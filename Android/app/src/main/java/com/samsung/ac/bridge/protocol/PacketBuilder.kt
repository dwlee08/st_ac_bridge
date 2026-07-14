package com.samsung.ac.bridge.protocol

object PacketBuilder {
    private const val START_BYTE = 0x32
    private const val END_BYTE = 0x34
    private val SRC = byteArrayOf(0x62.toByte(), 0x00.toByte(), 0x00.toByte())
    private val MSG_TYPE = byteArrayOf(0xC0.toByte(), 0x13.toByte())

    private var seq: Int = 0

    private fun nextSeq(): Int {
        val val0 = seq
        seq = (seq + 1) and 0xFF
        return val0
    }

    private fun build(dst: ByteArray, items: List<Pair<Int, ByteArray>>): ByteArray {
        val seq = nextSeq()
        val count = items.size
        val data = items.flatMap { (code, value) ->
            code.toBytes2Big() + value.toList()
        }.toByteArray()

        val inner = SRC + dst + MSG_TYPE + byteArrayOf(seq.toByte(), count.toByte()) + data
        val crc = CRC16.xmodem(inner)
        val size = inner.size + 4

        return byteArrayOf(START_BYTE.toByte()) +
                size.toBytes2Big() +
                inner +
                crc.toBytes2Big() +
                byteArrayOf(END_BYTE.toByte())
    }

    fun buildFields(dst: ByteArray, fields: Map<String, Any?>): ByteArray {
        val items = fieldsToItems(fields)
        return if (items.isEmpty()) byteArrayOf() else build(dst, items)
    }

    fun buildSetPower(dst: ByteArray, on: Boolean, targetTemp: Float? = null): ByteArray {
        val fields = mutableMapOf<String, Any?>("power" to on)
        if (on && targetTemp != null) {
            fields["target_temp"] = targetTemp
        }
        return buildFields(dst, fields)
    }

    fun buildSetMode(dst: ByteArray, mode: String): ByteArray {
        return buildFields(dst, mapOf("mode" to mode))
    }

    fun buildSetTargetTemp(dst: ByteArray, temp: Float, power: Boolean = true): ByteArray {
        return buildFields(dst, mapOf("power" to power, "target_temp" to temp))
    }

    fun buildSetFanMode(dst: ByteArray, fan: String): ByteArray {
        return buildFields(dst, mapOf("fan_mode" to fan))
    }

    fun buildSetVane(dst: ByteArray, vertical: Boolean, horizontal: Boolean): ByteArray {
        val normalized = normalizeAirflow(mapOf("vane_vertical" to vertical, "vane_horizontal" to horizontal))
        return buildFields(dst, normalized)
    }

    fun buildSetWindFree(dst: ByteArray, on: Boolean): ByteArray {
        val normalized = normalizeAirflow(mapOf("wind_free" to on))
        return buildFields(dst, normalized)
    }

    fun buildSetLongWind(dst: ByteArray, on: Boolean): ByteArray {
        val normalized = normalizeAirflow(mapOf("long_wind" to on))
        return buildFields(dst, normalized)
    }

    fun buildSetAutoClean(dst: ByteArray, on: Boolean): ByteArray {
        return buildFields(dst, mapOf("auto_clean" to on))
    }

    fun buildApplySettings(dst: ByteArray, settings: Map<String, Any?>): ByteArray {
        val normalized = normalizeAirflow(settings)
        return buildFields(dst, normalized)
    }

    private fun normalizeAirflow(fields: Map<String, Any?>): Map<String, Any?> {
        val out = fields.toMutableMap()
        when {
            out["wind_free"] == true -> {
                out["long_wind"] = false
                out["vane_vertical"] = false
                out["vane_horizontal"] = false
            }

            out["long_wind"] == true -> {
                out["wind_free"] = false
                out["vane_vertical"] = false
                out["vane_horizontal"] = false
            }

            out["vane_vertical"] == true || out["vane_horizontal"] == true -> {
                out["wind_free"] = false
                out["long_wind"] = false
            }
        }
        return out
    }

    private fun fieldsToItems(fields: Map<String, Any?>): List<Pair<Int, ByteArray>> {
        val items = mutableListOf<Pair<Int, ByteArray>>()

        fields["power"]?.let { v ->
            val byte = if (v as Boolean) 0x01 else 0x00
            items.add(0x4000 to byteArrayOf(byte.toByte()))
        }

        fields["mode"]?.let { v ->
            val code = PacketProtocol.MODE_CODES[v as String] ?: 1
            items.add(0x4001 to byteArrayOf(code.toByte()))
        }

        fields["target_temp"]?.let { v ->
            val temp = ((v as Number).toFloat() * 10).toInt()
            items.add(0x4201 to temp.toBytes2Big())
        }

        fields["fan_mode"]?.let { v ->
            val code = PacketProtocol.FAN_CODES[v as String] ?: 0
            items.add(0x4006 to byteArrayOf(code.toByte()))
        }

        fields["vane_vertical"]?.let { v ->
            val byte = if (v as Boolean) 0x01 else 0x00
            items.add(0x4011 to byteArrayOf(byte.toByte()))
        }

        fields["vane_horizontal"]?.let { v ->
            val byte = if (v as Boolean) 0x01 else 0x00
            items.add(0x407E to byteArrayOf(byte.toByte()))
        }

        fields["wind_free"]?.let { v ->
            val byte = if (v as Boolean) 0x09 else 0x00
            items.add(0x4060 to byteArrayOf(byte.toByte()))
        }

        fields["long_wind"]?.let { v ->
            val byte = if (v as Boolean) 0x10 else 0x0E
            items.add(0x4007 to byteArrayOf(byte.toByte()))
        }

        fields["auto_clean"]?.let { v ->
            val byte = if (v as Boolean) 0x01 else 0x00
            items.add(0x4111 to byteArrayOf(byte.toByte()))
        }

        return items
    }
}

private fun Int.toBytes2Big(): ByteArray {
    return byteArrayOf(
        ((this shr 8) and 0xFF).toByte(),
        (this and 0xFF).toByte()
    )
}
