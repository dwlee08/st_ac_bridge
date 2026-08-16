"""클라이언트 세션 — JSON 수신/파싱/명령 처리/응답 루프."""
from __future__ import annotations

import asyncio
import logging
from asyncio import StreamReader, StreamWriter

from ac_controller import AcController
from commands import CommandError, CommandService
from icool import IcoolManager
from state_store import OutdoorStore
from stream import LineSubscriber, StreamHub
from protocol import (
    ProtocolError,
    Request,
    err_response,
    ok_response,
)

logger = logging.getLogger(__name__)


class Session:
    def __init__(
        self,
        reader: StreamReader,
        writer: StreamWriter,
        controllers: dict[str, AcController],
        peer: str,
        unit_labels: dict[str, str] | None = None,
        outdoor_store: OutdoorStore | None = None,
        icool: IcoolManager | None = None,
        hub: StreamHub | None = None,
        afterblow=None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._controllers = controllers
        self._peer = peer
        self._unit_labels = unit_labels or {}
        self._outdoor_store = outdoor_store
        self._icool = icool
        self._hub = hub
        self._afterblow = afterblow
        self._sub: LineSubscriber | None = None
        # 명령 처리는 REST와 공유하는 서비스 계층에 위임 (검증/부가동작 단일 구현)
        self._svc = CommandService(
            controllers, self._unit_labels, outdoor_store, icool, afterblow)

    async def run(self) -> None:
        logger.info("session started: %s", self._peer)
        try:
            while True:
                line = await self._reader.readline()
                logger.info("readline %d bytes from %s: %r", len(line), self._peer, line[:80])
                if not line:
                    break
                try:
                    text = line.decode("utf-8").strip()
                except UnicodeDecodeError:
                    logger.warning("non-UTF-8 data from %s, closing", self._peer)
                    break
                await self._handle_line(text)
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        finally:
            if self._sub is not None and self._hub is not None:
                await self._hub.remove_subscriber(self._sub)
            logger.info("session closed: %s", self._peer)
            self._writer.close()

    async def _handle_line(self, raw: str) -> None:
        if not raw:
            return
        try:
            req = Request.parse(raw)
        except ProtocolError as e:
            logger.warning("parse error from %s: %s", self._peer, e)
            resp = err_response("?", str(e))
            await self._send(resp.serialize())
            return

        logger.info("cmd=%s params=%s from %s", req.cmd, req.params, self._peer)
        resp = await self._dispatch(req)
        if resp is None:   # SUBSCRIBE 등 응답 없이 스트림으로 전환되는 명령
            return
        logger.info("resp ok=%s from %s", resp.ok, self._peer)
        await self._send(resp.serialize())

    # 명령 → 서비스 호출. 파라미터 검증·부가동작은 전부 CommandService에 있고
    # 여기서는 params dict를 인자로 풀어주는 일만 한다 (REST 라우트와 같은 계층 공유).
    _HANDLERS = {
        "LIST_UNITS":        lambda svc, p: svc.list_units(),
        "STATUS_OUTDOOR":    lambda svc, p: svc.outdoor_status(),
        "STATUS":            lambda svc, p: svc.unit_status(p.get("unit_id")),
        "SET_POWER":         lambda svc, p: svc.set_power(p.get("unit_id"), p.get("on")),
        "SET_MODE":          lambda svc, p: svc.set_mode(p.get("unit_id"), p.get("mode")),
        "SET_TEMP":          lambda svc, p: svc.set_target_temp(p.get("unit_id"), p.get("temp")),
        "SET_FAN":           lambda svc, p: svc.set_fan_mode(p.get("unit_id"), p.get("fan")),
        "SET_VANE":          lambda svc, p: svc.set_vane(
                                 p.get("unit_id"), p.get("vertical"), p.get("horizontal")),
        "SET_WIND_FREE":     lambda svc, p: svc.set_wind_free(p.get("unit_id"), p.get("on")),
        "SET_LONG_WIND":     lambda svc, p: svc.set_long_wind(p.get("unit_id"), p.get("on")),
        "SET_AUTO_CLEAN":    lambda svc, p: svc.set_auto_clean(p.get("unit_id"), p.get("on")),
        "SET_SMART_DRY":     lambda svc, p: svc.set_smart_dry(
                                 p.get("unit_id"), p.get("on"), ratio=p.get("ratio"),
                                 max_min=p.get("max_min"), min_min=p.get("min_min")),
        "SET_ICOOL":         lambda svc, p: svc.set_icool(
                                 p.get("unit_id"), p.get("on"),
                                 target=p.get("target"), config=p.get("config")),
        "SET_ICOOL_DURATION": lambda svc, p: svc.set_icool_duration(
                                 p.get("unit_id"), p.get("duration")),
        "SET_ICOOL_CONFIG":  lambda svc, p: svc.set_icool_config(
                                 p.get("unit_id"), p.get("config")),
    }

    async def _dispatch(self, req: Request):
        cmd = req.cmd
        p = req.params

        if cmd == "PING":
            return ok_response(req.id, {"pong": True})

        if cmd == "SUBSCRIBE":
            # 이 연결을 이벤트 스트림으로 전환. 이후 hub가 스냅샷 + 변경분을 push.
            if self._hub is None:
                return err_response(req.id, "stream not available")
            self._sub = LineSubscriber(self._writer)
            await self._hub.add_subscriber(self._sub)
            return None

        handler = self._HANDLERS.get(cmd)
        if handler is None:
            return err_response(req.id, f"unknown command: {cmd}")

        try:
            result = handler(self._svc, p)
            data = await result if asyncio.iscoroutine(result) else result
        except CommandError as e:
            return err_response(req.id, str(e))
        return ok_response(req.id, data)

    async def _send(self, data: str) -> None:
        self._writer.write(data.encode("utf-8"))
        await self._writer.drain()
