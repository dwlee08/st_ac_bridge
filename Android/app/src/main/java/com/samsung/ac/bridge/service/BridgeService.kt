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
import com.samsung.ac.bridge.ac.AcController
import com.samsung.ac.bridge.ac.MockAcController
import com.samsung.ac.bridge.ac.RealAcController
import com.samsung.ac.bridge.afterblow.AfterBlowManager
import com.samsung.ac.bridge.ew11.EW11Client
import com.samsung.ac.bridge.icool.IcoolManager
import com.samsung.ac.bridge.network.TcpServer
import com.samsung.ac.bridge.state.OutdoorStore
import com.samsung.ac.bridge.state.StateStore
import kotlinx.coroutines.*
import java.util.concurrent.ConcurrentHashMap

class BridgeService : Service() {
    private val serviceScope = CoroutineScope(Dispatchers.Default + Job())
    private lateinit var ew11: EW11Client
    private lateinit var tcpServer: TcpServer
    private lateinit var icoolManager: IcoolManager
    private lateinit var afterblowManager: AfterBlowManager
    // 여러 코루틴/스레드(TCP 세션, 제어 루프, EW11 수신)가 공유하므로 동시성 안전 맵.
    private val stores = ConcurrentHashMap<String, StateStore>()
    private val controllers = ConcurrentHashMap<String, AcController>()
    private val outdoorStore = OutdoorStore()

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
        val mockMode = intent?.getBooleanExtra("mock_mode", false) ?: false

        startForeground(NOTIFICATION_ID, createNotification())

        serviceScope.launch {
            try {
                icoolManager = IcoolManager(stores, controllers)
                afterblowManager = AfterBlowManager(stores, controllers, icoolManager)
                tcpServer = TcpServer(serverPort, stores, controllers, icoolManager, afterblowManager, outdoorStore)

                if (mockMode) {
                    seedMockUnit("200000")
                    Log.i(TAG, "Mock mode — pre-registered mock unit, EW11 disabled")
                } else {
                    ew11 = EW11Client(ew11Host, ew11Port, stores, outdoorStore) { uid, address ->
                        // 유닛 자동 발견 시 컨트롤러 생성 (send 경로 확보)
                        controllers[uid] = RealAcController(uid, address, stores[uid]!!, ew11)
                        Log.i(TAG, "Created controller for unit: $uid")
                    }
                    launch { ew11ConnectionLoop() }
                }

                launch { tcpServer.start() }
                launch { icoolManager.runLoop() }
                launch { afterblowManager.runLoop() }
            } catch (e: Exception) {
                Log.e(TAG, "Service initialization error", e)
                stopSelf()
            }
        }

        return START_STICKY
    }

    private suspend fun ew11ConnectionLoop() = coroutineScope {
        while (isActive) {
            if (ew11.connect()) {
                ew11.receiveLoop()   // 에러/EOF 시 리턴 → 아래에서 재연결
                ew11.disconnect()
                Log.w(TAG, "EW11 disconnected, reconnecting in ${RECONNECT_DELAY_MS}ms")
            } else {
                Log.w(TAG, "EW11 connection failed, retrying in ${RECONNECT_DELAY_MS}ms")
            }
            delay(RECONNECT_DELAY_MS)
        }
    }

    private suspend fun seedMockUnit(uid: String) {
        val store = StateStore()
        store.update(mapOf(
            "power" to false, "mode" to "cool", "target_temp" to 24.0f,
            "current_temp" to 28.0f, "humidity" to 60, "fan_mode" to "auto",
        ))
        stores[uid] = store
        controllers[uid] = MockAcController(uid, store)
    }

    override fun onDestroy() {
        Log.i(TAG, "BridgeService destroyed")
        serviceScope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID, "AC Bridge Service", NotificationManager.IMPORTANCE_LOW
            ).apply { description = "AC Bridge is running in the background" }
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun createNotification(): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("AC Bridge")
            .setContentText("Bridge service is running")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .build()

    companion object {
        private const val TAG = "BridgeService"
        private const val CHANNEL_ID = "ac_bridge_service"
        private const val NOTIFICATION_ID = 1001
        private const val RECONNECT_DELAY_MS = 5000L
    }
}
