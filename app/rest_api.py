"""REST API 라우팅 — HTTP 메서드/경로 → CommandService 호출.

전송(소켓/HTTP 파싱)은 http_server.py가 담당하고 여기서는 순수하게
(method, path, body) → (status, payload)만 만든다. 덕분에 소켓 없이 테스트된다.

응답 봉투: {"ok":true,"data":{...}} / {"ok":false,"error":"..."} 에 HTTP 상태코드
(400 잘못된 파라미터 / 404 없는 유닛·경로 / 503 비활성 기능 / 500 서버 오류).

라우트 (prefix /api/v1):
    GET  /health                        서버 생존 + 등록 유닛 수
    GET  /units                         유닛 목록 [{id,label}]
    GET  /units/{uid}                   유닛 상태
    GET  /outdoor                       실외기(시스템) 상태
    GET  /events                        SSE 이벤트 스트림 (http_server가 직접 처리)
    POST /units/{uid}/power             {on}
    POST /units/{uid}/mode              {mode}
    POST /units/{uid}/temperature       {temp}
    POST /units/{uid}/fan               {fan}
    POST /units/{uid}/vane              {vertical,horizontal}
    POST /units/{uid}/wind-free         {on}
    POST /units/{uid}/long-wind         {on}
    POST /units/{uid}/auto-clean        {on}
    POST /units/{uid}/smart-dry         {on,ratio,max_min,min_min}
    POST /units/{uid}/icool             {on,target,config}
    POST /units/{uid}/icool/duration    {duration}
    POST /units/{uid}/icool/config      {config}
"""
from __future__ import annotations

import logging

from commands import CommandError, CommandService, UnavailableError, UnknownUnitError

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"
EVENTS_PATH = f"{API_PREFIX}/events"

# 유닛 하위 액션 → (서비스 메서드명, body에서 뽑을 인자 이름들)
# 인자 이름은 CommandService 시그니처의 키워드와 1:1이다.
_UNIT_ACTIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "power":       ("set_power",        ("on",)),
    "mode":        ("set_mode",         ("mode",)),
    "temperature": ("set_target_temp",  ("temp",)),
    "fan":         ("set_fan_mode",     ("fan",)),
    "vane":        ("set_vane",         ("vertical", "horizontal")),
    "wind-free":   ("set_wind_free",    ("on",)),
    "long-wind":   ("set_long_wind",    ("on",)),
    "auto-clean":  ("set_auto_clean",   ("on",)),
    "smart-dry":   ("set_smart_dry",    ("on", "ratio", "max_min", "min_min")),
    "icool":       ("set_icool",        ("on", "target", "config")),
}
_ICOOL_ACTIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "duration": ("set_icool_duration", ("duration",)),
    "config":   ("set_icool_config",   ("config",)),
}


def ok(data=None) -> dict:
    payload: dict = {"ok": True}
    if data is not None:
        payload["data"] = data
    return payload


def err(message: str) -> dict:
    return {"ok": False, "error": message}


class Router:
    def __init__(self, service: CommandService) -> None:
        self._svc = service

    async def dispatch(self, method: str, path: str, body: dict) -> tuple[int, dict]:
        """(HTTP status, 응답 payload) 반환. 예외를 밖으로 던지지 않는다."""
        if not path.startswith(API_PREFIX):
            return 404, err(f"no such route: {path}")
        rest = path[len(API_PREFIX):].strip("/")
        parts = [p for p in rest.split("/") if p]

        try:
            return await self._route(method, parts, body)
        except UnknownUnitError as e:
            return 404, err(str(e))
        except UnavailableError as e:
            return 503, err(str(e))
        except CommandError as e:
            return 400, err(str(e))
        except Exception:
            logger.exception("REST handler error: %s %s", method, path)
            return 500, err("internal error")

    async def _route(self, method: str, parts: list[str], body: dict) -> tuple[int, dict]:
        if parts == ["health"]:
            if method != "GET":
                return 405, err("method not allowed")
            return 200, ok({"status": "ok", "units": len(self._svc.list_units()["units"])})

        if parts == ["outdoor"]:
            if method != "GET":
                return 405, err("method not allowed")
            return 200, ok(await self._svc.outdoor_status())

        if parts == ["units"]:
            if method != "GET":
                return 405, err("method not allowed")
            return 200, ok(self._svc.list_units())

        if len(parts) >= 2 and parts[0] == "units":
            return await self._unit_route(method, parts[1], parts[2:], body)

        return 404, err("no such route: /" + "/".join(parts))

    async def _unit_route(
        self, method: str, uid: str, tail: list[str], body: dict,
    ) -> tuple[int, dict]:
        if not tail:
            if method != "GET":
                return 405, err("method not allowed")
            return 200, ok(await self._svc.unit_status(uid))

        if tail == ["icool"] or (len(tail) == 2 and tail[0] == "icool"):
            spec = (_UNIT_ACTIONS["icool"] if tail == ["icool"]
                    else _ICOOL_ACTIONS.get(tail[1]))
        else:
            spec = _UNIT_ACTIONS.get(tail[0]) if len(tail) == 1 else None

        if spec is None:
            return 404, err("no such unit action: /" + "/".join(tail))
        if method != "POST":
            return 405, err("method not allowed")

        name, arg_names = spec
        kwargs = {a: body.get(a) for a in arg_names}
        data = await getattr(self._svc, name)(uid, **kwargs)
        return 200, ok(data)
