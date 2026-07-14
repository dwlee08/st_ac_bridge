package com.samsung.ac.bridge.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import com.samsung.ac.bridge.R
import com.samsung.ac.bridge.ew11.EW11Client
import com.samsung.ac.bridge.icool.IcoolManager
import com.samsung.ac.bridge.network.TcpServer
import com.samsung.ac.bridge.state.StateStore
import kotlinx.coroutines.*

class BridgeService : Service() {
    private val serviceScope = CoroutineScope(Dispatchers.Default + Job())
    private lateinit var ew11: EW11Client
    private lateinit var tcpServer: TcpServer
    private lateinit var icoolManager: IcoolManager
    private val stores = mutableMapOf<String, StateStore>()

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "BridgeService created")
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Log.i(TAG, "BridgeService started")

        val ew11Host = intent?.getStringExtra("ew11_host") ?: "192.168.0.38"
        val ew11Port = intent?.getIntExtra("ew11_port", 8899) ?: 8899
        val serverPort = intent?.getIntExtra("server_port", 8888) ?: 8888

        startForeground(NOTIFICATION_ID, createNotification())

        serviceScope.launch {
            try {
                // Initialize managers
                icoolManager = IcoolManager(stores)
                tcpServer = TcpServer(serverPort, stores, icoolManager)
                ew11 = EW11Client(ew11Host, ew11Port, stores)

                // Start TCP server
                launch {
                    tcpServer.start()
                }

                // Start EW11 connection loop
                launch {
                    while (isActive) {
                        if (!ew11.isConnected) {
                            if (ew11.connect()) {
                                Log.i(TAG, "EW11 connected")
                                ew11.receiveLoop { data ->
                                    handleEW11Packet(data)
                                }
                            } else {
                                Log.w(TAG, "EW11 connection failed, retrying...")
                                delay(5000)
                            }
                        } else {
                            delay(1000)
                        }
                    }
                }

                // Start icool control loop
                launch {
                    icoolManager.runLoop()
                }
            } catch (e: Exception) {
                Log.e(TAG, "Service initialization error", e)
                stopSelf()
            }
        }

        return START_STICKY
    }

    override fun onDestroy() {
        Log.i(TAG, "BridgeService destroyed")
        serviceScope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private suspend fun handleEW11Packet(data: ByteArray) {
        // Parse packet and update state
        try {
            // TODO: Parse C014, C016, etc.
            Log.d(TAG, "EW11 packet received: ${data.size} bytes")
        } catch (e: Exception) {
            Log.e(TAG, "Packet parsing error", e)
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "AC Bridge Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "AC Bridge is running in the background"
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    private fun createNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("AC Bridge")
            .setContentText("Bridge service is running")
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    companion object {
        private const val TAG = "BridgeService"
        private const val CHANNEL_ID = "ac_bridge_service"
        private const val NOTIFICATION_ID = 1001
    }
}
