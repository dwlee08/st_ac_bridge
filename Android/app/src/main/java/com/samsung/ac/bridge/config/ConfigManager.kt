package com.samsung.ac.bridge.config

import android.content.Context
import android.content.SharedPreferences

class ConfigManager(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    var ew11Host: String
        get() = prefs.getString(KEY_EW11_HOST, DEFAULT_EW11_HOST) ?: DEFAULT_EW11_HOST
        set(value) = prefs.edit().putString(KEY_EW11_HOST, value).apply()

    var ew11Port: Int
        get() = prefs.getInt(KEY_EW11_PORT, DEFAULT_EW11_PORT)
        set(value) = prefs.edit().putInt(KEY_EW11_PORT, value).apply()

    var serverPort: Int
        get() = prefs.getInt(KEY_SERVER_PORT, DEFAULT_SERVER_PORT)
        set(value) = prefs.edit().putInt(KEY_SERVER_PORT, value).apply()

    var mockMode: Boolean
        get() = prefs.getBoolean(KEY_MOCK_MODE, false)
        set(value) = prefs.edit().putBoolean(KEY_MOCK_MODE, value).apply()

    fun getAsIntent(): Map<String, Any> = mapOf(
        "ew11_host" to ew11Host,
        "ew11_port" to ew11Port,
        "server_port" to serverPort,
        "mock_mode" to mockMode,
    )

    companion object {
        private const val PREFS_NAME = "ac_bridge_config"
        private const val KEY_EW11_HOST = "ew11_host"
        private const val KEY_EW11_PORT = "ew11_port"
        private const val KEY_SERVER_PORT = "server_port"
        private const val KEY_MOCK_MODE = "mock_mode"

        const val DEFAULT_EW11_HOST = "192.168.0.38"
        const val DEFAULT_EW11_PORT = 8899
        const val DEFAULT_SERVER_PORT = 8888
    }
}
