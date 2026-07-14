package com.samsung.ac.bridge.ew11

import android.util.Log
import com.samsung.ac.bridge.protocol.*
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
    private var lastRxTime = System.currentTimeMillis()
    private var rxBuffer = byteArrayOf()

    val isConnected: Boolean
        get() = socket?.isConnected == true && !socket!!.isClosed

    suspend fun connect(): Boolean = withContext(Dispatchers.IO) {
        try {
            socket = Socket(host, port)
            reader = socket!!.getInputStream()
            writer = socket!!.getOutputStream()
            rxBuffer = byteArrayOf()
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
                waitBusIdle()
                writer?.write(data)
                writer?.flush()
                Log.i(TAG, "EW11 TX: ${data.joinToString("") { "%02x".format(it) }}")
            } catch (e: Exception) {
                Log.e(TAG, "EW11 send failed", e)
                throw e
            }
        }
    }

    suspend fun receiveLoop() = withContext(Dispatchers.IO) {
        val buffer = ByteArray(8192)
        while (isActive) {
            try {
                val n = reader?.read(buffer) ?: return@withContext
                if (n > 0) {
                    lastRxTime = System.currentTimeMillis()
                    rxBuffer += buffer.sliceArray(0 until n)
                    Log.d(TAG, "EW11 RX: ${buffer.take(n).joinToString("") { "%02x".format(it) }}")
                    processPackets()
                }
            } catch (e: Exception) {
                Log.e(TAG, "EW11 receive error", e)
                if (isActive) {
                    delay(RECONNECT_DELAY)
                }
            }
        }
    }

    private suspend fun processPackets() {
        val (packets, remaining) = PacketParser.extractPackets(rxBuffer)
        rxBuffer = remaining

        for (pkt in packets) {
            when (pkt.msgType) {
                PacketProtocol.MSG_TYPE_STATUS -> handleStatus(pkt)
                PacketProtocol.MSG_TYPE_ACK -> handleAck(pkt)
                else -> Log.d(TAG, "Unknown message type: ${pkt.msgType.toString(16)}")
            }
        }
    }

    private suspend fun handleStatus(pkt: ParsedPacket) {
        val src = pkt.src
        if (src.size >= 3) {
            val uid = src.joinToString("") { "%02X".format(it) }
            val updates = when {
                src[0].toInt() == 0x10 -> StateDecoder.decodeOutdoorCodes(pkt.codes)
                else -> StateDecoder.decodeCodes(pkt.codes)
            }
            val store = stores[uid]
            if (store != null) {
                store.update(updates)
                Log.d(TAG, "Updated $uid: $updates")
            } else {
                Log.d(TAG, "Unknown unit: $uid")
            }
        }
    }

    private suspend fun handleAck(pkt: ParsedPacket) {
        Log.i(TAG, "ACK received from ${pkt.src.joinToString("") { "%02X".format(it) }}")
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
