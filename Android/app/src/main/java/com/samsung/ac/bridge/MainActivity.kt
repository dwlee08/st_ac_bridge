package com.samsung.ac.bridge

import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.samsung.ac.bridge.service.BridgeService

class MainActivity : AppCompatActivity() {
    private lateinit var statusText: TextView
    private lateinit var startBtn: Button
    private lateinit var stopBtn: Button
    private var isServiceRunning = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusText = findViewById(R.id.status_text)
        startBtn = findViewById(R.id.start_btn)
        stopBtn = findViewById(R.id.stop_btn)

        startBtn.setOnClickListener { startService() }
        stopBtn.setOnClickListener { stopService() }

        updateStatus()
    }

    private fun startService() {
        val intent = Intent(this, BridgeService::class.java).apply {
            putExtra("ew11_host", "192.168.0.38")  // Configure as needed
            putExtra("ew11_port", 8899)
            putExtra("server_port", 8888)
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
