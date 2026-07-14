package com.samsung.ac.bridge.icool

import android.util.Log
import com.samsung.ac.bridge.protocol.AcStatus
import com.samsung.ac.bridge.state.StateStore
import kotlinx.coroutines.*
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

class IcoolState(
    val uid: String,
    var active: Boolean = false,
    var target: Float = 24.0f,
    var windFree: Boolean = false,
    var savedState: AcStatus? = null,
    // Timer (independent from icool)
    var durationMin: Int = 0,
    var timerSec: Float? = null,
    var timerLast: Long? = null,
    // Tuning parameters
    var margin: Float = MARGIN,
    var blowOffset: Float = BLOW_OFFSET,
    var humLow: Int = HUM_LOW,
    var humHigh: Int = HUM_HIGH,
    var humBiasMax: Float = HUM_BIAS_MAX,
    var blowFan: String = FAN_BLOW,
    var blowVane: String = VANE_BLOW,
)

class IcoolManager(private val stores: Map<String, StateStore>) {
    private val states = mutableMapOf<String, IcoolState>()

    fun status(uid: String): Map<String, Any> {
        val st = states[uid] ?: return mapOf("icool_active" to false, "timer_min" to 0)
        val timerMin = when {
            st.timerSec != null -> max(1, (st.timerSec!! / 60).toInt())
            st.durationMin < 0 -> -1
            else -> 0
        }
        return mapOf("icool_active" to st.active, "timer_min" to timerMin)
    }

    suspend fun start(uid: String, target: Float? = null, config: Map<String, Any?>? = null) {
        val store = stores[uid] ?: run {
            Log.w(TAG, "start: unknown unit $uid")
            return
        }
        val st = states.getOrPut(uid) { IcoolState(uid) }
        val wasActive = st.active
        if (config != null) applyConfig(st, config)
        if (target != null) st.target = clamp(target)
        st.active = true
        applyStart(st, store, fresh = !wasActive)
        Log.i(TAG, "$uid icool start target=${st.target}")
    }

    suspend fun stop(uid: String, reason: String = "user") {
        val st = states[uid] ?: return
        if (!st.active) return
        st.active = false
        val saved = st.savedState
        st.savedState = null
        Log.i(TAG, "$uid icool stop ($reason)")
        restore(uid, saved, reason)
    }

    suspend fun setDuration(uid: String, durationMin: Int) {
        val st = states.getOrPut(uid) { IcoolState(uid) }
        val m = if (durationMin < 0) -1 else min(720, durationMin)
        st.durationMin = m
        if (m > 0) {
            st.timerSec = (m * 60).toFloat()
            st.timerLast = System.currentTimeMillis()
        } else {
            st.timerSec = null
            st.timerLast = null
        }
        Log.i(TAG, "$uid timer set ${m}min")
    }

    suspend fun runLoop() = coroutineScope {
        Log.i(TAG, "control loop started (tick=${TICK_SEC}s)")
        while (isActive) {
            try {
                tickAll()
            } catch (e: Exception) {
                Log.e(TAG, "tick error", e)
            }
            delay(TICK_SEC * 1000)
        }
    }

    private suspend fun tickAll() {
        for ((uid, st) in states.toList()) {
            if (st.timerSec != null) checkTimer(uid, st)
            if (st.active) tick(uid, st)
        }
    }

    private suspend fun checkTimer(uid: String, st: IcoolState) {
        val store = stores[uid] ?: return
        val status = store.get()
        val powered = status.power
        val now = System.currentTimeMillis()
        if (st.timerSec == null) return
        if (!powered) {
            st.timerLast = now
            return
        }
        if (st.timerLast != null) {
            val elapsed = (now - st.timerLast!!) / 1000f
            st.timerSec = st.timerSec!! - elapsed
        }
        st.timerLast = now
        if (st.timerSec!! <= 0) {
            st.timerSec = null
            st.timerLast = null
            st.durationMin = 0
            st.active = false
            // TODO: send power off command
            Log.i(TAG, "$uid timer expired → AC power OFF")
        }
    }

    private suspend fun tick(uid: String, st: IcoolState) {
        val store = stores[uid] ?: return
        val status = store.get()
        if (!st.active) return
        if (deviated(status, st)) {
            st.active = false
            Log.i(TAG, "$uid icool stop (external change)")
            return
        }
        val cur = status.currentTemp ?: return
        if (cur < MIN_VALID_TEMP) return
        control(uid, st, status, cur, status.humidity)
    }

    private suspend fun control(uid: String, st: IcoolState, status: AcStatus, cur: Float, humidity: Int?) {
        val eff = cur + humBias(humidity, st.humLow, st.humHigh, st.humBiasMax)
        val wf = decide(eff, st.target, st.windFree, st.margin)
        if (wf && !st.windFree) {
            st.windFree = true
            Log.i(TAG, "$uid 체감 $eff<목표 → 무풍 ON")
        } else if (!wf && st.windFree) {
            st.windFree = false
            Log.i(TAG, "$uid 체감 $eff>목표 → 무풍 OFF")
        }
    }

    private suspend fun applyStart(st: IcoolState, store: StateStore, fresh: Boolean) {
        val status = store.get()
        if (fresh) {
            st.savedState = status.copy()
        }
        val cur = status.currentTemp ?: 0f
        val eff = cur + humBias(status.humidity, st.humLow, st.humHigh, st.humBiasMax)
        val wf = cur >= MIN_VALID_TEMP && decide(eff, st.target, false, st.margin)
        st.windFree = wf
        // TODO: send apply_settings to AC
    }

    private fun deviated(status: AcStatus, st: IcoolState): Boolean {
        if (!status.power) return true
        if (status.mode != "cool") return true
        if (st.windFree) {
            if (!status.windFree) return true
            if (abs(status.targetTemp - st.target) > 0.05f) return true
        } else {
            if (status.windFree) return true
            if (status.fanMode != st.blowFan) return true
            if (abs(status.targetTemp - st.target + st.blowOffset) > 0.05f) return true
        }
        return false
    }

    private suspend fun restore(uid: String, saved: AcStatus?, reason: String) {
        // TODO: send restore command to AC
        Log.i(TAG, "$uid restored ($reason)")
    }

    private fun applyConfig(st: IcoolState, config: Map<String, Any?>) {
        (config["margin"] as? Number)?.let { st.margin = maxOf(0.1f, minOf(5f, it.toFloat())) }
        (config["blow_offset"] as? Number)?.let { st.blowOffset = maxOf(0f, minOf(5f, it.toFloat())) }
        (config["hum_low"] as? Number)?.let { st.humLow = maxOf(0, minOf(100, it.toInt())) }
        (config["hum_high"] as? Number)?.let { st.humHigh = maxOf(0, minOf(100, it.toInt())) }
        (config["hum_bias_max"] as? Number)?.let { st.humBiasMax = maxOf(0f, minOf(5f, it.toFloat())) }
        (config["blow_fan"] as? String)?.takeIf { it in BLOW_FANS }?.let { st.blowFan = it }
        (config["blow_vane"] as? String)?.takeIf { it in VANE_MODES }?.let { st.blowVane = it }
        if (st.humHigh <= st.humLow) {
            st.humHigh = min(100, st.humLow + 1)
        }
    }

    companion object {
        private const val TAG = "IcoolManager"
        private const val MARGIN = 0.5f
        private const val BLOW_OFFSET = 1.0f
        private const val FAN_BLOW = "high"
        private const val VANE_BLOW = "all"
        private const val HUM_LOW = 65
        private const val HUM_HIGH = 80
        private const val HUM_BIAS_MAX = 1.0f
        private const val TICK_SEC = 5L
        private const val MIN_VALID_TEMP = 5.0f
        private val BLOW_FANS = setOf("auto", "low", "medium", "high")
        private val VANE_MODES = setOf("fixed", "vertical", "horizontal", "all")

        private fun clamp(t: Float) = maxOf(16f, minOf(32f, t))

        private fun humBias(humidity: Int?, low: Int = HUM_LOW, high: Int = HUM_HIGH, biasMax: Float = HUM_BIAS_MAX): Float {
            if (humidity == null || humidity <= low) return 0f
            if (high <= low) return biasMax
            return biasMax * minOf(1f, (humidity - low).toFloat() / (high - low))
        }

        private fun decide(cur: Float, target: Float, prevWf: Boolean, margin: Float = MARGIN): Boolean {
            val delta = cur - target
            return if (prevWf) delta < margin else delta < -margin
        }
    }
}
