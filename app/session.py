"""클라이언트 세션 — JSON 수신/파싱/명령 처리/응답 루프."""
from __future__ import annotations

import asyncio
import logging
from asyncio import StreamReader, StreamWriter

from ac_controller import AcController
from state_store import OutdoorStore
from protocol import (
    TEMP_MAX,
    TEMP_MIN,
    VALID_FAN_MODES,
    VALID_MODES,
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
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._controllers = controllers
        self._default_unit = next(iter(controllers), None)
        self._peer = peer
        self._unit_labels = unit_labels or {}
        self._outdoor_store = outdoor_store

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
        logger.info("resp ok=%s from %s", resp.ok, self._peer)
        await self._send(resp.serialize())

    def _resolve_controller(self, params: dict) -> tuple[AcController | None, str | None]:
        """unit_id로 컨트롤러 반환. 생략 시 기본 유닛. 없으면 (None, 오류메시지)."""
        uid = params.get("unit_id", self._default_unit)
        ctrl = self._controllers.get(uid)
        if ctrl is None:
            return None, f"unknown unit_id: {uid}"
        return ctrl, None

    async def _dispatch(self, req: Request):
        cmd = req.cmd
        p = req.params

        if cmd == "PING":
            return ok_response(req.id, {"pong": True})

        if cmd == "LIST_UNITS":
            units = [
                {"id": uid, "label": self._unit_labels.get(uid, uid)}
                for uid in self._controllers
            ]
            return ok_response(req.id, {"units": units})

        if cmd == "STATUS_OUTDOOR":
            if self._outdoor_store is None:
                return err_response(req.id, "outdoor status not available")
            status = await self._outdoor_store.get()
            return ok_response(req.id, status.to_dict())

        uid = p.get("unit_id", self._default_unit)
        ctrl, err = self._resolve_controller(p)
        if ctrl is None:
            return err_response(req.id, err)

        if cmd == "STATUS":
            status = await ctrl.get_status()
            data = status.to_dict()
            data["unit_id"] = uid
            # 시스템 순시전력(실외기 합산 실측)을 공유값으로 echo.
            # 각 실내기 디바이스가 동일 값을 powerMeter로 노출(중복 표시는 무방).
            # 누적 에너지(powerConsumptionReport)는 중복 합산 방지를 위해
            # 실내기 STATUS에 넣지 않고 STATUS_OUTDOOR(Gateway 전용)로만 제공한다.
            if self._outdoor_store is not None:
                outdoor = await self._outdoor_store.get()
                if outdoor.power_w is not None:
                    data["system_power_w"] = outdoor.power_w
            return ok_response(req.id, data)

        if cmd == "SET_POWER":
            on = p.get("on")
            if not isinstance(on, bool):
                return err_response(req.id, "params.on must be boolean")
            await ctrl.set_power(on)
            return ok_response(req.id)

        if cmd == "SET_MODE":
            mode = p.get("mode")
            if mode not in VALID_MODES:
                return err_response(req.id, f"invalid mode: {mode}")
            await ctrl.set_mode(mode)
            return ok_response(req.id)

        if cmd == "SET_TEMP":
            temp = p.get("temp")
            if not isinstance(temp, (int, float)):
                return err_response(req.id, "params.temp must be number")
            temp = float(temp)
            if temp < TEMP_MIN or temp > TEMP_MAX:
                return err_response(req.id, f"temp out of range: {TEMP_MIN}~{TEMP_MAX}")
            # 0.5℃ 단위로 반올림
            temp = round(temp * 2) / 2
            await ctrl.set_target_temp(temp)
            return ok_response(req.id)

        if cmd == "SET_FAN":
            fan = p.get("fan")
            if fan not in VALID_FAN_MODES:
                return err_response(req.id, f"invalid fan mode: {fan}")
            status = await ctrl.get_status()
            if status.mode == "fan" and fan == "auto":
                return err_response(req.id, "fan mode auto is not allowed when mode=fan")
            await ctrl.set_fan_mode(fan)
            return ok_response(req.id)

        if cmd == "SET_VANE":
            vertical   = p.get("vertical")
            horizontal = p.get("horizontal")
            if not isinstance(vertical, bool) or not isinstance(horizontal, bool):
                return err_response(req.id, "params.vertical and horizontal must be boolean")
            await ctrl.set_vane(vertical, horizontal)
            return ok_response(req.id)

        if cmd == "SET_WIND_FREE":
            on = p.get("on")
            if not isinstance(on, bool):
                return err_response(req.id, "params.on must be boolean")
            await ctrl.set_wind_free(on)
            return ok_response(req.id)

        if cmd == "SET_LONG_WIND":
            on = p.get("on")
            if not isinstance(on, bool):
                return err_response(req.id, "params.on must be boolean")
            await ctrl.set_long_wind(on)
            return ok_response(req.id)

        if cmd == "SET_AUTO_CLEAN":
            on = p.get("on")
            if not isinstance(on, bool):
                return err_response(req.id, "params.on must be boolean")
            await ctrl.set_auto_clean(on)
            return ok_response(req.id)

        return err_response(req.id, f"unknown command: {cmd}")

    async def _send(self, data: str) -> None:
        self._writer.write(data.encode("utf-8"))
        await self._writer.drain()
