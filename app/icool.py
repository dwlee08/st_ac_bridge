"""인텔리전트 냉방(Intelligent Cooling) — 브릿지 측 제어 로직.

엣지는 인터페이스일 뿐이고, "냉방 목표온도와 실측 온도로 풍량/무풍을 자동 조절" 하는
제어 루프/타이머/종료판정은 여기(상주 프로세스)에서 담당한다.

풍량 자동 조절 (체감-목표 = delta):
    delta < -0.5 → 무풍(windFree), delta ≥ +0.5 → 강풍(high)
    (±0.5 히스테리시스 — 목표 근처에서 잦은 전환 방지, 그 사이는 이전 단계 유지)
체감온도 = 실측 + 습도 보정: 65%RH 이하 0, 65~80% 선형, 80% 이상 +1.0℃.
    습할수록 무풍 진입은 늦고 해제는 빨라져 강풍(제습) 체류가 늘고, 습도가
    내려가면 보정이 줄어 무풍으로 자연 수렴한다. 습도 미수신이면 보정 없음.
설정온도: 무풍이면 목표, 강풍이면 목표-1.0 (무풍 진입 경계보다 아래에 둬서
    AC 내부 서모스탯이 경계 도달 전에 냉방을 멈추는 일이 없게 한다).

시작: 전원 on, 냉방(cool), 현재 온도로 초기 단계 결정 — 이미 목표 아래면 무풍,
      아니면 상하·좌우 풍향 + 강풍 + 설정온도=목표-1.0 (이후 루프가 조절).
모든 시작/전환은 apply_settings로 C013 한 패킷에 담아 전송 — AC 조작음 1회.
종료: 타이머 만료, 또는 icool가 명령한 "예상 상태"와 실제가 어긋나면(전원/모드/풍량
      /풍향/무풍/설정온도 — 엣지·리모컨·판넬 무관) 종료. AC 상태는 그대로 둔다.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field

from ac_controller import AcController
from protocol import TEMP_MAX, TEMP_MIN

logger = logging.getLogger(__name__)

MARGIN = 0.5          # 무풍 켜고 끄는 경계 여유폭(℃)
FAN_BLOW = "high"     # blow 단계 풍량 (강풍 고정)
HUM_LOW = 65          # 이 습도(%RH) 이하면 체감온도 보정 없음
HUM_HIGH = 80         # 이 습도 이상이면 최대 보정 (사이 구간은 선형)
HUM_BIAS_MAX = 1.0    # 체감온도 최대 보정(℃)
TICK_SEC = 5          # 제어 루프 주기(초)
_MIN_VALID_TEMP = 5.0  # 실측 온도가 이 미만이면 아직 미수신으로 보고 제어 보류


def _clamp(t: float) -> float:
    return max(TEMP_MIN, min(TEMP_MAX, t))


def _hum_bias(humidity: int | None) -> float:
    """습도(%RH) → 체감온도 보정(℃). 미수신(None)이면 0."""
    if humidity is None or humidity <= HUM_LOW:
        return 0.0
    return HUM_BIAS_MAX * min(1.0, (humidity - HUM_LOW) / (HUM_HIGH - HUM_LOW))


@dataclass
class IcoolState:
    active: bool = False
    target: float = 24.0
    duration_min: int = 0
    deadline: float | None = None   # time.monotonic() 기준 종료시각. None=무제한
    wind_free: bool = False         # 현재 무풍 단계 여부
    # 유닛별 락 — 한 유닛의 AC 명령 대기가 다른 유닛의 tick/start/stop을 막지 않도록
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    def cool_sp(self) -> float:
        # 무풍 진입 경계(목표-0.5)보다 0.5℃ 아래 — AC 내부 서모스탯이
        # 경계 도달 전에 압축기를 줄여 무풍 진입이 불발되는 것을 방지
        return _clamp(self.target - 1.0)


class IcoolManager:
    def __init__(self, controllers: dict[str, AcController]) -> None:
        self._controllers = controllers
        # 유닛은 C014로 나중에 auto-register될 수 있으므로 상태는 지연 생성(스냅샷 금지).
        self._states: dict[str, IcoolState] = {}

    def _state(self, uid: str) -> IcoolState | None:
        """등록된 유닛의 icool 상태를 (필요 시 생성해) 반환. 미등록이면 None."""
        if uid not in self._controllers:
            return None
        st = self._states.get(uid)
        if st is None:
            st = IcoolState()
            self._states[uid] = st
        return st

    # ── STATUS 노출용 ────────────────────────────────────────────
    def status(self, uid: str) -> dict:
        """icool_duration_min: 남은 시간(분). -1=무제한 동작 중, 0=미사용.
        동작 중엔 최소 1을 보장해 0(미사용)과 겹치지 않게 한다 (만료는 tick이 처리)."""
        st = self._states.get(uid)
        if st is None or not st.active:
            return {"icool_active": False, "icool_duration_min": 0}
        if st.deadline is None:
            return {"icool_active": True, "icool_duration_min": -1}
        remain = max(1, math.ceil((st.deadline - time.monotonic()) / 60))
        return {"icool_active": True, "icool_duration_min": remain}

    # ── 엣지 명령 진입점 ─────────────────────────────────────────
    async def start(self, uid: str, target: float | None = None,
                    duration_min: int | None = None) -> None:
        ctrl = self._controllers.get(uid)
        st = self._state(uid)
        if ctrl is None or st is None:
            logger.warning("[icool] start: unknown unit %s", uid)
            return
        async with st.lock:
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
        async with st.lock:
            if not st.active:
                return
            st.active = False
            st.deadline = None
        logger.info("[icool] %s stop (%s)", uid, reason)

    async def set_duration(self, uid: str, duration_min: int) -> None:
        st = self._states.get(uid)
        if st is None:
            return
        async with st.lock:
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
        # await 중 start()가 새 유닛을 등록해도 안전하도록 스냅샷 순회
        for uid, st in list(self._states.items()):
            if st.active:
                await self._tick(uid, st)

    async def _tick(self, uid: str, st: IcoolState) -> None:
        ctrl = self._controllers.get(uid)
        if ctrl is None:
            return
        status = await ctrl.get_status()
        async with st.lock:
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
            await self._control(uid, ctrl, st, cur, status.humidity)

    async def _control(self, uid: str, ctrl: AcController, st: IcoolState,
                       cur: float, humidity: int | None) -> None:
        eff = cur + _hum_bias(humidity)   # 체감온도(습도 보정)로 판정
        wf = self._decide(eff, st.target, st.wind_free)
        if wf and not st.wind_free:
            await ctrl.apply_settings(**self._wind_free_fields(st))
            st.wind_free = True
            logger.info("[icool] %s 체감 %.1f<목표 → 무풍 ON, 설정 %.1f", uid, eff, st.target)
        elif not wf and st.wind_free:  # 무풍 → 강풍 복귀
            await ctrl.apply_settings(**self._blow_fields(st))
            st.wind_free = False
            logger.info("[icool] %s 체감 %.1f>목표 → 무풍 OFF, 강풍, 설정 %.1f", uid, eff, st.cool_sp())

    # 단계별 설정 조합 — apply_settings로 C013 한 패킷에 담아 조작음을 1회로 줄인다.
    @staticmethod
    def _wind_free_fields(st: IcoolState) -> dict:
        return dict(wind_free=True, long_wind=False,
                    vane_vertical=False, vane_horizontal=False,
                    target_temp=_clamp(st.target))

    @staticmethod
    def _blow_fields(st: IcoolState) -> dict:
        return dict(wind_free=False, long_wind=False,
                    vane_vertical=True, vane_horizontal=True,
                    fan_mode=FAN_BLOW, target_temp=st.cool_sp())

    # 실측-목표 온도차로 무풍 여부 결정. 경계는 ±0.5 여유폭 (blow는 강풍 고정).
    def _decide(self, cur: float, target: float, prev_wf: bool) -> bool:
        delta = cur - target
        return (delta < MARGIN) if prev_wf else (delta < -MARGIN)

    async def _apply_start(self, ctrl: AcController, st: IcoolState) -> None:
        # 현재 온도로 초기 단계 결정 — 이미 목표보다 시원하면 강풍 없이 무풍으로 시작
        status = await ctrl.get_status()
        cur = status.current_temp or 0.0
        eff = cur + _hum_bias(status.humidity)
        wf = cur >= _MIN_VALID_TEMP and self._decide(eff, st.target, False)
        stage = self._wind_free_fields(st) if wf else self._blow_fields(st)
        await ctrl.apply_settings(power=True, mode="cool", **stage)
        st.wind_free = wf

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
            if status.fan_mode != FAN_BLOW:
                return True
            if abs(status.target_temp - st.cool_sp()) > 0.05:
                return True
        return False
