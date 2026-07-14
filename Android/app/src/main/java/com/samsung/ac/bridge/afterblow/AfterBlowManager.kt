package com.samsung.ac.bridge.afterblow

import android.util.Log
import com.samsung.ac.bridge.ac.AcController
import com.samsung.ac.bridge.icool.IcoolManager
import com.samsung.ac.bridge.protocol.AcStatus
import com.samsung.ac.bridge.state.StateStore
import kotlinx.coroutines.*
import kotlin.math.max
import kotlin.math.min

class AfterBlowState(
    val uid: String,
    var enabled: Boolean = false,
    var powerOnAt: Long? = null,
    var wasPowered: Boolean = false,
    var drying: Boolean = false,
    var dryDeadline: Long? = null,
    var savedState: AcStatus? = null,
    var savedAuto: Boolean = false,
    var ratio: Int = RATIO_DEFAULT,
    var maxMin: Int = MAX_MIN_DEFAULT,
    var minMin: Int = MIN_MIN_DEFAULT,
)

class AfterBlowManager(
    private val stores: Map<String, StateStore>,
    private val controllers: Map<String, AcController> = emptyMap(),
    private val icoolManager: IcoolManager? = null,
) {
    private val states = mutableMapOf<String, AfterBlowState>()

    fun status(uid: String): Map<String, Any> {
        val st = states[uid]
        val out = mutableMapOf<String, Any>("after_blow_enabled" to (st?.enabled ?: false))
        if (st?.enabled == true) {
            out["auto_clean"] = false
        }
        if (st?.drying == true) {
            out["power"] = false
        }
        return out
    }

    suspend fun setEnabled(uid: String, on: Boolean, ratio: Int? = null, maxMin: Int? = null, minMin: Int? = null) {
        val st = states.getOrPut(uid) { AfterBlowState(uid) }
        st.enabled = on
        if (ratio != null) st.ratio = max(20, min(100, ratio))
        if (maxMin != null) st.maxMin = max(1, maxMin)
        if (minMin != null) st.minMin = max(0, minMin)
        Log.i(TAG, "$uid afterblow enabled=$on (ratio=${st.ratio}% max=${st.maxMin}min min=${st.minMin}min)")
    }

    suspend fun onPowerOff(uid: String): Boolean {
        val ctrl = controllers[uid] ?: return false
        val store = stores[uid] ?: return false
        val st = states[uid] ?: return false
        if (!st.enabled) return false

        val status = store.get()
        if (st.drying) return true
        if (!status.power) return false

        val now = System.currentTimeMillis()
        val runSec = if (st.powerOnAt != null) (now - st.powerOnAt!!) / 1000f else 0f
        if (runSec < st.minMin * 60) return false

        val drySec = min(runSec * st.ratio / 100f, (st.maxMin * 60).toFloat())
        st.savedState = status.copy()
        st.savedAuto = status.autoClean
        st.drying = true
        st.dryDeadline = now + (drySec * 1000).toLong()

        // Stop icool if running
        if (icoolManager != null) {
            icoolManager.stop(uid, "after_blow")
        }

        // Send AC commands
        ctrl.setAutoClean(false)
        ctrl.applySettings(mapOf(
            "power" to true,
            "mode" to "fanOnly",
            "fan_mode" to "high",
            "vane_vertical" to false,
            "vane_horizontal" to false,
            "wind_free" to false,
            "long_wind" to false,
        ))
        Log.i(TAG, "$uid afterblow start: run=${runSec}s → drying ${drySec}min (auto_clean OFF)")
        return true
    }

    suspend fun resume(uid: String): Boolean {
        val st = states[uid] ?: return false
        if (!st.drying) return false

        val saved = st.savedState
        val savedAuto = st.savedAuto
        st.drying = false
        st.dry_deadline = null
        st.savedState = null

        restore(uid, saved, savedAuto, "app power ON")
        return true
    }

    suspend fun runLoop() = coroutineScope {
        Log.i(TAG, "loop started (tick=${TICK_SEC}s)")
        while (isActive) {
            try {
                for (uid in stores.keys.toList()) {
                    val st = states.getOrPut(uid) { AfterBlowState(uid) }
                    tick(uid, st)
                }
            } catch (e: Exception) {
                Log.e(TAG, "tick error", e)
            }
            delay(TICK_SEC * 1000)
        }
    }

    private suspend fun tick(uid: String, st: AfterBlowState) {
        val ctrl = controllers[uid] ?: return
        val store = stores[uid] ?: return
        val status = store.get()
        val now = System.currentTimeMillis()

        if (!st.drying) {
            if (status.power && !st.wasPowered) {
                st.powerOnAt = now
            }
            st.wasPowered = status.power
            return
        }

        // Drying in progress
        when {
            st.dryDeadline != null && now >= st.dryDeadline!! -> {
                // Timer expired
                val savedAuto = st.savedAuto
                st.drying = false
                st.dryDeadline = null
                st.savedState = null
                st.wasPowered = false
                ctrl.setPower(false)
                ctrl.setAutoClean(savedAuto)
                Log.i(TAG, "$uid afterblow complete → power OFF (auto_clean=${savedAuto})")
            }

            !status.power -> {
                // Remote power OFF during drying
                st.drying = false
                st.dryDeadline = null
                st.savedState = null
                st.wasPowered = false
                Log.i(TAG, "$uid afterblow external power OFF → stop")
            }

            hasBlowChanges(status) -> {
                // Remote mode change during drying
                val saved = st.savedState
                val savedAuto = st.savedAuto
                st.drying = false
                st.dryDeadline = null
                st.savedState = null
                restore(uid, ctrl, saved, savedAuto, "remote adjustment during drying")
            }
        }
    }

    private suspend fun restore(uid: String, ctrl: AcController, saved: AcStatus?, savedAuto: Boolean, why: String) {
        if (saved == null) return
        val settings = mapOf(
            "power" to saved.power,
            "mode" to saved.mode,
            "target_temp" to saved.targetTemp,
            "fan_mode" to saved.fanMode,
            "vane_vertical" to saved.vaneVertical,
            "vane_horizontal" to saved.vaneHorizontal,
            "wind_free" to saved.windFree,
            "long_wind" to saved.longWind,
        )
        ctrl.applySettings(settings)
        ctrl.setAutoClean(savedAuto)
        Log.i(TAG, "$uid afterblow restored ($why)")
    }

    private fun hasBlowChanges(status: AcStatus): Boolean {
        return status.mode != "fanOnly" || status.fanMode != "high" ||
                status.vaneVertical || status.vaneHorizontal
    }

    companion object {
        private const val TAG = "AfterBlowManager"
        private const val TICK_SEC = 5L
        private const val RATIO_DEFAULT = 50
        private const val MAX_MIN_DEFAULT = 60
        private const val MIN_MIN_DEFAULT = 3
    }
}
