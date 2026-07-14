package com.samsung.ac.bridge.network

import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.samsung.ac.bridge.icool.IcoolManager
import com.samsung.ac.bridge.state.StateStore
import kotlinx.coroutines.*
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.PrintWriter
import java.net.ServerSocket
import java.net.Socket

class TcpServer(
    private val port: Int = 8888,
    private val stores: Map<String, StateStore>,
    private val icoolManager: IcoolManager,
) {
    private val gson = Gson()
    private var serverSocket: ServerSocket? = null

    suspend fun start() = withContext(Dispatchers.IO) {
        try {
            serverSocket = ServerSocket(port)
            Log.i(TAG, "TCP server started on port $port")
            while (isActive) {
                try {
                    val client = serverSocket?.accept() ?: return@withContext
                    launch {
                        handleSession(client)
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Accept error", e)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Server start failed", e)
        } finally {
            serverSocket?.close()
        }
    }

    suspend fun stop() = withContext(Dispatchers.IO) {
        serverSocket?.close()
    }

    private suspend fun handleSession(socket: Socket) = withContext(Dispatchers.IO) {
        try {
            val reader = BufferedReader(InputStreamReader(socket.getInputStream()))
            val writer = PrintWriter(socket.getOutputStream(), true)

            var line: String?
            while (reader.readLine().also { line = it } != null) {
                val line = line ?: continue
                try {
                    val req = gson.fromJson(line, JsonObject::class.java)
                    val resp = processCommand(req)
                    writer.println(gson.toJson(resp))
                } catch (e: Exception) {
                    Log.e(TAG, "Command processing error", e)
                    writer.println(gson.toJson(mapOf("error" to e.message)))
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Session error", e)
        } finally {
            socket.close()
        }
    }

    private suspend fun processCommand(req: JsonObject): Any {
        val cmd = req.get("cmd")?.asString ?: return mapOf("error" to "missing cmd")
        val id = req.get("id")?.asInt ?: 0

        return when (cmd) {
            "STATUS" -> {
                val uid = req.get("uid")?.asString ?: return errorResponse(id, "missing uid")
                val store = stores[uid] ?: return errorResponse(id, "unknown unit")
                val status = store.get()
                val icoolStatus = icoolManager.status(uid)
                okResponse(id, status.toMap() + icoolStatus)
            }

            "SET_ICOOL" -> {
                val uid = req.get("uid")?.asString ?: return errorResponse(id, "missing uid")
                val on = req.get("on")?.asBoolean ?: false
                val target = req.get("target")?.asFloat
                val config = req.getAsJsonObject("config")?.let {
                    it.entrySet().associate { (k, v) -> k to v }
                }

                if (on) {
                    icoolManager.start(uid, target, config?.mapValues { (_, v) -> v.asString })
                } else {
                    icoolManager.stop(uid)
                }
                okResponse(id, icoolManager.status(uid))
            }

            "SET_ICOOL_DURATION" -> {
                val uid = req.get("uid")?.asString ?: return errorResponse(id, "missing uid")
                val duration = req.get("duration")?.asInt ?: 0
                icoolManager.setDuration(uid, duration)
                okResponse(id, icoolManager.status(uid))
            }

            "SUBSCRIBE" -> {
                // Stream subscription (not implemented in this basic version)
                mapOf("t" to "snapshot", "units" to emptyMap<String, Any>(), "outdoor" to emptyMap<String, Any>())
            }

            else -> errorResponse(id, "unknown command: $cmd")
        }
    }

    private fun okResponse(id: Int, data: Any) = mapOf("id" to id, "status" to "ok", "data" to data)
    private fun errorResponse(id: Int, error: String) = mapOf("id" to id, "status" to "error", "error" to error)

    companion object {
        private const val TAG = "TcpServer"
    }
}
