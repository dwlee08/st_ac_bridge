package com.samsung.ac.bridge.network

import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.samsung.ac.bridge.ac.AcController
import com.samsung.ac.bridge.afterblow.AfterBlowManager
import com.samsung.ac.bridge.icool.IcoolManager
import com.samsung.ac.bridge.protocol.PacketProtocol
import com.samsung.ac.bridge.state.OutdoorStore
import com.samsung.ac.bridge.state.StateStore
import kotlinx.coroutines.*
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.PrintWriter
import java.net.ServerSocket
import java.net.Socket
import kotlin.math.roundToInt

/**
 * Edge Driver ↔ Bridge 세션. 와이어 포맷은 Python session.py와 동일:
 *   요청  {"id":..,"cmd":..,"params":{..}}
 *   응답  {"id":..,"ok":true/false,"data":{..}} + '\n'
 */
class TcpServer(
    private val port: Int = 8888,
    private val stores: Map<String, StateStore>,
    private val controllers: Map<String, AcController>,
    private val icoolManager: IcoolManager,
    private val afterblowManager: AfterBlowManager,
    private val outdoorStore: OutdoorStore? = null,
    private val unitLabels: Map<String, String> = emptyMap(),
) {
    private val gson = Gson()
    private var serverSocket: ServerSocket? = null

    suspend fun start() = withContext(Dispatchers.IO) {
        try {
            val server = ServerSocket(port)
            serverSocket = server
            Log.i(TAG, "TCP server started on port $port")
            while (isActive) {
                try {
                    val client = server.accept()
                    launch { handleSession(client) }
                } catch (e: Exception) {
                    if (isActive) Log.e(TAG, "Accept error", e)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Server start failed", e)
        } finally {
            serverSocket?.close()
        }
    }

    suspend fun stop() = withContext(Dispatchers.IO) { serverSocket?.close() }

    private suspend fun handleSession(socket: Socket) = withContext(Dispatchers.IO) {
        val peer = socket.remoteSocketAddress?.toString() ?: "?"
        Log.i(TAG, "session started: $peer")
        try {
            val reader = BufferedReader(InputStreamReader(socket.getInputStream(), Charsets.UTF_8))
            val writer = PrintWriter(socket.getOutputStream(), false)
            while (isActive) {
                val line = reader.readLine() ?: break
                val text = line.trim()
                if (text.isEmpty()) continue
                val resp = try {
                    dispatch(text)
                } catch (e: Exception) {
                    Log.e(TAG, "command error", e)
                    err("?", e.message ?: "internal error")
                }
                writer.print(gson.toJson(resp))
                writer.print("\n")
                writer.flush()
            }
        } catch (e: Exception) {
            Log.w(TAG, "session error: $peer", e)
        } finally {
            socket.close()
            Log.i(TAG, "session closed: $peer")
        }
    }

    private suspend fun dispatch(raw: String): Map<String, Any?> {
        val req = try {
            gson.fromJson(raw, JsonObject::class.java)
        } catch (e: Exception) {
            return err("?", "JSON parse error: ${e.message}")
        }
        val id = req.str("id") ?: return err("?", "missing required field: id")
        val cmd = req.str("cmd") ?: return err(id, "missing required field: cmd")
        val p = req.getObj("params")

        when (cmd) {
            "PING" -> return ok(id, mapOf("pong" to true))
            "SUBSCRIBE" -> return err(id, "stream not available")   // StreamHub 미구현 (HANDOFF 참고)
            "LIST_UNITS" -> {
                val units = controllers.keys.map { uid ->
                    mapOf("id" to uid, "label" to (unitLabels[uid] ?: uid))
                }
                return ok(id, mapOf("units" to units))
            }
            "STATUS_OUTDOOR" -> {
                val store = outdoorStore ?: return err(id, "outdoor status not available")
                return ok(id, store.get().toMap())
            }
        }

        // 이하 유닛 대상 명령 — unit_id 필수
        val uid = p.str("unit_id") ?: return err(id, "missing required param: unit_id")
        val ctrl = controllers[uid] ?: return err(id, "unknown unit_id: $uid")

        return when (cmd) {
            "STATUS" -> {
                val data = ctrl.getStatus().toMap().toMutableMap()
                data["unit_id"] = uid
                outdoorStore?.get()?.powerW?.let { data["system_power_w"] = it }
                data.putAll(icoolManager.status(uid))
                data.putAll(afterblowManager.status(uid))     // icool 뒤에 적용해 마스킹 우선
                ok(id, data)
            }

            "SET_POWER" -> {
                val on = p.bool("on") ?: return err(id, "params.on must be boolean")
                if (on) {
                    if (afterblowManager.resume(uid)) return ok(id, afterblowManager.status(uid))
                } else {
                    if (afterblowManager.onPowerOff(uid)) return ok(id, afterblowManager.status(uid))
                }
                ctrl.setPower(on)
                ok(id, null)
            }

            "SET_SMART_DRY" -> {
                val on = p.bool("on") ?: return err(id, "params.on must be boolean")
                afterblowManager.setEnabled(uid, on, p.int("ratio"), p.int("max_min"), p.int("min_min"))
                ok(id, afterblowManager.status(uid))
            }

            "SET_MODE" -> {
                val mode = p.str("mode")
                if (mode == null || mode !in PacketProtocol.VALID_MODES) return err(id, "invalid mode: $mode")
                if (mode == "fanOnly" && ctrl.getStatus().fanMode == "auto") {
                    // 송풍 모드는 풍량 auto 미지원 → low로 보정, 한 패킷 적용
                    ctrl.applySettings(mapOf("mode" to "fanOnly", "fan_mode" to "low"))
                    return ok(id, mapOf("fan_corrected" to "low"))
                }
                ctrl.setMode(mode)
                ok(id, null)
            }

            "SET_TEMP" -> {
                val temp = p.num("temp") ?: return err(id, "params.temp must be number")
                if (temp < PacketProtocol.TEMP_MIN || temp > PacketProtocol.TEMP_MAX)
                    return err(id, "temp out of range: ${PacketProtocol.TEMP_MIN}~${PacketProtocol.TEMP_MAX}")
                val rounded = (temp * 2).roundToInt() / 2.0f    // 0.5℃ 단위
                ctrl.setTargetTemp(rounded)
                ok(id, null)
            }

            "SET_FAN" -> {
                val fan = p.str("fan")
                if (fan == null || fan !in PacketProtocol.VALID_FAN_MODES) return err(id, "invalid fan mode: $fan")
                if (ctrl.getStatus().mode == "fanOnly" && fan == "auto")
                    return err(id, "fan mode auto is not allowed when mode=fanOnly")
                ctrl.setFanMode(fan)
                ok(id, null)
            }

            "SET_VANE" -> {
                val v = p.bool("vertical")
                val h = p.bool("horizontal")
                if (v == null && h == null) return err(id, "params.vertical or horizontal required")
                // 생략된 축은 현재 상태 유지 → 상하/좌우 독립 제어
                val cur = if (v == null || h == null) ctrl.getStatus() else null
                ctrl.setVane(v ?: cur!!.vaneVertical, h ?: cur!!.vaneHorizontal)
                ok(id, null)
            }

            "SET_WIND_FREE" -> {
                val on = p.bool("on") ?: return err(id, "params.on must be boolean")
                ctrl.setWindFree(on)
                ok(id, null)
            }

            "SET_LONG_WIND" -> {
                val on = p.bool("on") ?: return err(id, "params.on must be boolean")
                ctrl.setLongWind(on)
                ok(id, null)
            }

            "SET_AUTO_CLEAN" -> {
                val on = p.bool("on") ?: return err(id, "params.on must be boolean")
                ctrl.setAutoClean(on)
                ok(id, null)
            }

            "SET_ICOOL" -> {
                val on = p.bool("on") ?: return err(id, "params.on must be boolean")
                if (on) {
                    icoolManager.start(uid, p.num("target")?.toFloat(), p.getObj("config")?.let { jsonToMap(it) })
                } else {
                    icoolManager.stop(uid)
                }
                ok(id, icoolManager.status(uid))
            }

            "SET_ICOOL_DURATION" -> {
                val duration = p.num("duration") ?: return err(id, "params.duration must be number")
                icoolManager.setDuration(uid, duration.toInt())
                ok(id, icoolManager.status(uid))
            }

            "SET_ICOOL_CONFIG" -> {
                val config = p.getObj("config") ?: return err(id, "params.config must be object")
                icoolManager.setConfig(uid, jsonToMap(config))
                ok(id, icoolManager.status(uid))
            }

            else -> err(id, "unknown command: $cmd")
        }
    }

    // ── 응답 봉투 (Python Response.serialize와 동일 키) ──
    private fun ok(id: String, data: Any?): Map<String, Any?> =
        if (data == null) mapOf("id" to id, "ok" to true)
        else mapOf("id" to id, "ok" to true, "data" to data)

    private fun err(id: String, message: String): Map<String, Any?> =
        mapOf("id" to id, "ok" to false, "error" to message)

    // ── JSON 파라미터 추출 (타입 보존: 숫자는 숫자로 남겨 config 캐스팅이 동작하게) ──
    private fun JsonObject?.prim(key: String): JsonElement? =
        this?.get(key)?.takeIf { it.isJsonPrimitive }

    private fun JsonObject?.str(key: String): String? = prim(key)?.asString
    private fun JsonObject?.bool(key: String): Boolean? =
        prim(key)?.takeIf { it.asJsonPrimitive.isBoolean }?.asBoolean
    private fun JsonObject?.num(key: String): Double? =
        prim(key)?.takeIf { it.asJsonPrimitive.isNumber }?.asDouble
    private fun JsonObject?.int(key: String): Int? = num(key)?.toInt()
    private fun JsonObject?.getObj(key: String): JsonObject? =
        this?.get(key)?.takeIf { it.isJsonObject }?.asJsonObject

    private fun jsonToMap(obj: JsonObject): Map<String, Any?> =
        obj.entrySet().associate { (k, v) -> k to jsonToValue(v) }

    private fun jsonToValue(el: JsonElement): Any? = when {
        el.isJsonNull -> null
        el.isJsonPrimitive -> el.asJsonPrimitive.let {
            when {
                it.isBoolean -> it.asBoolean
                it.isNumber -> it.asDouble
                else -> it.asString
            }
        }
        else -> el.toString()
    }

    companion object {
        private const val TAG = "TcpServer"
    }
}
