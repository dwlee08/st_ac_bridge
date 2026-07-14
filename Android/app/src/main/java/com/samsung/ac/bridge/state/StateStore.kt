package com.samsung.ac.bridge.state

import com.samsung.ac.bridge.protocol.AcStatus
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class StateStore {
    private val mutex = Mutex()
    private var reported = AcStatus()
    private val desired = mutableMapOf<String, Any?>()

    suspend fun get(): AcStatus = mutex.withLock {
        var result = reported
        for ((k, v) in desired) {
            result = applyField(result, k, v)
        }
        return@withLock result
    }

    suspend fun update(updates: Map<String, Any?>) = mutex.withLock {
        updates.forEach { (k, v) ->
            if (isValidField(k)) {
                reported = applyField(reported, k, v)
            }
        }
    }

    suspend fun setDesired(updates: Map<String, Any?>) = mutex.withLock {
        updates.forEach { (k, v) ->
            if (isDesiredField(k)) {
                desired[k] = v
            }
        }
    }

    suspend fun clearDesired() = mutex.withLock {
        desired.clear()
    }

    private fun applyField(status: AcStatus, key: String, value: Any?): AcStatus {
        return when (key) {
            "power" -> status.copy(power = value as Boolean)
            "mode" -> status.copy(mode = value as String)
            "target_temp" -> status.copy(targetTemp = (value as Number).toFloat())
            "current_temp" -> status.copy(currentTemp = (value as? Number)?.toFloat())
            "humidity" -> status.copy(humidity = (value as? Number)?.toInt())
            "fan_mode" -> status.copy(fanMode = value as String)
            "vane_vertical" -> status.copy(vaneVertical = value as Boolean)
            "vane_horizontal" -> status.copy(vaneHorizontal = value as Boolean)
            "wind_free" -> status.copy(windFree = value as Boolean)
            "long_wind" -> status.copy(longWind = value as Boolean)
            "auto_clean" -> status.copy(autoClean = value as Boolean)
            else -> status
        }
    }

    companion object {
        private val VALID_FIELDS = setOf(
            "power", "mode", "target_temp", "current_temp", "humidity",
            "fan_mode", "vane_vertical", "vane_horizontal", "wind_free", "long_wind", "auto_clean"
        )
        private val DESIRED_FIELDS = setOf(
            "power", "mode", "target_temp", "fan_mode",
            "vane_vertical", "vane_horizontal", "wind_free", "long_wind", "auto_clean"
        )

        fun isValidField(key: String) = VALID_FIELDS.contains(key)
        fun isDesiredField(key: String) = DESIRED_FIELDS.contains(key)
    }
}
