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

# 아래 상수는 유닛별 튜닝값의 "기본값"이다. 실제 동작에는 IcoolState의 동명 필드가 쓰이며,
# 엣지 기기 설정(preferences)에서 SET_ICOOL_CONFIG로 유닛별로 덮어쓸 수 있다.
# (제어 루프가 유닛 공용 1개라, 유닛별 차등은 반드시 상태(IcoolState)에 있어야 한다.)
MARGIN = 0.5          # 무풍 켜고 끄는 경계 여유폭(℃)
BLOW_OFFSET = 1.0     # 강풍 단계 설정온도 = 목표 - 이 값(℃)
FAN_BLOW = "high"     # 냉방(blow) 단계 풍량 (기본 강풍)
VANE_BLOW = "all"     # 냉방(blow) 단계 풍향 모드 (기본 모든 방향)
HUM_LOW = 65          # 이 습도(%RH) 이하면 체감온도 보정 없음
HUM_HIGH = 80         # 이 습도 이상이면 최대 보정 (사이 구간은 선형)
HUM_BIAS_MAX = 1.0    # 체감온도 최대 보정(℃)
TICK_SEC = 5          # 제어 루프 주기(초) — 루프가 1개라 유닛 공용(전역), 설정 대상 아님
_MIN_VALID_TEMP = 5.0  # 실측 온도가 이 미만이면 아직 미수신으로 보고 제어 보류

_BLOW_FANS = {"auto", "low", "medium", "high"}

# 냉방 단계 풍향 모드 → (수직 스윙, 수평 스윙)
_VANE_MODES = {
    "fixed":      (False, False),   # 고정
    "vertical":   (True,  False),   # 수직
    "horizontal": (False, True),    # 수평
    "all":        (True,  True),    # 모든 방향
}


def _clamp(t: float) -> float:
    return max(TEMP_MIN, min(TEMP_MAX, t))


def _hum_bias(humidity: int | None, low: int = HUM_LOW, high: int = HUM_HIGH,
              bias_max: float = HUM_BIAS_MAX) -> float:
    """습도(%RH) → 체감온도 보정(℃). 미수신(None)이면 0. 임계값은 유닛별 설정."""
    if humidity is None or humidity <= low:
        return 0.0
    if high <= low:                       # 설정 이상값 방어 (0 나눗셈 방지)
        return bias_max
    return bias_max * min(1.0, (humidity - low) / (high - low))


@dataclass
class IcoolState:
    active: bool = False
    target: float = 24.0
    # ── 타이머 (icool과 분리) ──────────────────────────────────
    # duration_min: 사용자 선택값 (-1=연속/타이머 없음, 0=미사용, N=N분).
    # timer_sec: 남은 초. None=타이머 없음. 전원 ON일 때만 감소(전원 OFF면 일시정지).
    # 만료(0 도달) 시 AC 전원 OFF. icool 동작 여부와 무관하게 독립 동작.
    duration_min: int = 0
    timer_sec: float | None = None
    timer_last: float | None = None   # 마지막 감소 시각(monotonic)
    wind_free: bool = False         # 현재 무풍 단계 여부
    saved_state: dict | None = None    # icool 시작(신규) 시점의 AC 상태 스냅샷.
                                       # 스위치 OFF로 종료할 때 이 상태로 복원한다
                                       # (원래 전원 off였으면 복원=전원 off, on이었으면 원래 냉방 설정 복원).
    # 유닛별 튜닝값 (엣지 기기 설정에서 SET_ICOOL_CONFIG로 전달; 기본값=모듈 상수).
    margin: float = MARGIN
    blow_offset: float = BLOW_OFFSET
    hum_low: int = HUM_LOW
    hum_high: int = HUM_HIGH
    hum_bias_max: float = HUM_BIAS_MAX
    blow_fan: str = FAN_BLOW
    blow_vane: str = VANE_BLOW
    # 유닛별 락 — 한 유닛의 AC 명령 대기가 다른 유닛의 tick/start/stop을 막지 않도록
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    def cool_sp(self) -> float:
        # 무풍 진입 경계(목표-margin)보다 아래 — AC 내부 서모스탯이
        # 경계 도달 전에 압축기를 줄여 무풍 진입이 불발되는 것을 방지
        return _clamp(self.target - self.blow_offset)


def _apply_config(st: IcoolState, config: dict) -> None:
    """엣지가 보낸 유닛별 튜닝값을 IcoolState에 반영 (검증/클램프, 알 수 없는 키는 무시).
    None 값은 '미설정'으로 보고 건너뛴다(기존 값 유지)."""
    def num(key, lo, hi, cast):
        v = config.get(key)
        if v is None:
            return None
        try:
            return max(lo, min(hi, cast(v)))
        except (TypeError, ValueError):
            logger.warning("[icool] config %s 무시 (잘못된 값 %r)", key, v)
            return None

    m = num("margin", 0.1, 5.0, float)
    if m is not None:
        st.margin = m
    bo = num("blow_offset", 0.0, 5.0, float)
    if bo is not None:
        st.blow_offset = bo
    hl = num("hum_low", 0, 100, int)
    if hl is not None:
        st.hum_low = hl
    hh = num("hum_high", 0, 100, int)
    if hh is not None:
        st.hum_high = hh
    hb = num("hum_bias_max", 0.0, 5.0, float)
    if hb is not None:
        st.hum_bias_max = hb
    if config.get("blow_fan") in _BLOW_FANS:
        st.blow_fan = config["blow_fan"]
    if config.get("blow_vane") in _VANE_MODES:
        st.blow_vane = config["blow_vane"]
    # 상한이 하한 이하면 보정이 계단식이 되고 _hum_bias 0나눗셈 위험 → 최소 1 간격 보장
    if st.hum_high <= st.hum_low:
        st.hum_high = min(100, st.hum_low + 1)


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
        """icool_active: icool 동작 여부(타이머와 무관).
        timer_min: 타이머 남은 시간(분). -1=연속(타이머 없음), 0=미사용, N=남은 분.
        (남은 시간이 있으면 최소 1을 보장해 0(미사용)과 겹치지 않게 한다)."""
        st = self._states.get(uid)
        if st is None:
            return {"icool_active": False, "timer_min": 0}
        if st.timer_sec is not None:
            timer_min = max(1, math.ceil(st.timer_sec / 60))
        elif st.duration_min < 0:
            timer_min = -1
        else:
            timer_min = 0
        return {"icool_active": st.active, "timer_min": timer_min}

    # ── 엣지 명령 진입점 ─────────────────────────────────────────
    async def start(self, uid: str, target: float | None = None,
                    config: dict | None = None) -> None:
        # icool 시작. 타이머(duration)는 여기서 다루지 않는다 — set_duration으로 독립 제어.
        ctrl = self._controllers.get(uid)
        st = self._state(uid)
        if ctrl is None or st is None:
            logger.warning("[icool] start: unknown unit %s", uid)
            return
        async with st.lock:
            was_active = st.active   # 이미 동작 중이면 재적용(목표 변경 등) — 전원 켠 주체 판정 유지
            if config:
                _apply_config(st, config)   # 시작 시 최신 튜닝값 동봉 (브릿지 재시작 후에도 복원)
            if target is not None:
                st.target = _clamp(float(target))
            st.active = True
            await self._apply_start(ctrl, st, fresh=not was_active)
        logger.info("[icool] %s start target=%.1f "
                    "(margin=%.2f blow_off=%.2f hum=%d/%d/%.2f fan=%s vane=%s)",
                    uid, st.target,
                    st.margin, st.blow_offset, st.hum_low, st.hum_high, st.hum_bias_max,
                    st.blow_fan, st.blow_vane)

    async def set_config(self, uid: str, config: dict) -> None:
        """유닛별 튜닝값 갱신 (엣지 기기 설정 변경 시). 상태를 지연 생성해 start 전에도 보관하며,
        동작 중이면 다음 tick부터 새 값이 적용된다."""
        st = self._state(uid)
        if st is None:
            logger.warning("[icool] set_config: unknown unit %s", uid)
            return
        async with st.lock:
            _apply_config(st, config)
        logger.info("[icool] %s config margin=%.2f blow_off=%.2f hum=%d/%d/%.2f fan=%s vane=%s",
                    uid, st.margin, st.blow_offset, st.hum_low, st.hum_high, st.hum_bias_max,
                    st.blow_fan, st.blow_vane)

    async def stop(self, uid: str, reason: str = "user", restore: bool = True) -> None:
        st = self._states.get(uid)
        if st is None:
            return
        async with st.lock:
            if not st.active:
                return
            st.active = False
            # 타이머는 icool과 분리 — icool 정지 시에도 타이머는 그대로 둔다.
            saved = st.saved_state
            st.saved_state = None
        logger.info("[icool] %s stop (%s)", uid, reason)
        # restore=False면 복원하지 않고 비활성화만 한다. 호출측이 곧 전원을 끌
        # 예정(애프터블로우)인데 "냉방 ON 복원"을 하면 전원 OFF 의도와 충돌해
        # AC가 냉방으로 되살아나기 때문(리포트 D). 이 경우 상태만 비활성화한다.
        if not restore:
            return
        # 스위치 OFF 시 시작 시점 상태로 복원:
        #  - 원래 전원 off였으면 → AC 전원 OFF (icool이 켠 전원을 되돌림)
        #  - 원래 켜져 있던 냉방이면 → 그때의 모드/온도/풍량/풍향/무풍 설정 복원
        await self._restore(uid, saved, reason)

    async def _restore(self, uid: str, saved: dict | None, reason: str) -> None:
        ctrl = self._controllers.get(uid)
        if ctrl is None or saved is None:
            return
        if not saved.get("power"):
            await ctrl.set_power(False)
            logger.info("[icool] %s AC 전원 OFF (%s, 시작 시 꺼져 있었음)", uid, reason)
        else:
            await ctrl.apply_settings(**saved)   # power=True 포함 → 원래 냉방 상태 복원
            logger.info("[icool] %s 시작 시점 상태로 복원 (%s): %s", uid, reason, saved)

    async def set_duration(self, uid: str, duration_min: int) -> None:
        """타이머 설정 (icool과 독립). -1=연속(타이머 없음), 0=미사용/해제, N=N분.
        N분이면 즉시 카운트 시작하되, 전원 ON일 때만 감소한다(_check_timer)."""
        st = self._state(uid)   # icool 미동작 상태에서도 타이머를 걸 수 있게 생성
        if st is None:
            return
        async with st.lock:
            m = -1 if int(duration_min) < 0 else min(720, int(duration_min))
            st.duration_min = m
            if m > 0:
                st.timer_sec = m * 60
                st.timer_last = time.monotonic()
            else:
                st.timer_sec = None   # 연속/해제 → 타이머 없음
                st.timer_last = None
        logger.info("[timer] %s set %dmin", uid, m)

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
            if st.timer_sec is not None:      # 타이머는 icool 동작 여부와 무관하게 확인
                await self._check_timer(uid, st)
            if st.active:
                await self._tick(uid, st)

    # 타이머(icool과 분리): 전원 ON일 때만 실시간으로 감소, 0 도달 시 AC 전원 OFF.
    # 전원 OFF 동안은 timer_last만 갱신해 감소를 멈춘다(일시정지).
    async def _check_timer(self, uid: str, st: IcoolState) -> None:
        ctrl = self._controllers.get(uid)
        if ctrl is None:
            return
        powered = (await ctrl.get_status()).power
        expired = False
        async with st.lock:
            if st.timer_sec is None:
                return
            now = time.monotonic()
            if not powered:
                st.timer_last = now       # 꺼져 있는 동안은 감소하지 않음
                return
            if st.timer_last is not None:
                st.timer_sec -= (now - st.timer_last)
            st.timer_last = now
            if st.timer_sec <= 0:
                st.timer_sec = None
                st.timer_last = None
                st.duration_min = 0
                st.active = False         # 전원을 끄므로 icool도 함께 종료
                expired = True
        if expired:
            await ctrl.set_power(False)
            logger.info("[timer] %s 만료 → AC 전원 OFF", uid)

    async def _tick(self, uid: str, st: IcoolState) -> None:
        ctrl = self._controllers.get(uid)
        if ctrl is None:
            return
        status = await ctrl.get_status()
        async with st.lock:
            if not st.active:
                return
            # 예상 상태와 어긋나면 외부 조작으로 보고 icool 종료 (타이머는 건드리지 않음)
            if self._deviated(status, st):
                st.active = False
                logger.info("[icool] %s stop (external change)", uid)
                return
            # 온도 제어 (실측 미수신 시 보류)
            cur = status.current_temp or 0.0
            if cur < _MIN_VALID_TEMP:
                return
            await self._control(uid, ctrl, st, cur, status.humidity)

    async def _control(self, uid: str, ctrl: AcController, st: IcoolState,
                       cur: float, humidity: int | None) -> None:
        eff = cur + _hum_bias(humidity, st.hum_low, st.hum_high, st.hum_bias_max)  # 체감온도
        wf = self._decide(eff, st.target, st.wind_free, st.margin)
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
        v, h = _VANE_MODES.get(st.blow_vane, (True, True))
        return dict(wind_free=False, long_wind=False,
                    vane_vertical=v, vane_horizontal=h,
                    fan_mode=st.blow_fan, target_temp=st.cool_sp())

    # 실측-목표 온도차로 무풍 여부 결정. 경계는 ±margin 여유폭(유닛별).
    def _decide(self, cur: float, target: float, prev_wf: bool, margin: float = MARGIN) -> bool:
        delta = cur - target
        return (delta < margin) if prev_wf else (delta < -margin)

    async def _apply_start(self, ctrl: AcController, st: IcoolState, fresh: bool = True) -> None:
        # 현재 온도로 초기 단계 결정 — 이미 목표보다 시원하면 강풍 없이 무풍으로 시작
        status = await ctrl.get_status()
        if fresh:
            # 새로 시작하는 경우에만 스냅샷: icool 적용 전(=지금) 상태를 저장해 두고
            # 스위치 OFF 종료 시 복원한다. (재적용 시엔 icool이 이미 바꾼 상태라 저장하지 않음)
            # current_temp/humidity는 센서값이라 복원 대상에서 제외.
            st.saved_state = {
                "power":           status.power,
                "mode":            status.mode,
                "target_temp":     status.target_temp,
                "fan_mode":        status.fan_mode,
                "vane_vertical":   status.vane_vertical,
                "vane_horizontal": status.vane_horizontal,
                "wind_free":       status.wind_free,
                "long_wind":       status.long_wind,
            }
        cur = status.current_temp or 0.0
        eff = cur + _hum_bias(status.humidity, st.hum_low, st.hum_high, st.hum_bias_max)
        wf = cur >= _MIN_VALID_TEMP and self._decide(eff, st.target, False, st.margin)
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
            v, h = _VANE_MODES.get(st.blow_vane, (True, True))   # 유닛별 냉방 단계 풍향
            if status.vane_vertical != v or status.vane_horizontal != h:
                return True
            if status.fan_mode != st.blow_fan:   # 유닛별 냉방 단계 풍량 (_blow_fields와 일치해야 함)
                return True
            if abs(status.target_temp - st.cool_sp()) > 0.05:
                return True
        return False
