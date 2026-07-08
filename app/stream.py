"""이벤트 스트림(push) — 구독자에게 상태 변경만 밀어주는 pub/sub 허브.

엣지가 SUBSCRIBE로 지속 연결하면, 접속 즉시 전체 스냅샷을 받고 이후에는
상태가 바뀔 때만 변경분(diff)을 push로 받는다. 폴링(STATUS 주기 조회)을 대체한다.

프로토콜(줄단위 JSON):
    수신  {"cmd":"SUBSCRIBE"}
    송신  {"t":"snapshot","units":{uid:{...}},"outdoor":{...}}   # 접속 직후 1회
          {"t":"state","u":uid,"d":{...변경필드...}}            # 유닛 상태 변경
          {"t":"outdoor","d":{...변경필드...}}                  # 실외기 변경

구현 메모: 매 변경 지점에 훅을 거는 대신 짧은 주기 스윕으로 유효상태(get)를
비교해 diff만 브로드캐스트한다. 내부 비교는 공짜에 가깝고, 네트워크/ST 이벤트는
변경 시에만 발생하므로 폴 폭주 없이 실시간에 가깝게 반영된다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from asyncio import StreamWriter

from icool import IcoolManager
from state_store import OutdoorStore

logger = logging.getLogger(__name__)

SWEEP_INTERVAL = 1.0   # 상태 변경 감지 주기(초)


def _encode(msg: dict) -> bytes:
    return (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")


class StreamHub:
    def __init__(
        self,
        controllers: dict,
        icool: IcoolManager,
        outdoor_store: OutdoorStore | None = None,
    ) -> None:
        self._controllers = controllers
        self._icool = icool
        self._outdoor_store = outdoor_store
        self._subs: set[StreamWriter] = set()
        self._last_unit: dict[str, dict] = {}
        self._last_outdoor: dict = {}
        self._lock = asyncio.Lock()

    # ── 유닛/스냅샷 상태 구성 ────────────────────────────────────
    async def _unit_state(self, uid: str, ctrl, power_w: int | None) -> dict:
        s = (await ctrl.get_status()).to_dict()
        s.update(self._icool.status(uid))          # icool_active/icool_duration_min
        if power_w is not None:
            s["system_power_w"] = power_w           # 실외기 합산 전력을 각 유닛이 echo
        return s

    async def snapshot(self) -> dict:
        outdoor = await self._outdoor_store.get() if self._outdoor_store else None
        power_w = outdoor.power_w if outdoor else None
        units = {}
        for uid, ctrl in self._controllers.items():
            units[uid] = await self._unit_state(uid, ctrl, power_w)
        return {"t": "snapshot", "units": units,
                "outdoor": outdoor.to_dict() if outdoor else {}}

    # ── 구독자 관리 ──────────────────────────────────────────────
    async def add_subscriber(self, writer: StreamWriter) -> None:
        async with self._lock:
            self._subs.add(writer)
        try:
            writer.write(_encode(await self.snapshot()))
            await writer.drain()
            logger.info("stream subscriber added (%d total)", len(self._subs))
        except Exception:
            await self.remove_subscriber(writer)

    async def remove_subscriber(self, writer: StreamWriter) -> None:
        async with self._lock:
            self._subs.discard(writer)

    async def _broadcast(self, msg: dict) -> None:
        data = _encode(msg)
        async with self._lock:
            subs = list(self._subs)
        dead = []
        for w in subs:
            try:
                w.write(data)
                await w.drain()
            except Exception:
                dead.append(w)
        if dead:
            async with self._lock:
                for w in dead:
                    self._subs.discard(w)
            logger.info("stream dropped %d dead subscriber(s)", len(dead))

    # ── 변경 감지 스윕 ───────────────────────────────────────────
    async def run_loop(self) -> None:
        logger.info("stream hub started (sweep=%ss)", SWEEP_INTERVAL)
        while True:
            try:
                await self._sweep()
            except Exception:
                logger.exception("stream sweep error")
            await asyncio.sleep(SWEEP_INTERVAL)

    async def _sweep(self) -> None:
        outdoor = await self._outdoor_store.get() if self._outdoor_store else None
        power_w = outdoor.power_w if outdoor else None

        for uid, ctrl in self._controllers.items():
            cur = await self._unit_state(uid, ctrl, power_w)
            prev = self._last_unit.get(uid, {})
            diff = {k: v for k, v in cur.items() if prev.get(k) != v}
            if diff:
                self._last_unit[uid] = cur
                await self._broadcast({"t": "state", "u": uid, "d": diff})

        if outdoor is not None:
            cur = outdoor.to_dict()
            diff = {k: v for k, v in cur.items() if self._last_outdoor.get(k) != v}
            if diff:
                self._last_outdoor = cur
                await self._broadcast({"t": "outdoor", "d": diff})
