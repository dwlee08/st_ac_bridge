"""명령 서비스 — 유닛 제어/조회 로직의 단일 진실원.

REST 라우터(rest_api.py)가 이 계층을 호출한다. 전송 계층은 요청 파싱과 응답
포맷만 담당하고, 파라미터 검증·상태 조합·부가 동작(애프터블로우 개입,
fanOnly 풍량 보정 등)은 전부 여기에만 존재한다.

계약: 성공하면 응답 data(dict) 또는 None을 반환하고, 잘못된 요청은
CommandError(미등록 유닛은 UnknownUnitError)를 던진다.
"""
from __future__ import annotations

from ac_controller import AcController
from icool import IcoolManager
from state_store import OutdoorStore
from protocol import TEMP_MAX, TEMP_MIN, VALID_FAN_MODES, VALID_MODES


class CommandError(Exception):
    """클라이언트의 잘못된 요청 (파라미터 누락/형식/범위)."""


class UnknownUnitError(CommandError):
    """등록되지 않은 unit_id."""


class UnavailableError(CommandError):
    """해당 기능이 이 구성에서 비활성 (icool/afterblow/outdoor 미탑재)."""


def _require_bool(value, name: str) -> bool:
    if not isinstance(value, bool):
        raise CommandError(f"params.{name} must be boolean")
    return value


def _require_number(value, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise CommandError(f"params.{name} must be number")
    return float(value)


class CommandService:
    def __init__(
        self,
        controllers: dict[str, AcController],
        unit_labels: dict[str, str] | None = None,
        outdoor_store: OutdoorStore | None = None,
        icool: IcoolManager | None = None,
        afterblow=None,
    ) -> None:
        self._controllers = controllers
        self._unit_labels = unit_labels or {}
        self._outdoor_store = outdoor_store
        self._icool = icool
        self._afterblow = afterblow

    # ── 조회 ────────────────────────────────────────────────────
    def list_units(self) -> dict:
        return {"units": [
            {"id": uid, "label": self._unit_labels.get(uid, uid)}
            for uid in self._controllers
        ]}

    async def outdoor_status(self) -> dict:
        if self._outdoor_store is None:
            raise UnavailableError("outdoor status not available")
        return (await self._outdoor_store.get()).to_dict()

    def _controller(self, uid: str | None) -> AcController:
        """unit_id(필수)로 컨트롤러 조회. 누락과 미등록을 구분해 에러를 낸다."""
        if uid is None:
            raise CommandError("missing required param: unit_id")
        ctrl = self._controllers.get(uid)
        if ctrl is None:
            raise UnknownUnitError(f"unknown unit_id: {uid}")
        return ctrl

    async def unit_status(self, uid: str) -> dict:
        ctrl = self._controller(uid)
        data = (await ctrl.get_status()).to_dict()
        data["unit_id"] = uid
        # 시스템 순시전력(실외기 합산 실측)을 공유값으로 echo.
        # 각 실내기 디바이스가 동일 값을 powerMeter로 노출(중복 표시는 무방).
        # 누적 에너지(powerConsumptionReport)는 중복 합산 방지를 위해
        # 실내기 STATUS에 넣지 않고 실외기 조회로만 제공한다.
        if self._outdoor_store is not None:
            outdoor = await self._outdoor_store.get()
            if outdoor.power_w is not None:
                data["system_power_w"] = outdoor.power_w
        # 인텔리전트 냉방 상태(활성/남은시간/문구)를 실어 엣지가 그대로 표시
        if self._icool is not None:
            data.update(self._icool.status(uid))
        # 스마트 애프터 블로우: 활성 여부 + 송풍 중 power=off 마스킹 (icool 뒤에 적용해 마스킹 우선)
        if self._afterblow is not None:
            data.update(self._afterblow.status(uid))
        return data

    # ── 기본 제어 ───────────────────────────────────────────────
    async def set_power(self, uid: str, on) -> dict | None:
        ctrl = self._controller(uid)
        on = _require_bool(on, "on")
        if self._afterblow is not None:
            if on:
                # 송풍 건조 중 전원 ON → 저장 상태 복원하고 종료(정상 on 대체)
                if await self._afterblow.resume(uid):
                    return self._afterblow.status(uid)
            else:
                # 전원 OFF → 조건 맞으면 바로 끄지 않고 송풍 건조 시작
                if await self._afterblow.on_power_off(uid):
                    return self._afterblow.status(uid)
        await ctrl.set_power(on)
        return None

    async def set_mode(self, uid: str, mode) -> dict | None:
        ctrl = self._controller(uid)
        if mode not in VALID_MODES:
            raise CommandError(f"invalid mode: {mode}")
        if mode == "fanOnly":
            status = await ctrl.get_status()
            if status.fan_mode == "auto":
                # 송풍 모드는 풍량 auto 미지원 → low로 보정해
                # 모드+풍량을 한 패킷으로 적용 (D1 정책)
                await ctrl.apply_settings(mode="fanOnly", fan_mode="low")
                return {"fan_corrected": "low"}
        await ctrl.set_mode(mode)
        return None

    async def set_target_temp(self, uid: str, temp) -> None:
        ctrl = self._controller(uid)
        temp = _require_number(temp, "temp")
        if temp < TEMP_MIN or temp > TEMP_MAX:
            raise CommandError(f"temp out of range: {TEMP_MIN}~{TEMP_MAX}")
        await ctrl.set_target_temp(round(temp * 2) / 2)   # 0.5℃ 단위로 반올림

    async def set_fan_mode(self, uid: str, fan) -> None:
        ctrl = self._controller(uid)
        if fan not in VALID_FAN_MODES:
            raise CommandError(f"invalid fan mode: {fan}")
        status = await ctrl.get_status()
        if status.mode == "fanOnly" and fan == "auto":
            raise CommandError("fan mode auto is not allowed when mode=fanOnly")
        await ctrl.set_fan_mode(fan)

    async def set_vane(self, uid: str, vertical, horizontal) -> None:
        ctrl = self._controller(uid)
        if vertical is None and horizontal is None:
            raise CommandError("params.vertical or horizontal required")
        if vertical is not None:
            _require_bool(vertical, "vertical")
        if horizontal is not None:
            _require_bool(horizontal, "horizontal")
        # 생략된 축은 현재 상태(source of truth)를 유지 → 상하/좌우 독립 제어.
        if vertical is None or horizontal is None:
            cur = await ctrl.get_status()
            if vertical is None:
                vertical = cur.vane_vertical
            if horizontal is None:
                horizontal = cur.vane_horizontal
        await ctrl.set_vane(vertical, horizontal)

    async def set_wind_free(self, uid: str, on) -> None:
        ctrl = self._controller(uid)
        await ctrl.set_wind_free(_require_bool(on, "on"))

    async def set_long_wind(self, uid: str, on) -> None:
        ctrl = self._controller(uid)
        await ctrl.set_long_wind(_require_bool(on, "on"))

    async def set_auto_clean(self, uid: str, on) -> None:
        ctrl = self._controller(uid)
        await ctrl.set_auto_clean(_require_bool(on, "on"))

    # ── 스마트 애프터 블로우 ─────────────────────────────────────
    async def set_smart_dry(
        self, uid: str, on, ratio=None, max_min=None, min_min=None,
    ) -> dict:
        self._controller(uid)
        if self._afterblow is None:
            raise UnavailableError("after blow not available")
        on = _require_bool(on, "on")
        await self._afterblow.set_enabled(
            uid, on, ratio=ratio, max_min=max_min, min_min=min_min)
        return self._afterblow.status(uid)

    # ── 인텔리전트 냉방 ──────────────────────────────────────────
    def _icool_mgr(self) -> IcoolManager:
        if self._icool is None:
            raise UnavailableError("icool not available")
        return self._icool

    async def set_icool(self, uid: str, on, target=None, config=None) -> dict:
        self._controller(uid)
        icool = self._icool_mgr()
        on = _require_bool(on, "on")
        if on:
            if target is not None:
                _require_number(target, "target")
            if config is not None and not isinstance(config, dict):
                raise CommandError("params.config must be object")
            # 타이머(duration)는 icool과 분리 — set_icool_duration으로만 제어한다.
            await icool.start(uid, target=target, config=config)
        else:
            await icool.stop(uid)
        return icool.status(uid)

    async def set_icool_duration(self, uid: str, duration) -> dict:
        self._controller(uid)
        icool = self._icool_mgr()
        await icool.set_duration(uid, int(_require_number(duration, "duration")))
        return icool.status(uid)

    async def set_icool_config(self, uid: str, config) -> dict:
        self._controller(uid)
        icool = self._icool_mgr()
        if not isinstance(config, dict):
            raise CommandError("params.config must be object")
        await icool.set_config(uid, config)
        return icool.status(uid)
