"""인텔리전트 냉방(Intelligent Cooling) — 브릿지 측 제어 로직.

엣지는 인터페이스일 뿐이고, "냉방 목표온도와 실측 온도로 풍량/무풍을 자동 조절" 하는
제어 루프/타이머/종료판정은 여기(상주 프로세스)에서 담당한다.

풍량 자동 조절 (실측-목표 = delta):
    delta > 2.0        → 강풍(high)
    1.0 < delta ≤ 2.0  → 중풍(medium)
    -0.3 미만은 무풍, 그 위 ~ 1.0 이하 → 약풍(low)
    delta < -0.3       → 무풍(windFree)   (목표 근처 ±0.3 여유폭으로 잦은 전환 방지)
설정온도: 무풍이면 목표, 아니면 목표-0.5 (blow 중엔 빠르게 냉방).

시작: 전원 on, 냉방(cool), 상하·좌우 풍향, 강풍, 설정온도=목표-0.5 (이후 루프가 조절).
종료: 타이머 만료, 또는 icool가 명령한 "예상 상태"와 실제가 어긋나면(전원/모드/풍량
      /풍향/무풍/설정온도 — 엣지·리모컨·판넬 무관) 종료. AC 상태는 그대로 둔다.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass

from ac_controller import AcController
from protocol import TEMP_MAX, TEMP_MIN

logger = logging.getLogger(__name__)

MARGIN = 0.3          # 무풍 켜고 끄는 경계 여유폭(℃)
TICK_SEC = 5          # 제어 루프 주기(초)
_MIN_VALID_TEMP = 5.0  # 실측 온도가 이 미만이면 아직 미수신으로 보고 제어 보류


def _clamp(t: float) -> float:
    return max(TEMP_MIN, min(TEMP_MAX, t))


@dataclass
class IcoolState:
    active: bool = False
    target: float = 24.0
    duration_min: int = 0
    deadline: float | None = None   # time.monotonic() 기준 종료시각. None=무제한
    wind_free: bool = False         # 현재 무풍 단계 여부
    fan_level: str = "high"         # blow 단계의 현재 풍량 (high/medium/low)

    def cool_sp(self) -> float:
        return _clamp(self.target - 0.5)


class IcoolManager:
    def __init__(self, controllers: dict[str, AcController]) -> None:
        self._controllers = controllers
        self._states: dict[str, IcoolState] = {uid: IcoolState() for uid in controllers}
        self._lock = asyncio.Lock()

    # ── STATUS 노출용 ────────────────────────────────────────────
    def status(self, uid: str) -> dict:
        st = self._states.get(uid)
        if st is None or not st.active:
            return {"icool_active": False, "icool_status": "대기 중"}
        if st.deadline is None:
            return {"icool_active": True, "icool_remaining_min": None,
                    "icool_status": "인텔리전트 동작 중 (무제한)"}
        remain = max(0, math.ceil((st.deadline - time.monotonic()) / 60))
        return {"icool_active": True, "icool_remaining_min": remain,
                "icool_status": f"인텔리전트 동작 중 ({remain}분 남음)"}

    # ── 엣지 명령 진입점 ─────────────────────────────────────────
    async def start(self, uid: str, target: float | None = None,
                    duration_min: int | None = None) -> None:
        ctrl = self._controllers.get(uid)
        st = self._states.get(uid)
        if ctrl is None or st is None:
            return
        async with self._lock:
            if target is not None:
                st.target = _clamp(float(target))
            if duration_min is not None:
                st.duration_min = max(0, min(720, int(duration_min)))
            st.active = True
            st.deadline = (time.monotonic() + st.duration_min * 60) if st.duration_min > 0 else None
            await self._apply_start(ctrl, st)
        logger.info("[icool] %s start target=%.1f duration=%dmin", uid, st.target, st.duration_min)

    async def stop(self, uid: str, reason: str = "user") -> None:
        st = self._states.get(uid)
        if st is None:
            return
        async with self._lock:
            if not st.active:
                return
            st.active = False
            st.deadline = None
        logger.info("[icool] %s stop (%s)", uid, reason)

    async def set_duration(self, uid: str, duration_min: int) -> None:
        st = self._states.get(uid)
        if st is None:
            return
        async with self._lock:
            st.duration_min = max(0, min(720, int(duration_min)))
            if st.active:
                st.deadline = (time.monotonic() + st.duration_min * 60) if st.duration_min > 0 else None
        logger.info("[icool] %s duration=%dmin", uid, st.duration_min)

    # ── 제어 루프 ────────────────────────────────────────────────
    async def run_loop(self) -> None:
        logger.info("[icool] control loop started (tick=%ds)", TICK_SEC)
        while True:
            try:
                await self._tick_all()
            except Exception:  # 루프가 죽지 않도록
                logger.exception("[icool] tick error")
            await asyncio.sleep(TICK_SEC)

    async def _tick_all(self) -> None:
        for uid, st in self._states.items():
            if st.active:
                await self._tick(uid, st)

    async def _tick(self, uid: str, st: IcoolState) -> None:
        ctrl = self._controllers.get(uid)
        if ctrl is None:
            return
        status = await ctrl.get_status()
        async with self._lock:
            if not st.active:
                return
            # 1) 타이머 만료
            if st.deadline is not None and time.monotonic() >= st.deadline:
                st.active = False
                st.deadline = None
                logger.info("[icool] %s stop (timer)", uid)
                return
            # 2) 예상 상태와 어긋나면 외부 조작으로 보고 종료
            if self._deviated(status, st):
                st.active = False
                st.deadline = None
                logger.info("[icool] %s stop (external change)", uid)
                return
            # 3) 온도 제어 (실측 미수신 시 보류)
            cur = status.current_temp or 0.0
            if cur < _MIN_VALID_TEMP:
                return
            await self._control(uid, ctrl, st, cur)

    async def _control(self, uid: str, ctrl: AcController, st: IcoolState, cur: float) -> None:
        fan, wf = self._decide(cur, st.target, st.wind_free)
        if wf:
            if not st.wind_free:
                await ctrl.set_wind_free(True)
                await ctrl.set_target_temp(_clamp(st.target))
                st.wind_free = True
                logger.info("[icool] %s %.1f<목표 → 무풍 ON, 설정 %.1f", uid, cur, st.target)
            return
        if st.wind_free:  # 무풍 → blow 복귀
            await ctrl.set_vane(True, True)         # 풍향 복원 (무풍 해제 부수효과 포함)
            await ctrl.set_target_temp(st.cool_sp())
            await ctrl.set_fan_mode(fan)
            st.wind_free = False
            st.fan_level = fan
            logger.info("[icool] %s %.1f>목표 → 무풍 OFF, 풍량 %s, 설정 %.1f", uid, cur, fan, st.cool_sp())
        elif fan != st.fan_level:  # blow 내 풍량 단계 변경
            await ctrl.set_fan_mode(fan)
            st.fan_level = fan
            logger.info("[icool] %s Δ%.1f → 풍량 %s", uid, cur - st.target, fan)

    # 실측-목표 온도차로 (풍량, 무풍여부) 결정. 무풍 경계는 ±0.3 여유폭.
    def _decide(self, cur: float, target: float, prev_wf: bool) -> tuple[str, bool]:
        delta = cur - target
        wf = (delta < MARGIN) if prev_wf else (delta < -MARGIN)
        if wf:
            return "auto", True   # 무풍 중 fan은 AC가 강제 (반환값 미사용)
        if delta > 2.0:
            fan = "high"
        elif delta > 1.0:
            fan = "medium"
        else:
            fan = "low"
        return fan, False

    async def _apply_start(self, ctrl: AcController, st: IcoolState) -> None:
        await ctrl.set_power(True)
        await ctrl.set_mode("cool")
        await ctrl.set_vane(True, True)
        await ctrl.set_fan_mode("high")           # 시작은 강풍, 이후 루프가 온도차로 조절
        await ctrl.set_target_temp(st.cool_sp())
        st.wind_free = False
        st.fan_level = "high"

    # ── 종료 판정 (단계별 예상 상태 vs 실제) ─────────────────────
    def _deviated(self, status, st: IcoolState) -> bool:
        if not status.power:
            return True                            # 전원 off
        if status.mode != "cool":
            return True                            # 모드 변경
        if st.wind_free:  # 무풍 중엔 풍량/풍향을 AC가 강제하므로 제외
            if not status.wind_free:
                return True
            if abs(status.target_temp - _clamp(st.target)) > 0.05:
                return True
        else:
            if status.wind_free:
                return True
            if not (status.vane_vertical and status.vane_horizontal):
                return True
            if status.fan_mode != st.fan_level:
                return True
            if abs(status.target_temp - st.cool_sp()) > 0.05:
                return True
        return False
