package com.samsung.ac.bridge.afterblow

import android.util.Log
import com.samsung.ac.bridge.ac.AcController
import com.samsung.ac.bridge.icool.IcoolManager
import com.samsung.ac.bridge.protocol.AcStatus
import com.samsung.ac.bridge.state.StateStore
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.concurrent.ConcurrentHashMap
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
) {
    val lock = Mutex()
}

class AfterBlowManager(
    private val stores: MutableMap<String, StateStore>,
    private val controllers: Map<String, AcController> = emptyMap(),
    private val icoolManager: IcoolManager? = null,
) {
    private val states = ConcurrentHashMap<String, AfterBlowState>()

    fun status(uid: String): Map<String, Any> {
        val st = states[uid]
        val out = mutableMapOf<String, Any>("after_blow_enabled" to (st?.enabled ?: false))
        if (st?.enabled == true) out["auto_clean"] = false      // 엣지엔 자동건조 off로 표시
        if (st?.drying == true) out["power"] = false            // 송풍 중 내부 전원 OFF로 마스킹
        return out
    }

    suspend fun setEnabled(uid: String, on: Boolean, ratio: Int? = null, maxMin: Int? = null, minMin: Int? = null) {
        val st = states.getOrPut(uid) { AfterBlowState(uid) }
        st.lock.withLock {
            st.enabled = on
            if (ratio != null) st.ratio = max(20, min(100, ratio))
            if (maxMin != null) st.maxMin = max(1, maxMin)
            if (minMin != null) st.minMin = max(0, minMin)
        }
        Log.i(TAG, "$uid afterblow enabled=$on (ratio=${st.ratio}% max=${st.maxMin}min min=${st.minMin}min)")
    }

    /** 앱/브릿지 경유 전원 OFF 위임. true를 반환하면 호출측은 실제 setPower(false)를 하지 않는다. */
    suspend fun onPowerOff(uid: String): Boolean {
        val ctrl = controllers[uid] ?: return false
        val store = stores[uid] ?: return false
        val st = states[uid] ?: return false
        if (!st.enabled) return false

        val status = store.get()
        var drySec = 0f
        st.lock.withLock {
            if (st.drying) return true                  // 이미 건조 중 — 중복 off 무시
            if (!status.power) return false             // 이미 꺼져 있음 → 정상 처리
            val now = System.currentTimeMillis()
            val runSec = st.powerOnAt?.let { (now - it) / 1000f } ?: 0f
            if (runSec < st.minMin * 60) return false   // 너무 짧음 → 건조 스킵
            drySec = min(runSec * st.ratio / 100f, (st.maxMin * 60).toFloat())
            st.savedState = status.copy()
            st.savedAuto = status.autoClean
            st.drying = true
            st.dryDeadline = now + (drySec * 1000).toLong()
        }
        // icool 동작 중이면 정지(전원을 곧 끌 것이므로) — 락 밖에서
        icoolManager?.stop(uid, "after_blow")
        ctrl.setAutoClean(false)                        // 시작 직전에만 자동건조 끔(이중 건조 방지)
        ctrl.applySettings(BLOW_FIELDS)
        Log.i(TAG, "$uid afterblow start → 송풍 ${drySec / 60}분 (자동건조 OFF)")
        return true
    }

    /** 앱 전원 ON 위임. 건조 중이면 복원+종료하고 true. 아니면 false. */
    suspend fun resume(uid: String): Boolean {
        val ctrl = controllers[uid] ?: return false
        val st = states[uid] ?: return false
        val saved: AcStatus?
        val savedAuto: Boolean
        st.lock.withLock {
            if (!st.drying) return false
            saved = st.savedState
            savedAuto = st.savedAuto
            st.drying = false
            st.dryDeadline = null
            st.savedState = null
        }
        restore(uid, ctrl, saved, savedAuto, "앱 전원 ON")
        return true
    }

    suspend fun runLoop() = coroutineScope {
        Log.i(TAG, "loop started (tick=${TICK_SEC}s)")
        while (isActive) {
            try {
                // 기능 활성 여부와 무관하게 모든 유닛 tick — 전원 ON 시각을 항상 추적.
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
        val status = stores[uid]?.get() ?: return
        val now = System.currentTimeMillis()

        // 종료/복원 시 락 밖에서 처리하기 위한 신호
        var powerOff = false
        var savedAutoOnExpire = false
        var restoreSaved: AcStatus? = null
        var restoreAuto = false
        var doRestore = false

        st.lock.withLock {
            if (!st.drying) {
                if (status.power && !st.wasPowered) st.powerOnAt = now   // off→on 전이(리모컨 ON 포함)
                st.wasPowered = status.power
                return
            }
            // ── 건조 중 ──
            val deadline = st.dryDeadline
            when {
                deadline != null && now >= deadline -> {                // 1) 타이머 만료
                    savedAutoOnExpire = st.savedAuto
                    st.drying = false; st.dryDeadline = null; st.savedState = null; st.wasPowered = false
                    powerOff = true
                }
                !status.power -> {                                      // 2) 리모컨으로 꺼짐 → 복원 안 함
                    st.drying = false; st.dryDeadline = null; st.savedState = null; st.wasPowered = false
                    Log.i(TAG, "$uid 송풍 중 외부 전원 OFF → 종료")
                }
                hasBlowChanges(status) -> {                             // 3) 리모컨 설정 변경 → 복원
                    restoreSaved = st.savedState; restoreAuto = st.savedAuto
                    st.drying = false; st.dryDeadline = null; st.savedState = null
                    doRestore = true
                }
            }
        }

        if (powerOff) {
            ctrl.setPower(false)
            ctrl.setAutoClean(savedAutoOnExpire)   // 다음 전원 ON 시 반영
            Log.i(TAG, "$uid afterblow 완료 → 전원 OFF (자동건조 복원=$savedAutoOnExpire)")
        }
        if (doRestore) restore(uid, ctrl, restoreSaved, restoreAuto, "송풍 중 외부 조작")
    }

    private suspend fun restore(uid: String, ctrl: AcController, saved: AcStatus?, savedAuto: Boolean, why: String) {
        if (saved == null) return
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
        ctrl.setAutoClean(savedAuto)
        Log.i(TAG, "$uid afterblow 복원/종료 ($why): auto_clean=$savedAuto")
    }

    private fun hasBlowChanges(status: AcStatus): Boolean =
        status.mode != "fanOnly" || status.fanMode != "high" ||
                status.vaneVertical || status.vaneHorizontal

    companion object {
        private const val TAG = "AfterBlowManager"
        private const val TICK_SEC = 5L
        private const val RATIO_DEFAULT = 50
        private const val MAX_MIN_DEFAULT = 60
        private const val MIN_MIN_DEFAULT = 3

        // 건조(송풍) 단계에서 에어컨에 강제할 설정
        private val BLOW_FIELDS = mapOf(
            "power" to true, "mode" to "fanOnly", "fan_mode" to "high",
            "vane_vertical" to false, "vane_horizontal" to false,
            "wind_free" to false, "long_wind" to false,
        )
    }
}
