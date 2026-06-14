"""C014 상태 패킷 파싱, CRC16-XMODEM 검증, 패킷 경계 분리."""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

START_BYTE = 0x32
END_BYTE   = 0x34
HEADER_LEN = 3   # 0x32 + LEN_H + LEN_L
FOOTER_LEN = 3   # CRC_H + CRC_L + 0x34
MIN_PAYLOAD = 10  # SRC(3) + DST(3) + TYPE(2) + SEQ(1) + COUNT(1)
MAX_PAYLOAD = 512

MSG_TYPE_STATUS = 0xC014
MSG_TYPE_ACK    = 0xC016


@dataclass
class ParsedPacket:
    src: bytes
    dst: bytes
    msg_type: int
    seq: int
    codes: list[tuple[int, bytes]]


def crc16_xmodem(data: bytes) -> int:
    crc = 0x0000
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def _value_size(code_high: int) -> int:
    nibble = code_high & 0x0F
    if nibble in (0x0, 0x1):
        return 1
    if nibble == 0x2:
        return 2
    if nibble == 0x4:
        return 4
    if nibble == 0x6:
        return 10
    return 2  # 스펙 기본값


def _parse_codes(data: bytes) -> list[tuple[int, bytes]]:
    """data[0] = count 바이트, data[1:] = code-value 쌍."""
    if not data:
        return []
    count = data[0]
    codes: list[tuple[int, bytes]] = []
    i = 1
    for _ in range(count):
        if i + 2 > len(data):
            break
        code = (data[i] << 8) | data[i + 1]
        size = _value_size(data[i])
        if i + 2 + size > len(data):
            break
        codes.append((code, bytes(data[i + 2: i + 2 + size])))
        i += 2 + size
    return codes


def _try_parse(raw: bytes) -> ParsedPacket | None:
    if raw[-1] != END_BYTE:
        return None
    payload = raw[3:-3]
    if len(payload) < MIN_PAYLOAD:
        return None
    crc_calc = crc16_xmodem(payload)
    crc_recv = (raw[-3] << 8) | raw[-2]
    if crc_calc != crc_recv:
        logger.info("CRC mismatch: calc=%04X recv=%04X raw=%s", crc_calc, crc_recv, raw.hex())
        return None
    src      = payload[0:3]
    dst      = payload[3:6]
    msg_type = (payload[6] << 8) | payload[7]
    seq      = payload[8]
    codes    = _parse_codes(payload[9:])  # payload[9] = count byte
    return ParsedPacket(src=bytes(src), dst=bytes(dst),
                        msg_type=msg_type, seq=seq, codes=codes)


def extract_packets(buf: bytearray) -> tuple[list[ParsedPacket], bytearray]:
    packets: list[ParsedPacket] = []
    i = 0
    while i < len(buf):
        if buf[i] != START_BYTE:
            i += 1
            continue

        if i + 3 > len(buf):
            break

        size = (buf[i + 1] << 8) | buf[i + 2]
        pkt_len = size + 2  # SIZE = total_len - 2

        if pkt_len > MAX_PAYLOAD + 6 or pkt_len < 14:
            i += 1
            continue

        if i + pkt_len > len(buf):
            break

        raw = bytes(buf[i: i + pkt_len])
        if raw[-1] != END_BYTE:
            i += 1
            continue

        pkt = _try_parse(raw)
        if pkt is None:
            i += 1
            continue

        packets.append(pkt)
        i += pkt_len

    return packets, bytearray(buf[i:])
