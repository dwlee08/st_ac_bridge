"""C013 제어 패킷 빌드."""
from __future__ import annotations

from packet_parser import crc16_xmodem

START_BYTE = 0x32
END_BYTE   = 0x34
SRC        = bytes([0x62, 0x00, 0x00])
MSG_TYPE   = bytes([0xC0, 0x13])

_MODE_CODE = {"auto": 0, "cool": 1, "dry": 2, "fanOnly": 3}
_FAN_CODE  = {"auto": 0, "low": 1, "medium": 2, "high": 3}

_seq = 0


def _next_seq() -> int:
    global _seq
    val = _seq
    _seq = (_seq + 1) & 0xFF
    return val


def _build(dst: bytes, items: list[tuple[int, bytes]]) -> bytes:
    """items: [(code_int, value_bytes), ...]"""
    seq   = _next_seq()
    count = len(items)
    data  = b"".join(c.to_bytes(2, "big") + v for c, v in items)
    inner = SRC + dst + MSG_TYPE + bytes([seq, count]) + data
    crc   = crc16_xmodem(inner)
    size  = len(inner) + 4  # SIZE = total_packet_len - 2
    return (bytes([START_BYTE])
            + size.to_bytes(2, "big")
            + inner
            + crc.to_bytes(2, "big")
            + bytes([END_BYTE]))


def build_set_power(dst: bytes, on: bool, target_temp: float | None = None) -> bytes:
    items = [(0x4000, bytes([0x01 if on else 0x00]))]
    if on and target_temp is not None:
        items.append((0x4201, int(target_temp * 10).to_bytes(2, "big")))
    return _build(dst, items)


def build_set_mode(dst: bytes, mode: str) -> bytes:
    return _build(dst, [(0x4001, bytes([_MODE_CODE[mode]]))])


def build_set_target_temp(dst: bytes, temp: float, power: bool = True) -> bytes:
    return _build(dst, [
        (0x4000, bytes([0x01 if power else 0x00])),
        (0x4201, int(temp * 10).to_bytes(2, "big")),
    ])


def build_set_fan_mode(dst: bytes, fan: str) -> bytes:
    return _build(dst, [(0x4006, bytes([_FAN_CODE[fan]]))])


def build_set_vane(dst: bytes, vertical: bool, horizontal: bool) -> bytes:
    items = [
        (0x4011, bytes([0x01 if vertical else 0x00])),
        (0x407E, bytes([0x01 if horizontal else 0x00])),
    ]
    if vertical or horizontal:
        items.append((0x4060, bytes([0x00])))   # wind_free off
        items.append((0x4007, bytes([0x0E])))   # long_wind off
    return _build(dst, items)


def build_set_wind_free(dst: bytes, on: bool) -> bytes:
    items = [(0x4060, bytes([0x09 if on else 0x00]))]
    if on:
        items.append((0x4011, bytes([0x00])))   # vane_vertical off
        items.append((0x407E, bytes([0x00])))   # vane_horizontal off
    return _build(dst, items)


def build_set_long_wind(dst: bytes, on: bool) -> bytes:
    items = [(0x4007, bytes([0x10 if on else 0x0E]))]
    if on:
        items.append((0x4011, bytes([0x00])))   # vane_vertical off
        items.append((0x407E, bytes([0x00])))   # vane_horizontal off
    return _build(dst, items)


def build_reconcile(dst: bytes, diffs: dict) -> bytes:
    """desired와 reported의 차이(diffs)를 C013 한 패킷으로 빌드."""
    items: list[tuple[int, bytes]] = []
    if "power" in diffs:
        items.append((0x4000, bytes([0x01 if diffs["power"] else 0x00])))
    if "mode" in diffs:
        items.append((0x4001, bytes([_MODE_CODE.get(diffs["mode"], 1)])))
    if "target_temp" in diffs:
        items.append((0x4201, int(diffs["target_temp"] * 10).to_bytes(2, "big")))
    if "fan_mode" in diffs:
        items.append((0x4006, bytes([_FAN_CODE.get(diffs["fan_mode"], 0)])))
    if "vane_vertical" in diffs:
        items.append((0x4011, bytes([0x01 if diffs["vane_vertical"] else 0x00])))
    if "vane_horizontal" in diffs:
        items.append((0x407E, bytes([0x01 if diffs["vane_horizontal"] else 0x00])))
    if "wind_free" in diffs:
        items.append((0x4060, bytes([0x09 if diffs["wind_free"] else 0x00])))
    if "long_wind" in diffs:
        items.append((0x4007, bytes([0x10 if diffs["long_wind"] else 0x0E])))
    return _build(dst, items) if items else b""
