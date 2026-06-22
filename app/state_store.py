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
