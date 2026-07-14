package com.samsung.ac.bridge.state

import com.samsung.ac.bridge.protocol.OutdoorStatus
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** 실외기 공용 상태(전력/에너지/외기온도 등). Python OutdoorStore 대응. */
class OutdoorStore {
    private val mutex = Mutex()
    private var status = OutdoorStatus()

    suspend fun get(): OutdoorStatus = mutex.withLock { status }

    suspend fun update(updates: Map<String, Any?>) = mutex.withLock {
        var s = status
        for ((k, v) in updates) {
            s = when (k) {
                "power_w" -> s.copy(powerW = (v as? Number)?.toInt())
                "cumulative_energy_wh" -> s.copy(cumulativeEnergyWh = (v as? Number)?.toInt())
                "outdoor_temp" -> s.copy(outdoorTemp = (v as? Number)?.toFloat())
                "current_a" -> s.copy(currentA = (v as? Number)?.toFloat())
                "voltage_v" -> s.copy(voltageV = (v as? Number)?.toInt())
                "odu_mode" -> s.copy(oduMode = v as? String ?: s.oduMode)
                "heat_cool" -> s.copy(heatCool = v as? String ?: s.heatCool)
                else -> s
            }
        }
        status = s
    }
}
