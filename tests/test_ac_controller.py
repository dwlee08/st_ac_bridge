"""ac_controller — Mock/Real 상태 변화 동등성(R5), 배치·전원 ON 병합 패킷."""
import asyncio

from ac_controller import MockAcController, RealAcController
from helpers import FakeEW11, packet_items
from state_store import StateStore

DST = b"\x20\x00\x00"
AIRFLOW = ("vane_vertical", "vane_horizontal", "wind_free", "long_wind")


def run(coro):
    return asyncio.run(coro)


async def _mock_state_after(setter, *args):
    store = StateStore()
    ctrl = MockAcController(store)
    await getattr(ctrl, setter)(*args)
    return await store.get()


async def _real_desired_after(setter, *args):
    store = StateStore()
    await store.update(power=True)  # 전송 경로 활성화
    ctrl = RealAcController(DST, store, FakeEW11())
    await getattr(ctrl, setter)(*args)
    return await store.get()


def test_mock_real_equivalence_airflow_setters():
    # 동일 setter 호출 후 기류 필드 상태가 Mock == Real(desired 반영)
    cases = [
        ("set_vane", (True, True)),
        ("set_vane", (False, False)),
        ("set_wind_free", (True,)),
        ("set_wind_free", (False,)),
        ("set_long_wind", (True,)),
        ("set_long_wind", (False,)),
    ]
    async def main():
        for setter, args in cases:
            m = await _mock_state_after(setter, *args)
            r = await _real_desired_after(setter, *args)
            for f in AIRFLOW:
                assert getattr(m, f) == getattr(r, f), (setter, args, f)
    run(main())


def test_real_wind_free_packet_carries_long_wind_off():  # D2
    async def main():
        store = StateStore()
        await store.update(power=True)
        ew = FakeEW11()
        ctrl = RealAcController(DST, store, ew)
        await ctrl.set_wind_free(True)
        items = dict(packet_items(ew.sent[-1]))
        assert items[0x4060] == b"\x09" and items[0x4007] == b"\x0e"
    run(main())


def test_apply_settings_normalizes():
    async def main():
        store = StateStore()
        await store.update(power=True)
        ew = FakeEW11()
        ctrl = RealAcController(DST, store, ew)
        await ctrl.apply_settings(wind_free=True, target_temp=24.0)
        st = await store.get()
        assert st.wind_free and not st.long_wind
        assert not st.vane_vertical and not st.vane_horizontal
        items = dict(packet_items(ew.sent[-1]))
        assert items[0x4060] == b"\x09" and items[0x4007] == b"\x0e"
        assert 0x4011 in items and 0x407E in items
    run(main())


def test_apply_settings_off_when_powered_off_queues_only():
    async def main():
        store = StateStore()
        ew = FakeEW11()
        ctrl = RealAcController(DST, store, ew)
        await ctrl.apply_settings(fan_mode="high")
        assert ew.sent == []
        assert (await store.pending_diffs()) == {"fan_mode": "high"}
    run(main())


def test_power_on_merges_queued_desired_into_one_packet():
    async def main():
        store = StateStore()
        await store.update(power=False, mode="auto", fan_mode="auto", target_temp=24.0)
        ew = FakeEW11()
        ctrl = RealAcController(DST, store, ew)
        await ctrl.set_mode("cool")
        await ctrl.set_fan_mode("high")
        assert ew.sent == []                 # 꺼짐 중 큐잉만
        await ctrl.set_power(True)
        assert len(ew.sent) == 1             # 한 패킷(조작음 1회)
        items = dict(packet_items(ew.sent[0]))
        assert items[0x4000] == b"\x01"      # power on
        assert items[0x4001] == b"\x01"      # cool
        assert items[0x4006] == b"\x03"      # high
        assert 0x4201 in items               # target_temp 동봉
    run(main())


def test_mock_apply_settings_normalizes():
    async def main():
        store = StateStore()
        ctrl = MockAcController(store)
        await ctrl.apply_settings(long_wind=True)
        st = await store.get()
        assert st.long_wind and not st.wind_free
        assert not st.vane_vertical and not st.vane_horizontal
    run(main())
