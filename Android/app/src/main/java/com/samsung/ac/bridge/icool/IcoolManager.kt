package com.samsung.ac.bridge.icool

import android.util.Log
import com.samsung.ac.bridge.ac.AcController
import com.samsung.ac.bridge.protocol.AcStatus
import com.samsung.ac.bridge.protocol.PacketProtocol
import com.samsung.ac.bridge.state.StateStore
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.min

// 설정온도 클램프는 프로토콜의 유효 범위(18~30℃)와 일치해야 한다. IcoolState/IcoolManager 공용.
internal fun clampTemp(t: Float) = max(PacketProtocol.TEMP_MIN, min(PacketProtocol.TEMP_MAX, t))

// IcoolState 생성자 기본값 — 튜닝 파라미터의 초기값.
private const val MARGIN = 0.5f
private const val BLOW_OFFSET = 1.0f
private const val FAN_BLOW = "high"
private const val VANE_BLOW = "all"
private const val HUM_LOW = 65
private const val HUM_HIGH = 80
private const val HUM_BIAS_MAX = 1.0f

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
) {
    // 유닛별 락 — 한 유닛의 AC 명령 대기가 다른 유닛의 tick/start/stop을 막지 않도록.
    val lock = Mutex()

    fun coolSp() = clampTemp(target - blowOffset)
}

class IcoolManager(
    private val stores: MutableMap<String, StateStore>,
    private val controllers: Map<String, AcController> = emptyMap(),
) {
    private val states = ConcurrentHashMap<String, IcoolState>()

    fun status(uid: String): Map<String, Any> {
        val st = states[uid] ?: return mapOf("icool_active" to false, "timer_min" to 0)
        val timerSec = st.timerSec
        val timerMin = when {
            timerSec != null -> max(1, ceil(timerSec / 60.0).toInt())
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
        st.lock.withLock {
            val wasActive = st.active
            if (config != null) applyConfig(st, config)
            if (target != null) st.target = clampTemp(target)
            st.active = true
            applyStart(st, store, fresh = !wasActive)
        }
        Log.i(TAG, "$uid icool start target=${st.target}")
    }

    suspend fun setConfig(uid: String, config: Map<String, Any?>) {
        val st = states.getOrPut(uid) { IcoolState(uid) }
        st.lock.withLock { applyConfig(st, config) }
        Log.i(TAG, "$uid icool config margin=${st.margin} blow_off=${st.blowOffset} " +
                "hum=${st.humLow}/${st.humHigh}/${st.humBiasMax} fan=${st.blowFan} vane=${st.blowVane}")
    }

    suspend fun stop(uid: String, reason: String = "user") {
        val st = states[uid] ?: return
        val saved: AcStatus?
        st.lock.withLock {
            if (!st.active) return
            st.active = false
            saved = st.savedState
            st.savedState = null
        }
        Log.i(TAG, "$uid icool stop ($reason)")
        restore(uid, saved, reason)
    }

    suspend fun setDuration(uid: String, durationMin: Int) {
        val st = states.getOrPut(uid) { IcoolState(uid) }
        st.lock.withLock {
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
        for ((uid, st) in states) {
            if (st.timerSec != null) checkTimer(uid, st)
            if (st.active) tick(uid, st)
        }
    }

    // 타이머(icool과 분리): 전원 ON일 때만 감소, 0 도달 시 AC 전원 OFF.
    private suspend fun checkTimer(uid: String, st: IcoolState) {
        val ctrl = controllers[uid] ?: return
        val store = stores[uid] ?: return
        val powered = store.get().power
        var expired = false
        st.lock.withLock {
            if (st.timerSec == null) return
            val now = System.currentTimeMillis()
            if (!powered) {
                st.timerLast = now
                return
            }
            st.timerLast?.let { st.timerSec = st.timerSec!! - (now - it) / 1000f }
            st.timerLast = now
            if (st.timerSec!! <= 0) {
                st.timerSec = null
                st.timerLast = null
                st.durationMin = 0
                st.active = false
                expired = true
            }
        }
        if (expired) {
            ctrl.setPower(false)
            Log.i(TAG, "$uid timer expired → AC power OFF")
        }
    }

    private suspend fun tick(uid: String, st: IcoolState) {
        val ctrl = controllers[uid] ?: return
        val status = stores[uid]?.get() ?: return
        st.lock.withLock {
            if (!st.active) return
            if (deviated(status, st)) {
                st.active = false
                Log.i(TAG, "$uid icool stop (external change)")
                return
            }
            val cur = status.currentTemp ?: return
            if (cur < MIN_VALID_TEMP) return
            control(uid, ctrl, st, cur, status.humidity)
        }
    }

    private suspend fun control(uid: String, ctrl: AcController, st: IcoolState, cur: Float, humidity: Int?) {
        val eff = cur + humBias(humidity, st.humLow, st.humHigh, st.humBiasMax)
        val wf = decide(eff, st.target, st.windFree, st.margin)
        if (wf && !st.windFree) {
            st.windFree = true
            ctrl.applySettings(windFreeFields(st))
            Log.i(TAG, "$uid 체감 $eff<목표 → 무풍 ON, 설정 ${st.target}")
        } else if (!wf && st.windFree) {
            st.windFree = false
            ctrl.applySettings(blowFields(st))
            Log.i(TAG, "$uid 체감 $eff>목표 → 무풍 OFF, 강풍, 설정 ${st.coolSp()}")
        }
    }

    private suspend fun applyStart(st: IcoolState, store: StateStore, fresh: Boolean) {
        val ctrl = controllers[st.uid] ?: return
        val status = store.get()
        if (fresh) st.savedState = status.copy()
        val cur = status.currentTemp ?: 0f
        val eff = cur + humBias(status.humidity, st.humLow, st.humHigh, st.humBiasMax)
        val wf = cur >= MIN_VALID_TEMP && decide(eff, st.target, false, st.margin)
        val stage = if (wf) windFreeFields(st) else blowFields(st)
        ctrl.applySettings(mapOf("power" to true, "mode" to "cool") + stage)
        st.windFree = wf
    }

    private fun windFreeFields(st: IcoolState): Map<String, Any?> = mapOf(
        "wind_free" to true,
        "long_wind" to false,
        "vane_vertical" to false,
        "vane_horizontal" to false,
        "target_temp" to clampTemp(st.target),
    )

    private fun blowFields(st: IcoolState): Map<String, Any?> {
        val (v, h) = vaneModePair(st.blowVane)
        return mapOf(
            "wind_free" to false,
            "long_wind" to false,
            "vane_vertical" to v,
            "vane_horizontal" to h,
            "fan_mode" to st.blowFan,
            "target_temp" to st.coolSp(),
        )
    }

    // 예상 상태와 어긋나면(외부 조작) icool 종료. Python _deviated 대응.
    private fun deviated(status: AcStatus, st: IcoolState): Boolean {
        if (!status.power) return true
        if (status.mode != "cool") return true
        if (st.windFree) {
            if (!status.windFree) return true
            if (abs(status.targetTemp - clampTemp(st.target)) > 0.05f) return true
        } else {
            if (status.windFree) return true
            val (v, h) = vaneModePair(st.blowVane)
            if (status.vaneVertical != v || status.vaneHorizontal != h) return true
            if (status.fanMode != st.blowFan) return true
            if (abs(status.targetTemp - st.coolSp()) > 0.05f) return true
        }
        return false
    }

    private suspend fun restore(uid: String, saved: AcStatus?, reason: String) {
        val ctrl = controllers[uid] ?: return
        if (saved == null) return
        if (!saved.power) {
            ctrl.setPower(false)
            Log.i(TAG, "$uid AC 전원 OFF ($reason, 시작 시 꺼져 있었음)")
        } else {
            ctrl.applySettings(mapOf(
                "power" to true,
                "mode" to saved.mode,
                "target_temp" to saved.targetTemp,
                "fan_mode" to saved.fanMode,
                "vane_vertical" to saved.vaneVertical,
                "vane_horizontal" to saved.vaneHorizontal,
                "wind_free" to saved.windFree,
                "long_wind" to saved.longWind,
            ))
            Log.i(TAG, "$uid 시작 시점 상태로 복원 ($reason)")
        }
    }

    private fun applyConfig(st: IcoolState, config: Map<String, Any?>) {
        (config["margin"] as? Number)?.let { st.margin = max(0.1f, min(5f, it.toFloat())) }
        (config["blow_offset"] as? Number)?.let { st.blowOffset = max(0f, min(5f, it.toFloat())) }
        (config["hum_low"] as? Number)?.let { st.humLow = max(0, min(100, it.toInt())) }
        (config["hum_high"] as? Number)?.let { st.humHigh = max(0, min(100, it.toInt())) }
        (config["hum_bias_max"] as? Number)?.let { st.humBiasMax = max(0f, min(5f, it.toFloat())) }
        (config["blow_fan"] as? String)?.takeIf { it in BLOW_FANS }?.let { st.blowFan = it }
        (config["blow_vane"] as? String)?.takeIf { it in VANE_MODES }?.let { st.blowVane = it }
        if (st.humHigh <= st.humLow) st.humHigh = min(100, st.humLow + 1)
    }

    companion object {
        private const val TAG = "IcoolManager"
        private const val TICK_SEC = 5L
        private const val MIN_VALID_TEMP = 5.0f
        private val BLOW_FANS = setOf("auto", "low", "medium", "high")
        private val VANE_MODES = setOf("fixed", "vertical", "horizontal", "all")

        private fun vaneModePair(mode: String): Pair<Boolean, Boolean> = when (mode) {
            "fixed" -> false to false
            "vertical" -> true to false
            "horizontal" -> false to true
            "all" -> true to true
            else -> true to true
        }

        private fun humBias(humidity: Int?, low: Int, high: Int, biasMax: Float): Float {
            if (humidity == null || humidity <= low) return 0f
            if (high <= low) return biasMax
            return biasMax * min(1f, (humidity - low).toFloat() / (high - low))
        }

        private fun decide(cur: Float, target: Float, prevWf: Boolean, margin: Float): Boolean {
            val delta = cur - target
            return if (prevWf) delta < margin else delta < -margin
        }
    }
}
