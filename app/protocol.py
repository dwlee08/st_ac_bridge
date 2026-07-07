"""Edge Driver ↔ AC Bridge Server JSON 메시지 포맷."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


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


@dataclass
class Request:
    id: str
    cmd: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: str) -> Request:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProtocolError(f"JSON parse error: {e}") from e
        if not isinstance(obj, dict):
            raise ProtocolError(f"expected JSON object, got {type(obj).__name__}")
        if "id" not in obj or "cmd" not in obj:
            raise ProtocolError("missing required fields: id, cmd")
        return cls(id=str(obj["id"]), cmd=str(obj["cmd"]), params=obj.get("params") or {})


@dataclass
class Response:
    id: str
    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None

    def serialize(self) -> str:
        obj: dict[str, Any] = {"id": self.id, "ok": self.ok}
        if self.data is not None:
            obj["data"] = self.data
        if self.error is not None:
            obj["error"] = self.error
        return json.dumps(obj, ensure_ascii=False) + "\n"


def ok_response(req_id: str, data: dict[str, Any] | None = None) -> Response:
    return Response(id=req_id, ok=True, data=data)


def err_response(req_id: str, message: str) -> Response:
    return Response(id=req_id, ok=False, error=message)


class ProtocolError(Exception):
    pass
