"""클라이언트 세션 — JSON 수신/파싱/명령 처리/응답 루프."""
from __future__ import annotations

import asyncio
import logging
from asyncio import StreamReader, StreamWriter

from ac_controller import AcController
from icool import IcoolManager
from state_store import OutdoorStore
from stream import StreamHub
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
        icool: IcoolManager | None = None,
        hub: StreamHub | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._controllers = controllers
        self._default_unit = next(iter(controllers), None)
        self._peer = peer
        self._unit_labels = unit_labels or {}
        self._outdoor_store = outdoor_store
        self._icool = icool
        self._hub = hub
        self._subscribed = False

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
            if self._subscribed and self._hub is not None:
                await self._hub.remove_subscriber(self._writer)
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

        if cmd == "SUBSCRIBE":
            # 이 연결을 이벤트 스트림으로 전환. 이후 hub가 스냅샷 + 변경분을 push.
            if self._hub is None:
                return err_response(req.id, "stream not available")
            await self._hub.add_subscriber(self._writer)
            self._subscribed = True
            return None

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
            # 인텔리전트 냉방 상태(활성/남은시간/문구)를 STATUS에 실어 엣지가 그대로 표시
            if self._icool is not None:
                data.update(self._icool.status(uid))
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

        # 인텔리전트 냉방: on=시작(목표/제한시간), off=종료. 실제 제어는 브릿지 루프가 담당.
        if cmd == "SET_ICOOL":
            if self._icool is None:
                return err_response(req.id, "icool not available")
            on = p.get("on")
            if not isinstance(on, bool):
                return err_response(req.id, "params.on must be boolean")
            if on:
                target = p.get("target")
                duration = p.get("duration")
                if target is not None and not isinstance(target, (int, float)):
                    return err_response(req.id, "params.target must be number")
                if duration is not None and not isinstance(duration, (int, float)):
                    return err_response(req.id, "params.duration must be number")
                await self._icool.start(uid, target=target, duration_min=duration)
            else:
                await self._icool.stop(uid)
            return ok_response(req.id, self._icool.status(uid))

        if cmd == "SET_ICOOL_DURATION":
            if self._icool is None:
                return err_response(req.id, "icool not available")
            duration = p.get("duration")
            if not isinstance(duration, (int, float)):
                return err_response(req.id, "params.duration must be number")
            await self._icool.set_duration(uid, int(duration))
            return ok_response(req.id, self._icool.status(uid))

        return err_response(req.id, f"unknown command: {cmd}")

    async def _send(self, data: str) -> None:
        self._writer.write(data.encode("utf-8"))
        await self._writer.drain()
