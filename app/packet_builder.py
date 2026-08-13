"""C013 제어 패킷 빌드.

필드명 → (code, value) 매핑은 `_items_from_fields()` 한 곳에만 존재한다.
개별 build_set_* 는 필드 dict를 구성해 이를 통과시키는 얇은 래퍼이며,
기류 연동 필드의 상호배타 규칙은 protocol.normalize_airflow()가 단일 구현이다.
"""
from __future__ import annotations

from packet_parser import crc16_xmodem, is_physical_address
from protocol import FAN_CODES, MODE_CODES, normalize_airflow

START_BYTE = 0x32
END_BYTE   = 0x34
SRC        = bytes([0x62, 0x00, 0x00])
MSG_TYPE   = bytes([0xC0, 0x13])

_seq = 0


def _next_seq() -> int:
    global _seq
    val = _seq
    _seq = (_seq + 1) & 0xFF
    return val


def _build(dst: bytes, items: list[tuple[int, bytes]]) -> bytes:
    """items: [(code_int, value_bytes), ...]"""
    # 와일드카드 주소(예: 20.ff.ff)로 보내면 모든 실내기에 동시 기록된다.
    # 유령 유닛이 어떤 경로로든 등록됐을 때의 최후 방어선.
    if not is_physical_address(dst):
        raise ValueError(f"refusing to send to non-physical address: {dst.hex()}")
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


# 필드명 → 인코더. 항목 순서가 곧 패킷 내 코드 순서(canonical order)다.
_FIELD_ENCODERS: list[tuple[str, callable]] = [
    ("power",           lambda v: (0x4000, bytes([0x01 if v else 0x00]))),
    ("mode",            lambda v: (0x4001, bytes([MODE_CODES.get(v, 1)]))),
    ("target_temp",     lambda v: (0x4201, int(v * 10).to_bytes(2, "big"))),
    ("fan_mode",        lambda v: (0x4006, bytes([FAN_CODES.get(v, 0)]))),
    ("vane_vertical",   lambda v: (0x4011, bytes([0x01 if v else 0x00]))),
    ("vane_horizontal", lambda v: (0x407E, bytes([0x01 if v else 0x00]))),
    ("wind_free",       lambda v: (0x4060, bytes([0x09 if v else 0x00]))),
    ("long_wind",       lambda v: (0x4007, bytes([0x10 if v else 0x0E]))),
    ("auto_clean",      lambda v: (0x4111, bytes([0x01 if v else 0x00]))),
]


def _items_from_fields(fields: dict) -> list[tuple[int, bytes]]:
    """AcStatus 필드 dict → C013 (code, value) 목록. 매핑의 단일 지점."""
    return [enc(fields[name]) for name, enc in _FIELD_ENCODERS if name in fields]


def build_fields(dst: bytes, fields: dict) -> bytes:
    """필드 dict를 C013 한 패킷으로 빌드. 빈 dict면 b''."""
    items = _items_from_fields(fields)
    return _build(dst, items) if items else b""


def build_set_power(dst: bytes, on: bool, target_temp: float | None = None) -> bytes:
    fields: dict = {"power": on}
    if on and target_temp is not None:
        fields["target_temp"] = target_temp
    return build_fields(dst, fields)


def build_set_mode(dst: bytes, mode: str) -> bytes:
    return build_fields(dst, {"mode": mode})


def build_set_target_temp(dst: bytes, temp: float, power: bool = True) -> bytes:
    return build_fields(dst, {"power": power, "target_temp": temp})


def build_set_fan_mode(dst: bytes, fan: str) -> bytes:
    return build_fields(dst, {"fan_mode": fan})


def build_set_vane(dst: bytes, vertical: bool, horizontal: bool) -> bytes:
    return build_fields(dst, normalize_airflow(
        {"vane_vertical": vertical, "vane_horizontal": horizontal}))


def build_set_wind_free(dst: bytes, on: bool) -> bytes:
    return build_fields(dst, normalize_airflow({"wind_free": on}))


def build_set_long_wind(dst: bytes, on: bool) -> bytes:
    return build_fields(dst, normalize_airflow({"long_wind": on}))


def build_set_auto_clean(dst: bytes, on: bool) -> bytes:
    return build_fields(dst, {"auto_clean": on})


def build_reconcile(dst: bytes, diffs: dict) -> bytes:
    """desired와 reported의 차이(diffs)를 C013 한 패킷으로 빌드."""
    return build_fields(dst, diffs)
