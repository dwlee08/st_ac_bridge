package com.samsung.ac.bridge.protocol

data class AcStatus(
    val power: Boolean = false,
    val mode: String = "cool",
    val targetTemp: Float = 24.0f,
    val currentTemp: Float? = null,
    val humidity: Int? = null,
    val fanMode: String = "auto",
    val vaneVertical: Boolean = false,
    val vaneHorizontal: Boolean = false,
    val windFree: Boolean = false,
    val longWind: Boolean = false,
    val autoClean: Boolean = false,
) {
    fun toMap(): Map<String, Any?> = mapOf(
        "power" to power,
        "mode" to mode,
        "target_temp" to targetTemp,
        "current_temp" to currentTemp,
        "humidity" to humidity,
        "fan_mode" to fanMode,
        "vane_vertical" to vaneVertical,
        "vane_horizontal" to vaneHorizontal,
        "wind_free" to windFree,
        "long_wind" to longWind,
        "auto_clean" to autoClean,
    )

    companion object {
        fun fromMap(map: Map<String, Any?>): AcStatus {
            return AcStatus(
                power = (map["power"] as? Boolean) ?: false,
                mode = (map["mode"] as? String) ?: "cool",
                targetTemp = ((map["target_temp"] as? Number)?.toFloat()) ?: 24.0f,
                currentTemp = (map["current_temp"] as? Number)?.toFloat(),
                humidity = (map["humidity"] as? Number)?.toInt(),
                fanMode = (map["fan_mode"] as? String) ?: "auto",
                vaneVertical = (map["vane_vertical"] as? Boolean) ?: false,
                vaneHorizontal = (map["vane_horizontal"] as? Boolean) ?: false,
                windFree = (map["wind_free"] as? Boolean) ?: false,
                longWind = (map["long_wind"] as? Boolean) ?: false,
                autoClean = (map["auto_clean"] as? Boolean) ?: false,
            )
        }
    }
}

data class OutdoorStatus(
    val powerW: Int? = null,
    val cumulativeEnergyWh: Int? = null,
    val outdoorTemp: Float? = null,
    val currentA: Float? = null,
    val voltageV: Int? = null,
    val oduMode: String = "STOP",
    val heatCool: String = "Undef",
) {
    fun toMap(): Map<String, Any?> = mapOf(
        "power_w" to powerW,
        "cumulative_energy_wh" to cumulativeEnergyWh,
        "outdoor_temp" to outdoorTemp,
        "current_a" to currentA,
        "voltage_v" to voltageV,
        "odu_mode" to oduMode,
        "heat_cool" to heatCool,
    )

    companion object {
        fun fromMap(map: Map<String, Any?>): OutdoorStatus {
            return OutdoorStatus(
                powerW = (map["power_w"] as? Number)?.toInt(),
                cumulativeEnergyWh = (map["cumulative_energy_wh"] as? Number)?.toInt(),
                outdoorTemp = (map["outdoor_temp"] as? Number)?.toFloat(),
                currentA = (map["current_a"] as? Number)?.toFloat(),
                voltageV = (map["voltage_v"] as? Number)?.toInt(),
                oduMode = (map["odu_mode"] as? String) ?: "STOP",
                heatCool = (map["heat_cool"] as? String) ?: "Undef",
            )
        }
    }
}
