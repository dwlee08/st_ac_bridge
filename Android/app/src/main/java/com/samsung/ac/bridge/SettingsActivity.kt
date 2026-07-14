package com.samsung.ac.bridge

import android.content.Intent
import android.os.Bundle
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.samsung.ac.bridge.config.ConfigManager
import com.samsung.ac.bridge.service.BridgeService

class SettingsActivity : AppCompatActivity() {
    private lateinit var configManager: ConfigManager
    private lateinit var ew11HostInput: EditText
    private lateinit var ew11PortInput: EditText
    private lateinit var serverPortInput: EditText
    private lateinit var mockModeToggle: CheckBox
    private lateinit var saveBtn: Button
    private lateinit var cancelBtn: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        configManager = ConfigManager(this)

        ew11HostInput = findViewById(R.id.ew11_host_input)
        ew11PortInput = findViewById(R.id.ew11_port_input)
        serverPortInput = findViewById(R.id.server_port_input)
        mockModeToggle = findViewById(R.id.mock_mode_toggle)
        saveBtn = findViewById(R.id.save_btn)
        cancelBtn = findViewById(R.id.cancel_btn)

        loadConfig()

        saveBtn.setOnClickListener { saveConfig() }
        cancelBtn.setOnClickListener { finish() }
    }

    private fun loadConfig() {
        ew11HostInput.setText(configManager.ew11Host)
        ew11PortInput.setText(configManager.ew11Port.toString())
        serverPortInput.setText(configManager.serverPort.toString())
        mockModeToggle.isChecked = configManager.mockMode
    }

    private fun saveConfig() {
        try {
            val host = ew11HostInput.text.toString().trim()
            val port = ew11PortInput.text.toString().trim().toIntOrNull() ?: return showError("Invalid EW11 port")
            val serverPort = serverPortInput.text.toString().trim().toIntOrNull() ?: return showError("Invalid server port")
            val mockMode = mockModeToggle.isChecked

            if (host.isEmpty()) {
                showError("EW11 host cannot be empty")
                return
            }

            if (port !in 1..65535) {
                showError("EW11 port must be between 1 and 65535")
                return
            }

            if (serverPort !in 1..65535) {
                showError("Server port must be between 1 and 65535")
                return
            }

            configManager.ew11Host = host
            configManager.ew11Port = port
            configManager.serverPort = serverPort
            configManager.mockMode = mockMode

            Toast.makeText(this, "Settings saved", Toast.LENGTH_SHORT).show()
            finish()
        } catch (e: Exception) {
            showError("Error: ${e.message}")
        }
    }

    private fun showError(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }
}
