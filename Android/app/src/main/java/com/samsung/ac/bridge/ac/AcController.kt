package com.samsung.ac.bridge.ac

import android.util.Log
import com.samsung.ac.bridge.ew11.EW11Client
import com.samsung.ac.bridge.protocol.AcStatus
import com.samsung.ac.bridge.protocol.PacketBuilder
import com.samsung.ac.bridge.state.StateStore

abstract class AcController(
    protected val uid: String,
    protected val store: StateStore,
) {
    abstract suspend fun getStatus(): AcStatus
    abstract suspend fun setPower(on: Boolean): Boolean
    abstract suspend fun setMode(mode: String): Boolean
    abstract suspend fun setTargetTemp(temp: Float): Boolean
    abstract suspend fun setFanMode(fan: String): Boolean
    abstract suspend fun setVane(vertical: Boolean, horizontal: Boolean): Boolean
    abstract suspend fun setWindFree(on: Boolean): Boolean
    abstract suspend fun setLongWind(on: Boolean): Boolean
    abstract suspend fun setAutoClean(on: Boolean): Boolean
    abstract suspend fun applySettings(settings: Map<String, Any?>): Boolean

    companion object {
        private const val TAG = "AcController"
    }
}

class RealAcController(
    uid: String,
    val address: ByteArray,
    store: StateStore,
    private val ew11: EW11Client,
) : AcController(uid, store) {

    override suspend fun getStatus(): AcStatus = store.get()

    override suspend fun setPower(on: Boolean): Boolean {
        val packet = PacketBuilder.buildSetPower(address, on)
        return if (packet.isNotEmpty()) {
            ew11.send(packet)
            true
        } else false
    }

    override suspend fun setMode(mode: String): Boolean {
        val packet = PacketBuilder.buildSetMode(address, mode)
        return if (packet.isNotEmpty()) {
            ew11.send(packet)
            true
        } else false
    }

    override suspend fun setTargetTemp(temp: Float): Boolean {
        val packet = PacketBuilder.buildSetTargetTemp(address, temp)
        return if (packet.isNotEmpty()) {
            ew11.send(packet)
            true
        } else false
    }

    override suspend fun setFanMode(fan: String): Boolean {
        val packet = PacketBuilder.buildSetFanMode(address, fan)
        return if (packet.isNotEmpty()) {
            ew11.send(packet)
            true
        } else false
    }

    override suspend fun setVane(vertical: Boolean, horizontal: Boolean): Boolean {
        val packet = PacketBuilder.buildSetVane(address, vertical, horizontal)
        return if (packet.isNotEmpty()) {
            ew11.send(packet)
            true
        } else false
    }

    override suspend fun setWindFree(on: Boolean): Boolean {
        val packet = PacketBuilder.buildSetWindFree(address, on)
        return if (packet.isNotEmpty()) {
            ew11.send(packet)
            true
        } else false
    }

    override suspend fun setLongWind(on: Boolean): Boolean {
        val packet = PacketBuilder.buildSetLongWind(address, on)
        return if (packet.isNotEmpty()) {
            ew11.send(packet)
            true
        } else false
    }

    override suspend fun setAutoClean(on: Boolean): Boolean {
        val packet = PacketBuilder.buildSetAutoClean(address, on)
        return if (packet.isNotEmpty()) {
            ew11.send(packet)
            true
        } else false
    }

    override suspend fun applySettings(settings: Map<String, Any?>): Boolean {
        val packet = PacketBuilder.buildApplySettings(address, settings)
        return if (packet.isNotEmpty()) {
            ew11.send(packet)
            true
        } else false
    }
}

class MockAcController(
    uid: String,
    store: StateStore,
) : AcController(uid, store) {

    override suspend fun getStatus(): AcStatus = store.get()

    override suspend fun setPower(on: Boolean): Boolean {
        store.update(mapOf("power" to on))
        Log.i(TAG, "$uid mock: power=$on")
        return true
    }

    override suspend fun setMode(mode: String): Boolean {
        store.update(mapOf("mode" to mode))
        Log.i(TAG, "$uid mock: mode=$mode")
        return true
    }

    override suspend fun setTargetTemp(temp: Float): Boolean {
        store.update(mapOf("target_temp" to temp))
        Log.i(TAG, "$uid mock: target_temp=$temp")
        return true
    }

    override suspend fun setFanMode(fan: String): Boolean {
        store.update(mapOf("fan_mode" to fan))
        Log.i(TAG, "$uid mock: fan_mode=$fan")
        return true
    }

    override suspend fun setVane(vertical: Boolean, horizontal: Boolean): Boolean {
        store.update(mapOf("vane_vertical" to vertical, "vane_horizontal" to horizontal))
        Log.i(TAG, "$uid mock: vane vertical=$vertical horizontal=$horizontal")
        return true
    }

    override suspend fun setWindFree(on: Boolean): Boolean {
        store.update(mapOf("wind_free" to on))
        Log.i(TAG, "$uid mock: wind_free=$on")
        return true
    }

    override suspend fun setLongWind(on: Boolean): Boolean {
        store.update(mapOf("long_wind" to on))
        Log.i(TAG, "$uid mock: long_wind=$on")
        return true
    }

    override suspend fun setAutoClean(on: Boolean): Boolean {
        store.update(mapOf("auto_clean" to on))
        Log.i(TAG, "$uid mock: auto_clean=$on")
        return true
    }

    override suspend fun applySettings(settings: Map<String, Any?>): Boolean {
        store.update(settings)
        Log.i(TAG, "$uid mock: apply_settings $settings")
        return true
    }

    companion object {
        private const val TAG = "MockAcController"
    }
}
