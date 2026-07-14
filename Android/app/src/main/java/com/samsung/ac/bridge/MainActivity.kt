package com.samsung.ac.bridge

import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.samsung.ac.bridge.config.ConfigManager
import com.samsung.ac.bridge.service.BridgeService

class MainActivity : AppCompatActivity() {
    private lateinit var statusText: TextView
    private lateinit var startBtn: Button
    private lateinit var stopBtn: Button
    private lateinit var settingsBtn: Button
    private lateinit var configManager: ConfigManager
    private var isServiceRunning = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        configManager = ConfigManager(this)

        statusText = findViewById(R.id.status_text)
        startBtn = findViewById(R.id.start_btn)
        stopBtn = findViewById(R.id.stop_btn)
        settingsBtn = findViewById(R.id.settings_btn)

        startBtn.setOnClickListener { startService() }
        stopBtn.setOnClickListener { stopService() }
        settingsBtn.setOnClickListener { openSettings() }

        updateStatus()
    }

    private fun startService() {
        val intent = Intent(this, BridgeService::class.java).apply {
            putExtra("ew11_host", configManager.ew11Host)
            putExtra("ew11_port", configManager.ew11Port)
            putExtra("server_port", configManager.serverPort)
            putExtra("mock_mode", configManager.mockMode)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
        isServiceRunning = true
        updateStatus()
    }

    private fun stopService() {
        val intent = Intent(this, BridgeService::class.java)
        stopService(intent)
        isServiceRunning = false
        updateStatus()
    }

    private fun openSettings() {
        val intent = Intent(this, SettingsActivity::class.java)
        startActivity(intent)
    }

    private fun updateStatus() {
        statusText.text = if (isServiceRunning) {
            getString(R.string.connected)
        } else {
            getString(R.string.disconnected)
        }
        startBtn.isEnabled = !isServiceRunning
        stopBtn.isEnabled = isServiceRunning
    }
}
