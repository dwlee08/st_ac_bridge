"""파싱된 RS485 코드/값 → AcStatus 필드 변환."""
from __future__ import annotations

_MODE_MAP = {0: "auto", 1: "cool", 2: "dry", 3: "fanOnly"}
_FAN_MAP  = {0: "auto", 1: "low",  2: "medium", 3: "high"}


def decode_codes(codes: list[tuple[int, bytes]]) -> dict:
    """코드-값 목록을 StateStore.update() 에 넘길 kwargs dict로 변환."""
    updates: dict = {}
    for code, value in codes:
        if code == 0x4000:
            updates["power"] = value[0] == 0x01
        elif code == 0x4001:
            updates["mode"] = _MODE_MAP.get(value[0], "cool")
        elif code == 0x4006:
            updates["fan_mode"] = _FAN_MAP.get(value[0], "auto")
        elif code == 0x4011:
            updates["vane_vertical"] = value[0] == 0x01
        elif code == 0x407E:
            updates["vane_horizontal"] = value[0] == 0x01
        elif code == 0x4007:
            updates["long_wind"] = value[0] == 0x10
        elif code == 0x4060:
            updates["wind_free"] = value[0] == 0x09
        elif code == 0x4038:
            updates["humidity"] = value[0]
        elif code == 0x4111:
            updates["auto_clean"] = value[0] == 0x01
        elif code == 0x4201:
            updates["target_temp"] = int.from_bytes(value, "big") / 10
        elif code == 0x4203:
            temp = int.from_bytes(value, "big") / 10
            if temp > 0:
                updates["current_temp"] = temp
    return updates
