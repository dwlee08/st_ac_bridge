"""Glue Layer 진입점 — 추상 인터페이스 + MockAcController + RealAcController."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import packet_builder as pb
from state_store import AcStatus, StateStore

if TYPE_CHECKING:
    from ew11_client import EW11Client

logger = logging.getLogger(__name__)


class AcController(ABC):
    @abstractmethod
    async def get_status(self) -> AcStatus:
        raise NotImplementedError

    @abstractmethod
    async def set_power(self, on: bool) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def set_mode(self, mode: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def set_target_temp(self, temp: float) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def set_fan_mode(self, fan: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def set_vane(self, vertical: bool, horizontal: bool) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def set_wind_free(self, on: bool) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def set_long_wind(self, on: bool) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def set_auto_clean(self, on: bool) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def apply_settings(self, **fields) -> bool:
        """여러 설정을 한 번에 적용 (실기기는 C013 한 패킷 → 조작음 1회).

        fields는 AcStatus 필드명 기준. wind_free↔vane 같은 연동 필드는
        호출자가 최종 조합을 명시적으로 넘긴다 (개별 setter의 부수효과 없음).
        """
        raise NotImplementedError


class MockAcController(AcController):
    """실제 EW11 없이 서버 전체를 테스트하기 위한 더미 구현."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def get_status(self) -> AcStatus:
        return await self._store.get()

    async def set_power(self, on: bool) -> bool:
        await self._store.update(power=on)
        logger.info("mock: power=%s", on)
        return True

    async def set_mode(self, mode: str) -> bool:
        await self._store.update(mode=mode)
        logger.info("mock: mode=%s", mode)
        return True

    async def set_target_temp(self, temp: float) -> bool:
        await self._store.update(target_temp=temp)
        logger.info("mock: target_temp=%.1f", temp)
        return True

    async def set_fan_mode(self, fan: str) -> bool:
        await self._store.update(fan_mode=fan)
        logger.info("mock: fan_mode=%s", fan)
        return True

    async def set_vane(self, vertical: bool, horizontal: bool) -> bool:
        updates = dict(vane_vertical=vertical, vane_horizontal=horizontal)
        if vertical or horizontal:
            updates.update(wind_free=False, long_wind=False)
        await self._store.update(**updates)
        logger.info("mock: vane vertical=%s horizontal=%s", vertical, horizontal)
        return True

    async def set_wind_free(self, on: bool) -> bool:
        await self._store.update(wind_free=on)
        logger.info("mock: wind_free=%s", on)
        return True

    async def set_long_wind(self, on: bool) -> bool:
        await self._store.update(long_wind=on)
        logger.info("mock: long_wind=%s", on)
        return True

    async def set_auto_clean(self, on: bool) -> bool:
        await self._store.update(auto_clean=on)
        logger.info("mock: auto_clean=%s", on)
        return True

    async def apply_settings(self, **fields) -> bool:
        await self._store.update(**fields)
        logger.info("mock: apply %s", fields)
        return True


class RealAcController(AcController):
    """EW11을 통해 실제 RS485 패킷을 송수신하는 구현."""

    def __init__(self, unit_address: bytes, store: StateStore, ew11: EW11Client) -> None:
        self._dst   = unit_address
        self._store = store
        self._ew11  = ew11

    async def get_status(self) -> AcStatus:
        return await self._store.get()

    async def _powered_on(self) -> bool:
        return (await self._store.get()).power

    async def set_power(self, on: bool) -> bool:
        await self._store.set_desired(power=on)
        if on:
            # 꺼진 동안 쌓인 desired(모드/풍량/풍향 등)를 전원 코드와
            # C013 한 패킷으로 병합 — 별도 reconcile 패킷(조작음 추가) 방지
            diffs = await self._store.pending_diffs()
            diffs["power"] = True
            if "target_temp" not in diffs:
                diffs["target_temp"] = (await self._store.get()).target_temp
            pkt = pb.build_reconcile(self._dst, diffs)
        else:
            pkt = pb.build_set_power(self._dst, False)
        logger.info("TX SET_POWER on=%s pkt=%s", on, pkt.hex())
        await self._ew11.send_with_ack(pkt)
        return True

    async def set_mode(self, mode: str) -> bool:
        await self._store.set_desired(mode=mode)
        if not await self._powered_on():
            return True
        await self._ew11.send_with_ack(pb.build_set_mode(self._dst, mode))
        return True

    async def set_target_temp(self, temp: float) -> bool:
        await self._store.set_desired(target_temp=temp)
        if not await self._powered_on():
            return True
        status = await self._store.get()
        await self._ew11.send_with_ack(pb.build_set_target_temp(self._dst, temp, status.power))
        return True

    async def set_fan_mode(self, fan: str) -> bool:
        await self._store.set_desired(fan_mode=fan)
        if not await self._powered_on():
            return True
        await self._ew11.send_with_ack(pb.build_set_fan_mode(self._dst, fan))
        return True

    async def set_vane(self, vertical: bool, horizontal: bool) -> bool:
        desired = dict(vane_vertical=vertical, vane_horizontal=horizontal)
        if vertical or horizontal:
            desired.update(wind_free=False, long_wind=False)
        await self._store.set_desired(**desired)
        if not await self._powered_on():
            return True
        await self._ew11.send_with_ack(pb.build_set_vane(self._dst, vertical, horizontal))
        return True

    async def set_wind_free(self, on: bool) -> bool:
        if on:
            await self._store.set_desired(wind_free=True, long_wind=False,
                                          vane_vertical=False, vane_horizontal=False)
        else:
            await self._store.set_desired(wind_free=False)
        if not await self._powered_on():
            return True
        await self._ew11.send_with_ack(pb.build_set_wind_free(self._dst, on))
        return True

    async def set_long_wind(self, on: bool) -> bool:
        if on:
            await self._store.set_desired(long_wind=True, wind_free=False,
                                          vane_vertical=False, vane_horizontal=False)
        else:
            await self._store.set_desired(long_wind=False)
        if not await self._powered_on():
            return True
        await self._ew11.send_with_ack(pb.build_set_long_wind(self._dst, on))
        return True

    async def set_auto_clean(self, on: bool) -> bool:
        await self._store.set_desired(auto_clean=on)
        if not await self._powered_on():
            return True
        await self._ew11.send_with_ack(pb.build_set_auto_clean(self._dst, on))
        return True

    async def apply_settings(self, **fields) -> bool:
        await self._store.set_desired(**fields)
        # 전원을 켜는 요청이 아니고 현재 꺼져 있으면 desired만 기록 (개별 setter와 동일)
        if not fields.get("power") and not await self._powered_on():
            return True
        pkt = pb.build_reconcile(self._dst, fields)
        if not pkt:
            return True
        logger.info("TX APPLY %s pkt=%s", fields, pkt.hex())
        await self._ew11.send_with_ack(pkt)
        return True
