package com.samsung.ac.bridge.ew11

import android.util.Log
import com.samsung.ac.bridge.state.StateStore
import kotlinx.coroutines.*
import java.net.Socket
import kotlin.math.min

class EW11Client(
    private val host: String,
    private val port: Int,
    private val stores: Map<String, StateStore>,
) {
    private var socket: Socket? = null
    private var reader: Socket.InputStream? = null
    private var writer: Socket.OutputStream? = null
    private val sendLock = Any()
    private val buf = ByteArray(8192)
    private var lastRxTime = System.currentTimeMillis()

    val isConnected: Boolean
        get() = socket?.isConnected == true && !socket!!.isClosed

    suspend fun connect(): Boolean = withContext(Dispatchers.IO) {
        try {
            socket = Socket(host, port)
            reader = socket!!.getInputStream()
            writer = socket!!.getOutputStream()
            Log.i(TAG, "EW11 connected: $host:$port")
            true
        } catch (e: Exception) {
            Log.e(TAG, "EW11 connection failed", e)
            false
        }
    }

    suspend fun disconnect() = withContext(Dispatchers.IO) {
        try {
            reader?.close()
            writer?.close()
            socket?.close()
        } catch (e: Exception) {
            Log.w(TAG, "Error closing socket", e)
        }
    }

    suspend fun send(data: ByteArray) = withContext(Dispatchers.IO) {
        synchronized(sendLock) {
            if (!isConnected) throw RuntimeException("EW11 not connected")
            try {
                writer?.write(data)
                writer?.flush()
                Log.i(TAG, "EW11 TX: ${data.joinToString("") { "%02x".format(it) }}")
            } catch (e: Exception) {
                Log.e(TAG, "EW11 send failed", e)
                throw e
            }
        }
    }

    suspend fun receiveLoop(onPacket: suspend (data: ByteArray) -> Unit) = withContext(Dispatchers.IO) {
        val buffer = ByteArray(8192)
        while (isActive) {
            try {
                val n = reader?.read(buffer) ?: return@withContext
                if (n > 0) {
                    lastRxTime = System.currentTimeMillis()
                    Log.d(TAG, "EW11 RX: ${buffer.take(n).joinToString("") { "%02x".format(it) }}")
                    onPacket(buffer.take(n).toByteArray())
                }
            } catch (e: Exception) {
                Log.e(TAG, "EW11 receive error", e)
                if (isActive) {
                    delay(RECONNECT_DELAY)
                }
            }
        }
    }

    private suspend fun waitBusIdle() {
        val elapsed = System.currentTimeMillis() - lastRxTime
        if (elapsed < BUS_IDLE_MS) {
            delay(BUS_IDLE_MS - elapsed)
        }
    }

    companion object {
        private const val TAG = "EW11Client"
        private const val RECONNECT_DELAY = 5000L
        private const val BUS_IDLE_MS = 100L
    }
}
