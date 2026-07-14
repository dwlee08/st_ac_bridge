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
            result = when (k) {
                "power" -> result.copy(power = v as Boolean)
                "mode" -> result.copy(mode = v as String)
                "target_temp" -> result.copy(targetTemp = (v as Number).toFloat())
                "current_temp" -> result.copy(currentTemp = (v as? Number)?.toFloat())
                "humidity" -> result.copy(humidity = (v as? Number)?.toInt())
                "fan_mode" -> result.copy(fanMode = v as String)
                "vane_vertical" -> result.copy(vaneVertical = v as Boolean)
                "vane_horizontal" -> result.copy(vaneHorizontal = v as Boolean)
                "wind_free" -> result.copy(windFree = v as Boolean)
                "long_wind" -> result.copy(longWind = v as Boolean)
                "auto_clean" -> result.copy(autoClean = v as Boolean)
                else -> result
            }
        }
        return@withLock result
    }

    suspend fun update(vararg updates: Pair<String, Any?>) = mutex.withLock {
        updates.forEach { (k, v) ->
            if (isValidField(k)) {
                setField(k, v)
            }
        }
    }

    suspend fun setDesired(vararg updates: Pair<String, Any?>) = mutex.withLock {
        updates.forEach { (k, v) ->
            if (isDesiredField(k)) {
                desired[k] = v
            }
        }
    }

    suspend fun clearDesired() = mutex.withLock {
        desired.clear()
    }

    private fun setField(key: String, value: Any?) {
        reported = when (key) {
            "power" -> reported.copy(power = value as Boolean)
            "mode" -> reported.copy(mode = value as String)
            "target_temp" -> reported.copy(targetTemp = (value as Number).toFloat())
            "current_temp" -> reported.copy(currentTemp = (value as? Number)?.toFloat())
            "humidity" -> reported.copy(humidity = (value as? Number)?.toInt())
            "fan_mode" -> reported.copy(fanMode = value as String)
            "vane_vertical" -> reported.copy(vaneVertical = value as Boolean)
            "vane_horizontal" -> reported.copy(vaneHorizontal = value as Boolean)
            "wind_free" -> reported.copy(windFree = value as Boolean)
            "long_wind" -> reported.copy(longWind = value as Boolean)
            "auto_clean" -> reported.copy(autoClean = value as Boolean)
            else -> reported
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
