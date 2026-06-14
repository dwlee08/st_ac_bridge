"""Edge Driver ↔ AC Bridge Server JSON 메시지 포맷."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


VALID_MODES = {"auto", "cool", "dry", "fanOnly"}
VALID_FAN_MODES = {"auto", "low", "medium", "high"}
TEMP_MIN = 18.0
TEMP_MAX = 30.0


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
