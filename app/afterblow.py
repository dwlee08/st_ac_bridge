"""스마트 애프터 블로우 — 전원 OFF 시 송풍으로 내부를 말린 뒤 끄는 기능(브릿지 측).

앱/브릿지 제어로 전원을 끄면 바로 끄지 않고, 송풍(fanOnly)+강풍+풍향 고정으로 전환해
'동작했던 시간의 절반'(최대 max_min, run이 min_min 미만이면 적용 안 함)만큼 말린 뒤 전원을 끈다.
- 송풍 중 내부 전원 상태는 OFF로 보고(status에서 power 마스킹) — 앱엔 꺼짐으로 표시.
- 블로우 시작 직전에만 에어컨 자체 자동건조를 끈다(이중 건조 방지). 리모컨 OFF는
  이 사이클을 안 타므로 에어컨 자체 자동건조가 살아 있다.
- 송풍 중 앱 전원 ON 또는 리모컨 조작이 들어오면 저장한 상태로 복원하고 종료.

트리거는 앱/브릿지 경유 SET_POWER off에서만 (session이 on_power_off로 위임). 리모컨 물리 OFF는
이미 꺼진 뒤라 인터셉트하지 않는다.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field

from ac_controller import AcController

logger = logging.getLogger(__name__)

TICK_SEC = 5            # 전원 상태 추적/건조 타이머 확인 주기(초)
RATIO_DEFAULT = 50     # 동작 시간 대비 송풍 비율(%) 기본값(=절반)
MAX_MIN_DEFAULT = 60   # 건조 최대 시간(분)
MIN_MIN_DEFAULT = 3    # 이 시간(분) 미만 동작이면 건조 적용 안 함


@dataclass
class AfterBlowState:
    enabled: bool = False              # 기능 on/off (사용자 스위치)
    power_on_at: float | None = None   # 마지막 전원 ON 시각(monotonic)
    was_powered: bool = False          # 직전 tick 전원 상태(전이 감지)
    drying: bool = False               # 송풍 건조 진행 중
    dry_deadline: float | None = None
    saved_state: dict | None = None    # 복원용 스냅샷(apply_settings 필드, auto_clean 제외)
    saved_auto: bool = False           # 시작 직전 자동건조 설정(복원용)
    ratio: int = RATIO_DEFAULT         # 동작 시간 대비 송풍 비율(%)
    max_min: int = MAX_MIN_DEFAULT
    min_min: int = MIN_MIN_DEFAULT
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)


# 건조(송풍) 단계에서 에어컨에 강제할 설정
def _blow_fields() -> dict:
    return dict(power=True, mode="fanOnly", fan_mode="high",
                vane_vertical=False, vane_horizontal=False,
                wind_free=False, long_wind=False)


def _snapshot(status) -> dict:
    # 복원용 — 센서값(current_temp/humidity)과 auto_clean은 제외(auto_clean은 따로 복원)
    return {
        "power":           True,       # 끄기 직전 = 켜져 있던 상태
        "mode":            status.mode,
        "target_temp":     status.target_temp,
        "fan_mode":        status.fan_mode,
        "vane_vertical":   status.vane_vertical,
        "vane_horizontal": status.vane_horizontal,
        "wind_free":       status.wind_free,
        "long_wind":       status.long_wind,
    }


class AfterBlowManager:
    def __init__(self, controllers: dict[str, AcController], icool=None) -> None:
        self._controllers = controllers
        self._icool = icool   # 건조 시작 시 icool 동작 중이면 정지시키기 위함
        self._states: dict[str, AfterBlowState] = {}

    def _state(self, uid: str) -> AfterBlowState | None:
        if uid not in self._controllers:
            return None
        st = self._states.get(uid)
        if st is None:
            st = AfterBlowState()
            self._states[uid] = st
        return st

    # ── STATUS 노출용 ────────────────────────────────────────────
    def status(self, uid: str) -> dict:
        st = self._states.get(uid)
        out = {"after_blow_enabled": bool(st and st.enabled)}
        if st and st.enabled:
            # 기능 on이면 엣지엔 자동건조 off로 표시(실제 AC 자동건조는 사이클 직전에만 끔).
            out["auto_clean"] = False
        if st and st.drying:
            out["power"] = False   # 송풍 중 내부 전원 OFF로 마스킹
        return out

    # ── 엣지 명령 진입점 ─────────────────────────────────────────
    async def set_enabled(self, uid: str, on: bool, ratio: int | None = None,
                          max_min: int | None = None, min_min: int | None = None) -> None:
        st = self._state(uid)
        if st is None:
            return
        async with st.lock:
            st.enabled = bool(on)
            if ratio is not None:
                st.ratio = max(20, min(100, int(ratio)))
            if max_min is not None:
                st.max_min = max(1, int(max_min))
            if min_min is not None:
                st.min_min = max(0, int(min_min))
        logger.info("[afterblow] %s enabled=%s (ratio=%d%% max=%dmin min=%dmin)",
                    uid, st.enabled, st.ratio, st.max_min, st.min_min)

    # 앱/브릿지 경유 전원 OFF 위임. True를 반환하면 호출측은 실제 set_power(False)를 하지 않는다.
    async def on_power_off(self, uid: str) -> bool:
        ctrl = self._controllers.get(uid)
        st = self._state(uid)
        if ctrl is None or st is None or not st.enabled:
            return False
        status = await ctrl.get_status()
        async with st.lock:
            if st.drying:
                return True                 # 이미 건조 중 — 중복 off 무시
            if not status.power:
                return False                # 이미 꺼져 있음 → 정상 처리
            run_sec = (time.monotonic() - st.power_on_at) if st.power_on_at else 0.0
            if run_sec < st.min_min * 60:
                return False                # 너무 짧음 → 건조 스킵(자동건조 그대로 정상 off)
            dry_sec = min(run_sec * st.ratio / 100.0, st.max_min * 60)
            st.saved_state = _snapshot(status)
            st.saved_auto = status.auto_clean
            st.drying = True
            st.dry_deadline = time.monotonic() + dry_sec
        # icool 동작 중이면 정지(전원을 곧 끌 것이므로). 복원은 하지 않는다 —
        # icool.stop의 "냉방 ON 복원"이 곧 있을 전원 OFF/송풍과 충돌하기 때문(리포트 D).
        if self._icool is not None:
            await self._icool.stop(uid, reason="after_blow", restore=False)
        await ctrl.set_auto_clean(False)          # 시작 직전에만 자동건조 끔(이중 건조 방지)
        await ctrl.apply_settings(**_blow_fields())
        logger.info("[afterblow] %s 시작: run=%.0fs → 송풍 %.0f분 (자동건조 OFF)",
                    uid, run_sec, dry_sec / 60)
        return True

    # 앱 전원 ON 위임. 건조 중이면 복원+종료하고 True. 아니면 False(정상 on 처리).
    async def resume(self, uid: str) -> bool:
        st = self._states.get(uid)
        if st is None:
            return False
        async with st.lock:
            if not st.drying:
                return False
            saved = st.saved_state
            saved_auto = st.saved_auto
            st.drying = False
            st.dry_deadline = None
            st.saved_state = None
        await self._restore(uid, saved, saved_auto, "앱 전원 ON")
        return True

    async def _restore(self, uid: str, saved: dict | None, saved_auto: bool, why: str) -> None:
        ctrl = self._controllers.get(uid)
        if ctrl is None or saved is None:
            return
        await ctrl.apply_settings(**saved)        # power=True 포함 → 원래 상태 복원
        await ctrl.set_auto_clean(saved_auto)     # 자동건조 설정도 복원
        logger.info("[afterblow] %s 복원/종료 (%s): %s auto_clean=%s", uid, why, saved, saved_auto)

    # ── 제어 루프 ────────────────────────────────────────────────
    async def run_loop(self) -> None:
        logger.info("[afterblow] loop started (tick=%ds)", TICK_SEC)
        while True:
            try:
                # 기능 활성 여부와 무관하게 모든 유닛을 tick — 전원 ON 시각을 항상 추적해,
                # 동작 중에 스마트 애프터 블로우를 켜도 작동 시간을 정확히 반영한다.
                for uid in list(self._controllers.keys()):
                    st = self._state(uid)
                    if st is not None:
                        await self._tick(uid, st)
            except Exception:
                logger.exception("[afterblow] tick error")
            await asyncio.sleep(TICK_SEC)

    async def _tick(self, uid: str, st: AfterBlowState) -> None:
        ctrl = self._controllers.get(uid)
        if ctrl is None:
            return
        status = await ctrl.get_status()
        now = time.monotonic()
        if not st.drying:
            # 전원 ON 시각 추적 (off→on 전이) — 리모컨 ON 포함
            if status.power and not st.was_powered:
                st.power_on_at = now
            st.was_powered = status.power
            return
        # ── 건조 중 ──
        # 1) 타이머 만료 → 실제 전원 OFF + 종료 (자동건조는 복원 설정으로 다음 ON 때 반영)
        if st.dry_deadline is not None and now >= st.dry_deadline:
            saved_auto = st.saved_auto
            st.drying = False
            st.dry_deadline = None
            st.saved_state = None
            st.was_powered = False
            await ctrl.set_power(False)
            await ctrl.set_auto_clean(saved_auto)   # 다음 전원 ON 시 반영(리모컨 off 대비)
            logger.info("[afterblow] %s 완료 → 전원 OFF (자동건조 복원=%s)", uid, saved_auto)
            return
        # 2) 리모컨으로 꺼짐 → 그대로 종료(복원 안 함)
        if not status.power:
            st.drying = False
            st.dry_deadline = None
            st.saved_state = None
            st.was_powered = False
            logger.info("[afterblow] %s 송풍 중 외부 전원 OFF → 종료", uid)
            return
        # 3) 리모컨으로 다른 설정으로 변경(송풍 강제값과 어긋남) → 복원 후 종료
        blow = _blow_fields()
        if (status.mode != blow["mode"] or status.fan_mode != blow["fan_mode"]
                or status.vane_vertical or status.vane_horizontal):
            saved = st.saved_state
            saved_auto = st.saved_auto
            st.drying = False
            st.dry_deadline = None
            st.saved_state = None
            await self._restore(uid, saved, saved_auto, "송풍 중 외부 조작")
