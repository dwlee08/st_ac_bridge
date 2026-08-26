"""에어컨 도메인 값/규칙의 단일 진실원 (모드·풍량 enum, 온도 범위, 기류 상호배타).

wire 포맷은 여기 없다 — RS485 는 packet_builder/packet_parser,
Edge 대면 REST 는 rest_api 가 담당한다.
"""
from __future__ import annotations


# 모드/풍량 enum 단일 진실원 — 코드값·역맵·유효집합은 여기서만 정의하고
# packet_builder(인코딩)/state_decoder(디코딩)는 이를 import 한다.
MODE_CODES = {"auto": 0, "cool": 1, "dry": 2, "fanOnly": 3}
FAN_CODES  = {"auto": 0, "low": 1, "medium": 2, "high": 3}
MODE_BY_CODE = {v: k for k, v in MODE_CODES.items()}
FAN_BY_CODE  = {v: k for k, v in FAN_CODES.items()}
VALID_MODES = set(MODE_CODES)
VALID_FAN_MODES = set(FAN_CODES)
TEMP_MIN = 18.0
TEMP_MAX = 30.0


def normalize_airflow(fields: dict) -> dict:
    """기류 연동 필드(vane↔wind_free↔long_wind) 상호배타 규칙의 단일 구현.

    켜지는 기능이 상대 기능을 끄도록 companion off 필드를 채워 반환한다.
    우선순위: wind_free > long_wind > vane (동시에 켜 달라는 조합은 무효이므로
    앞선 기능이 이긴다). 상호배타는 desired 상태와 전송 패킷 양쪽에 동일하게
    적용된다(wire에도 off 코드를 명시 — 펌웨어 암묵 동작에 의존하지 않는다).
    """
    out = dict(fields)
    if out.get("wind_free"):
        out.update(long_wind=False, vane_vertical=False, vane_horizontal=False)
    elif out.get("long_wind"):
        out.update(wind_free=False, vane_vertical=False, vane_horizontal=False)
    elif out.get("vane_vertical") or out.get("vane_horizontal"):
        out.update(wind_free=False, long_wind=False)
    return out
