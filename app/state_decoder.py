"""파싱된 RS485 코드/값 → AcStatus 필드 변환."""
from __future__ import annotations

_MODE_MAP = {0: "auto", 1: "cool", 2: "dry", 3: "fanOnly"}
_FAN_MAP  = {0: "auto", 1: "low",  2: "medium", 3: "high"}

# 실외기 운전 모드 (0x8001) — samsung_ac NASA 레퍼런스 기준 주요 값
_ODU_MODE_MAP = {
    0: "STOP", 1: "SAFETY", 2: "NORMAL", 3: "BALANCE",
    4: "RECOVERY", 5: "DEICE", 6: "COMPDOWN", 7: "PROHIBIT",
}
# 냉/난방 방향 (0x8003)
_HEAT_COOL_MAP = {0: "Undef", 1: "Cool", 2: "Heat", 3: "CoolMain", 4: "HeatMain"}


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


def decode_outdoor_codes(codes: list[tuple[int, bytes]]) -> dict:
    """실외기(10:00:00) C014 코드-값 → OutdoorStore.update() kwargs dict.

    값 스케일은 samsung_ac NASA 레퍼런스 및 위키(samsung_nasa_protocol) 기준.
    전력/에너지 코드(0x84xx)는 전력 미터 탑재 실외기 모델에서만 수신된다.
    """
    updates: dict = {}
    for code, value in codes:
        if code == 0x8204:
            # 외기 온도: signed int16 / 10 ℃
            updates["outdoor_temp"] = int.from_bytes(value, "big", signed=True) / 10
        elif code == 0x8413:
            # 순시 전력: 전 모듈 합, W (약 30초 주기)
            updates["power_w"] = int.from_bytes(value, "big")
        elif code == 0x8414:
            # 누적 전력량: 전 모듈 합, Wh (kWh 환산 시 /1000)
            updates["cumulative_energy_wh"] = int.from_bytes(value, "big")
        elif code == 0x8217:
            # 실외기 전류(CT1): 위키 기준 /10 → A
            updates["current_a"] = int.from_bytes(value, "big") / 10
        elif code == 0x24FC:
            # 전압: 스케일 미확정, 실측 데이터로 검증 필요 (raw V 가정)
            updates["voltage_v"] = int.from_bytes(value, "big")
        elif code == 0x8001:
            updates["odu_mode"] = _ODU_MODE_MAP.get(value[0], f"UNKNOWN({value[0]})")
        elif code == 0x8003:
            updates["heat_cool"] = _HEAT_COOL_MAP.get(value[0], "Undef")
    return updates
