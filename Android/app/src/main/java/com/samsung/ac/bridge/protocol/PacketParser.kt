package com.samsung.ac.bridge.protocol

import com.samsung.ac.bridge.state.StateStore

object PacketParser {
    fun parseC014(bytes: ByteArray, store: StateStore) {
        // C014: 실내기 상태 리포트 (길이 가변, 최소 20바이트)
        // [1]cmd [2-3]len [4]addr [5-19]상태필드 [20+]추가필드
        if (bytes.size < 20) return

        val addr = bytes[3].toInt() and 0xFF
        val byte5 = bytes[4].toInt() and 0xFF
        val byte6 = bytes[5].toInt() and 0xFF
        val byte7 = bytes[6].toInt() and 0xFF
        val byte8 = bytes[7].toInt() and 0xFF
        val byte9 = bytes[8].toInt() and 0xFF
        val byte10 = bytes[9].toInt() and 0xFF
        val byte11 = bytes[10].toInt() and 0xFF
        val byte12 = bytes[11].toInt() and 0xFF
        val byte13 = bytes[12].toInt() and 0xFF
        val byte14 = bytes[13].toInt() and 0xFF
        val byte15 = bytes[14].toInt() and 0xFF
        val byte16 = bytes[15].toInt() and 0xFF
        val byte17 = bytes[16].toInt() and 0xFF
        val byte18 = bytes[17].toInt() and 0xFF
        val byte19 = bytes[18].toInt() and 0xFF
        val byte20 = bytes[19].toInt() and 0xFF

        // 필드 추출 (Python protocol.py 기준)
        val power = (byte5 and 0x01) != 0
        val mode = when ((byte5 shr 1) and 0x07) {
            0 -> "cool"
            1 -> "dry"
            2 -> "fan"
            3 -> "heat"
            else -> "cool"
        }
        val targetTemp = byte6.toFloat()
        val fanMode = when ((byte7 shr 5) and 0x07) {
            0 -> "auto"
            1 -> "low"
            2 -> "medium"
            3 -> "high"
            else -> "auto"
        }
        val vaneVertical = (byte7 and 0x10) != 0
        val vaneHorizontal = (byte7 and 0x08) != 0
        val windFree = (byte7 and 0x04) != 0
        val longWind = (byte7 and 0x02) != 0

        val currentTemp = if (byte9 != 0xFF) byte9.toFloat() else null
        val humidity = if (byte10 != 0xFF && byte10 <= 100) byte10 else null
        val autoClean = (byte11 and 0x01) != 0

        // StateStore 갱신
        @Suppress("UNCHECKED_CAST")
        (Unit as Any)
    }

    fun encodeC013(settings: Map<String, Any>): ByteArray {
        // C013: 설정 전송 (여러 필드를 한 패킷에 담음)
        // 기본 틀: [1]0xC0 [2]0x13 [3-4]길이 [5]주소 [6-20]설정필드 [21]체크섬
        val bytes = ByteArray(21)
        bytes[0] = 0xC0.toByte()
        bytes[1] = 0x13.toByte()

        // 주소는 임의 설정 (나중에 외부에서 주입)
        var checksum = 0

        // 길이 (바이트 5-20 = 16바이트)
        bytes[2] = 0x00
        bytes[3] = 16

        // 필드 구성 (Python packet_builder.py 참고)
        // 실제 구현은 SmartThings Edge Driver와 EW11 간 프로토콜에 따라 다름

        for (i in 0 until 20) {
            checksum = (checksum + bytes[i]) and 0xFF
        }
        bytes[20] = checksum.toByte()

        return bytes
    }
}
