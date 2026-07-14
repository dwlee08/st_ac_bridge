package com.samsung.ac.bridge.ew11

import android.util.Log
import com.samsung.ac.bridge.protocol.*
import com.samsung.ac.bridge.state.OutdoorStore
import com.samsung.ac.bridge.state.StateStore
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.InputStream
import java.io.OutputStream
import java.net.Socket

class EW11Client(
    private val host: String,
    private val port: Int,
    private val stores: MutableMap<String, StateStore>,
    private val outdoorStore: OutdoorStore? = null,
    private val onUnitDiscovered: suspend (uid: String, address: ByteArray) -> Unit = { _, _ -> },
) {
    private var socket: Socket? = null
    private var reader: InputStream? = null
    private var writer: OutputStream? = null
    // 전송 직렬화 + 버스 idle 대기(waitBusIdle이 suspend라 synchronized 불가 → Mutex 사용).
    private val sendMutex = Mutex()
    @Volatile private var lastRxTime = System.currentTimeMillis()
    private var rxBuffer = byteArrayOf()

    val isConnected: Boolean
        get() = socket?.isConnected == true && !socket!!.isClosed

    suspend fun connect(): Boolean = withContext(Dispatchers.IO) {
        try {
            val s = Socket(host, port)
            socket = s
            reader = s.getInputStream()
            writer = s.getOutputStream()
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
        } finally {
            socket = null
            reader = null
            writer = null
        }
    }

    suspend fun send(data: ByteArray) = sendMutex.withLock {
        val out = writer ?: throw RuntimeException("EW11 not connected")
        waitBusIdle()
        withContext(Dispatchers.IO) {
            out.write(data)
            out.flush()
        }
        Log.i(TAG, "EW11 TX: ${data.hex()}")
    }

    /** 연결이 살아있는 동안 수신·파싱. 에러/EOF 시 리턴하여 상위 루프가 재연결하게 한다. */
    suspend fun receiveLoop() = withContext(Dispatchers.IO) {
        val buffer = ByteArray(8192)
        while (isActive) {
            val n = try {
                reader?.read(buffer) ?: return@withContext
            } catch (e: Exception) {
                Log.e(TAG, "EW11 receive error", e)
                return@withContext
            }
            if (n < 0) {
                Log.w(TAG, "EW11 stream closed (EOF)")
                return@withContext
            }
            if (n > 0) {
                lastRxTime = System.currentTimeMillis()
                rxBuffer += buffer.copyOfRange(0, n)
                // 정상 패킷을 못 찾고 무한히 쌓이는 것을 방지 (Python MAX_BUF 대응).
                if (rxBuffer.size > MAX_BUF) {
                    rxBuffer = rxBuffer.copyOfRange(rxBuffer.size - MAX_BUF, rxBuffer.size)
                }
                processPackets()
            }
        }
    }

    private suspend fun processPackets() {
        val (packets, remaining) = PacketParser.extractPackets(rxBuffer)
        rxBuffer = remaining
        for (pkt in packets) {
            when (pkt.msgType) {
                PacketProtocol.MSG_TYPE_STATUS -> handleStatus(pkt)
                PacketProtocol.MSG_TYPE_ACK -> Log.i(TAG, "ACK from ${pkt.src.hex()}")
                else -> Log.d(TAG, "Unknown message type: ${pkt.msgType.toString(16)}")
            }
        }
    }

    private suspend fun handleStatus(pkt: ParsedPacket) {
        val src = pkt.src
        if (src.size < 3) return

        // 실외기(10:00:00)는 AC 유닛이 아니라 실외기 공용 상태로 라우팅 (유닛 자동등록 금지).
        if (src[0].toInt() and 0xFF == OUTDOOR_PREFIX) {
            outdoorStore?.update(StateDecoder.decodeOutdoorCodes(pkt.codes))
            return
        }

        val uid = src.hex()
        var store = stores[uid]
        if (store == null) {
            store = StateStore()
            stores[uid] = store
            onUnitDiscovered(uid, src.copyOf())
            Log.i(TAG, "Auto-registered unit: $uid")
        }
        store.update(StateDecoder.decodeCodes(pkt.codes))
    }

    private suspend fun waitBusIdle() {
        val elapsed = System.currentTimeMillis() - lastRxTime
        if (elapsed < BUS_IDLE_MS) {
            delay(BUS_IDLE_MS - elapsed)
        }
    }

    // Python addr.hex()와 동일한 소문자 hex — uid가 기존 Edge Driver 등록값과 일치해야 함.
    private fun ByteArray.hex() = joinToString("") { "%02x".format(it) }

    companion object {
        private const val TAG = "EW11Client"
        private const val BUS_IDLE_MS = 100L
        private const val MAX_BUF = 8192
        private const val OUTDOOR_PREFIX = 0x10
    }
}
