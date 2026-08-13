package com.samsung.ac.bridge.protocol

object PacketProtocol {
    const val START_BYTE = 0x32
    const val END_BYTE = 0x34
    const val HEADER_LEN = 3   // 0x32 + LEN_H + LEN_L
    const val FOOTER_LEN = 3   // CRC_H + CRC_L + 0x34
    const val MIN_PAYLOAD = 10 // SRC(3) + DST(3) + TYPE(2) + SEQ(1) + COUNT(1)
    const val MAX_PAYLOAD = 512

    const val MSG_TYPE_STATUS = 0xC014
    const val MSG_TYPE_ACK = 0xC016

    // NASA 주소는 3바이트 class.channel.address 구조다.
    // channel/address 0xFF는 "미지정(와일드카드)"이며 20.ff.ff 는 물리 장치가 아니라
    // "모든 실내기" 브로드캐스트 주소다.
    const val ADDR_CLASS_OUTDOOR = 0x10
    const val ADDR_CLASS_INDOOR = 0x20
    const val ADDR_WILDCARD_BYTE = 0xFF

    /** 실재하는 개별 장치의 주소인지 (와일드카드/브로드캐스트 배제). klass를 주면 클래스도 검사. */
    fun isPhysicalAddress(addr: ByteArray, klass: Int? = null): Boolean {
        if (addr.size != 3) return false
        val b = addr.map { it.toInt() and 0xFF }
        if (klass != null && b[0] != klass) return false
        return b.none { it == ADDR_WILDCARD_BYTE }
    }

    // Mode/Fan code mappings
    val MODE_CODES = mapOf("auto" to 0, "cool" to 1, "dry" to 2, "fanOnly" to 3)
    val MODE_BY_CODE = MODE_CODES.entries.associate { it.value to it.key }
    val FAN_CODES = mapOf("auto" to 0, "low" to 1, "medium" to 2, "high" to 3)
    val FAN_BY_CODE = FAN_CODES.entries.associate { it.value to it.key }
    val VALID_MODES = MODE_CODES.keys
    val VALID_FAN_MODES = FAN_CODES.keys

    const val TEMP_MIN = 18.0f
    const val TEMP_MAX = 30.0f

    // Outdoor mode mappings
    private val ODU_MODE_MAP = mapOf(
        0 to "STOP", 1 to "SAFETY", 2 to "NORMAL", 3 to "BALANCE",
        4 to "RECOVERY", 5 to "DEICE", 6 to "COMPDOWN", 7 to "PROHIBIT"
    )
    private val HEAT_COOL_MAP = mapOf(
        0 to "Undef", 1 to "Cool", 2 to "Heat", 3 to "CoolMain", 4 to "HeatMain"
    )

    fun oduModeString(code: Int) = ODU_MODE_MAP[code] ?: "UNKNOWN($code)"
    fun heatCoolString(code: Int) = HEAT_COOL_MAP[code] ?: "Undef"
}

data class ParsedPacket(
    val src: ByteArray,
    val dst: ByteArray,
    val msgType: Int,
    val seq: Int,
    val codes: List<Pair<Int, ByteArray>>,
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is ParsedPacket) return false
        if (!src.contentEquals(other.src)) return false
        if (!dst.contentEquals(other.dst)) return false
        if (msgType != other.msgType) return false
        if (seq != other.seq) return false
        if (codes != other.codes) return false
        return true
    }

    override fun hashCode(): Int {
        var result = src.contentHashCode()
        result = 31 * result + dst.contentHashCode()
        result = 31 * result + msgType
        result = 31 * result + seq
        result = 31 * result + codes.hashCode()
        return result
    }
}

object CRC16 {
    fun xmodem(data: ByteArray): Int {
        var crc = 0x0000
        for (byte in data) {
            crc = crc xor ((byte.toInt() and 0xFF) shl 8)
            for (i in 0 until 8) {
                crc = if ((crc and 0x8000) != 0) {
                    ((crc shl 1) xor 0x1021) and 0xFFFF
                } else {
                    (crc shl 1) and 0xFFFF
                }
            }
        }
        return crc
    }
}

object PacketParser {
    fun extractPackets(buf: ByteArray): Pair<List<ParsedPacket>, ByteArray> {
        val packets = mutableListOf<ParsedPacket>()
        var i = 0

        while (i < buf.size) {
            if (buf[i].toInt() and 0xFF != PacketProtocol.START_BYTE) {
                i++
                continue
            }

            if (i + 3 > buf.size) break

            val size = ((buf[i + 1].toInt() and 0xFF) shl 8) or (buf[i + 2].toInt() and 0xFF)
            val pktLen = size + 2 // SIZE = total_len - 2

            if (pktLen > PacketProtocol.MAX_PAYLOAD + 6 || pktLen < 14) {
                i++
                continue
            }

            if (i + pktLen > buf.size) break

            val raw = buf.sliceArray(i until i + pktLen)
            if ((raw.last().toInt() and 0xFF) != PacketProtocol.END_BYTE) {
                i++
                continue
            }

            val pkt = tryParse(raw)
            if (pkt != null) {
                packets.add(pkt)
            }
            i += pktLen
        }

        return packets to buf.sliceArray(i until buf.size)
    }

    private fun tryParse(raw: ByteArray): ParsedPacket? {
        if ((raw.last().toInt() and 0xFF) != PacketProtocol.END_BYTE) return null

        val payload = raw.sliceArray(3 until raw.size - 3)
        if (payload.size < PacketProtocol.MIN_PAYLOAD) return null

        val crcCalc = CRC16.xmodem(payload)
        val crcRecv = ((raw[raw.size - 3].toInt() and 0xFF) shl 8) or (raw[raw.size - 2].toInt() and 0xFF)
        if (crcCalc != crcRecv) return null

        val src = payload.sliceArray(0 until 3)
        val dst = payload.sliceArray(3 until 6)
        val msgType = ((payload[6].toInt() and 0xFF) shl 8) or (payload[7].toInt() and 0xFF)
        val seq = payload[8].toInt() and 0xFF
        val codes = parseCodes(payload.sliceArray(9 until payload.size))

        return ParsedPacket(
            src = src,
            dst = dst,
            msgType = msgType,
            seq = seq,
            codes = codes
        )
    }

    private fun parseCodes(data: ByteArray): List<Pair<Int, ByteArray>> {
        if (data.isEmpty()) return emptyList()

        val count = data[0].toInt() and 0xFF
        val codes = mutableListOf<Pair<Int, ByteArray>>()
        var i = 1

        for (idx in 0 until count) {
            if (i + 2 > data.size) break

            val code = ((data[i].toInt() and 0xFF) shl 8) or (data[i + 1].toInt() and 0xFF)
            val size = valueSize(data[i])

            if (i + 2 + size > data.size) break

            val value = data.sliceArray(i + 2 until i + 2 + size)
            codes.add(code to value)
            i += 2 + size
        }

        return codes
    }

    private fun valueSize(codeHigh: Byte): Int {
        val nibble = codeHigh.toInt() and 0x0F
        return when (nibble) {
            0x0, 0x1 -> 1
            0x2 -> 2
            0x4 -> 4
            0x6 -> 10
            else -> 2
        }
    }
}

object StateDecoder {
    fun decodeCodes(codes: List<Pair<Int, ByteArray>>): Map<String, Any?> {
        val updates = mutableMapOf<String, Any?>()

        for ((code, value) in codes) {
            when (code) {
                0x4000 -> updates["power"] = value[0].toInt() == 0x01
                0x4001 -> updates["mode"] = PacketProtocol.MODE_BY_CODE[value[0].toInt()] ?: "cool"
                0x4006 -> updates["fan_mode"] = PacketProtocol.FAN_BY_CODE[value[0].toInt()] ?: "auto"
                0x4011 -> updates["vane_vertical"] = value[0].toInt() == 0x01
                0x407E -> updates["vane_horizontal"] = value[0].toInt() == 0x01
                0x4007 -> updates["long_wind"] = value[0].toInt() == 0x10
                0x4060 -> updates["wind_free"] = value[0].toInt() == 0x09
                0x4038 -> updates["humidity"] = value[0].toInt() and 0xFF
                0x4111 -> updates["auto_clean"] = value[0].toInt() == 0x01
                0x4201 -> updates["target_temp"] = bytesToInt(value) / 10.0f
                0x4203 -> {
                    val temp = bytesToInt(value) / 10.0f
                    if (temp > 0) updates["current_temp"] = temp
                }
            }
        }

        return updates
    }

    fun decodeOutdoorCodes(codes: List<Pair<Int, ByteArray>>): Map<String, Any?> {
        val updates = mutableMapOf<String, Any?>()

        for ((code, value) in codes) {
            when (code) {
                0x8204 -> updates["outdoor_temp"] = bytesToSignedInt(value) / 10.0f
                0x8413 -> updates["power_w"] = bytesToInt(value)
                0x8414 -> updates["cumulative_energy_wh"] = bytesToInt(value)
                0x8217 -> updates["current_a"] = bytesToInt(value) / 10.0f
                0x24FC -> updates["voltage_v"] = bytesToInt(value)
                0x8001 -> updates["odu_mode"] = PacketProtocol.oduModeString(value[0].toInt())
                0x8003 -> updates["heat_cool"] = PacketProtocol.heatCoolString(value[0].toInt())
            }
        }

        return updates
    }

    private fun bytesToInt(bytes: ByteArray): Int {
        var value = 0
        for (b in bytes) {
            value = (value shl 8) or (b.toInt() and 0xFF)
        }
        return value
    }

    private fun bytesToSignedInt(bytes: ByteArray): Int {
        var value = bytesToInt(bytes)
        if (bytes.isNotEmpty() && (bytes[0].toInt() and 0x80) != 0) {
            value = value or (0xFFFF shl 16)
        }
        return value
    }
}
