"""에어컨 상태 저장소 — desired(의도 상태) / reported(AC 실제 상태) 분리."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field


@dataclass
class AcStatus:
    power: bool = False
    mode: str = "cool"            # auto / cool / dry / fanOnly
    target_temp: float = 24.0
    current_temp: float = 0.0
    fan_mode: str = "auto"        # auto / low / medium / high
    vane_vertical: bool = False
    vane_horizontal: bool = False
    wind_free: bool = False
    long_wind: bool = False
    auto_clean: bool = False
    humidity: int | None = None   # 읽기 전용, 센서 탑재 모델만 수신

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["humidity"] is None:
            del d["humidity"]
        return d


@dataclass
class OutdoorStatus:
    """실외기(주소 10:00:00) C014 브로드캐스트 기반 상태. 모두 읽기 전용.

    실외기 1대가 실내기 여러 대를 담당하므로 유닛별이 아닌 시스템 공용 상태다.
    미수신 필드는 None으로 두고 to_dict()에서 생략한다.
    """
    outdoor_temp: float | None = None          # 0x8204 외기 온도 ℃
    power_w: int | None = None                 # 0x8413 순시 전력 W (전 모듈 합)
    cumulative_energy_wh: int | None = None    # 0x8414 누적 전력량 Wh
    current_a: float | None = None             # 0x8217 실외기 전류 A
    voltage_v: float | None = None             # 0x24FC 전압 V
    odu_mode: str | None = None                # 0x8001 실외기 운전 모드
    heat_cool: str | None = None               # 0x8003 냉/난방 방향

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


class OutdoorStore:
    """실외기 상태 저장소. C014 수신으로만 갱신되는 단일 공용 상태."""

    def __init__(self) -> None:
        self._status = OutdoorStatus()
        self._lock = asyncio.Lock()

    async def get(self) -> OutdoorStatus:
        async with self._lock:
            return OutdoorStatus(**asdict(self._status))

    async def update(self, **kwargs) -> None:
        async with self._lock:
            for k, v in kwargs.items():
                if hasattr(self._status, k):
                    setattr(self._status, k, v)


# reconcile 대상 필드 (읽기 전용 제외)
_RECONCILE_FIELDS = frozenset({
    "power", "mode", "target_temp",
    "fan_mode", "vane_vertical", "vane_horizontal",
    "wind_free", "long_wind", "auto_clean",
})


class StateStore:
    def __init__(self) -> None:
        self._reported = AcStatus()          # C014로 갱신되는 실제 AC 상태
        self._desired: dict = {}             # 엣지드라이버가 명시적으로 요청한 필드만
        self._lock = asyncio.Lock()

    async def get(self) -> AcStatus:
        """reported에 desired override를 적용한 최종 상태 반환."""
        async with self._lock:
            result = AcStatus(**asdict(self._reported))
            for k, v in self._desired.items():
                setattr(result, k, v)
            return result

    async def set_desired(self, **kwargs) -> None:
        """엣지드라이버 명령 시 호출 — 해당 필드를 desired로 등록."""
        async with self._lock:
            for k, v in kwargs.items():
                if k in _RECONCILE_FIELDS:
                    self._desired[k] = v

    async def pending_diffs(self) -> dict:
        """C014 수신 없이 현재 desired vs reported 불일치 필드 반환."""
        async with self._lock:
            return {
                f: v for f, v in self._desired.items()
                if getattr(self._reported, f, None) != v
            }

    async def update(self, **kwargs) -> dict:
        """C014 수신 시 호출. desired와 다른 필드를 반환 (reconcile 대상)."""
        async with self._lock:
            for k, v in kwargs.items():
                if hasattr(self._reported, k):
                    setattr(self._reported, k, v)

            diffs: dict = {}
            settled: list = []
            for field, desired_val in self._desired.items():
                reported_val = getattr(self._reported, field, None)
                if reported_val == desired_val:
                    settled.append(field)   # AC가 원하는 값에 도달 → override 해제
                else:
                    diffs[field] = desired_val
            for f in settled:
                del self._desired[f]

            return diffs
