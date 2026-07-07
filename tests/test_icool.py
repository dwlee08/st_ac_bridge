"""icool 통합 스모크 — 시작 단계 결정, 무풍↔강풍 전환, _deviated 정합, 습도 보정."""
import asyncio

from ac_controller import MockAcController
from icool import IcoolManager, _hum_bias
from state_store import StateStore


def run(coro):
    return asyncio.run(coro)


def make_unit(**reported):
    store = StateStore()
    ctrl = MockAcController(store)
    return store, ctrl


# ── 습도 체감온도 보정 곡선 ──────────────────────────────────────
def test_hum_bias_curve():
    assert _hum_bias(None) == 0.0
    assert _hum_bias(65) == 0.0
    assert abs(_hum_bias(72.5) - 0.5) < 1e-9
    assert _hum_bias(80) == 1.0
    assert _hum_bias(95) == 1.0


# ── 시작 단계 결정 ───────────────────────────────────────────────
def test_start_cool_room_begins_wind_free():
    async def main():
        store, ctrl = make_unit()
        await store.update(current_temp=22.0, humidity=50)
        m = IcoolManager({"u1": ctrl})
        await m.start("u1", target=24.0)
        s = await ctrl.get_status()
        assert s.power and s.mode == "cool" and s.wind_free
        assert abs(s.target_temp - 24.0) < 0.01
    run(main())


def test_start_warm_room_begins_high_fan():
    async def main():
        store, ctrl = make_unit()
        await store.update(current_temp=27.0, humidity=50)
        m = IcoolManager({"u1": ctrl})
        await m.start("u1", target=24.0)
        s = await ctrl.get_status()
        assert not s.wind_free and s.fan_mode == "high"
        assert abs(s.target_temp - 23.0) < 0.01   # cool_sp = 목표-1.0
    run(main())


def test_start_no_temp_falls_back_to_high_fan():
    async def main():
        store, ctrl = make_unit()
        m = IcoolManager({"u1": ctrl})
        await m.start("u1", target=24.0)
        s = await ctrl.get_status()
        assert not s.wind_free and s.fan_mode == "high"
    run(main())


def test_start_humid_cool_room_stays_blow():
    # 실측 23.4(delta -0.6)이지만 습도 80% → 체감 24.4 → 강풍 유지
    async def main():
        store, ctrl = make_unit()
        await store.update(current_temp=23.4, humidity=80)
        m = IcoolManager({"u1": ctrl})
        await m.start("u1", target=24.0)
        assert not (await ctrl.get_status()).wind_free
    run(main())


# ── 전환 사이클 + _deviated 정합 ────────────────────────────────
def test_full_cycle_transitions_and_no_false_deviation():
    async def main():
        store, ctrl = make_unit()
        await store.update(current_temp=27.0, humidity=50)
        m = IcoolManager({"u1": ctrl})
        await m.start("u1", target=24.0)
        st = m._state("u1")

        await m._tick("u1", st)
        assert st.active                      # 전환 직후 오탐 없음

        await store.update(current_temp=23.4)  # 목표-0.6 → 무풍 진입
        await m._tick("u1", st)
        s = await ctrl.get_status()
        assert st.wind_free and s.wind_free and not s.vane_vertical
        assert abs(s.target_temp - 24.0) < 0.01
        await m._tick("u1", st)
        assert st.active

        await store.update(current_temp=24.6)  # 목표+0.6 → 강풍 복귀
        await m._tick("u1", st)
        s = await ctrl.get_status()
        assert not st.wind_free and s.fan_mode == "high" and s.vane_vertical
        assert abs(s.target_temp - 23.0) < 0.01
        await m._tick("u1", st)
        assert st.active
    run(main())


def test_external_change_stops_session():
    async def main():
        store, ctrl = make_unit()
        await store.update(current_temp=27.0)
        m = IcoolManager({"u1": ctrl})
        await m.start("u1", target=24.0)
        st = m._state("u1")
        await store.update(fan_mode="low")     # 외부에서 풍량 변경
        await m._tick("u1", st)
        assert not st.active
    run(main())


def test_hysteresis_holds_between_boundaries():
    async def main():
        store, ctrl = make_unit()
        await store.update(current_temp=27.0, humidity=50)
        m = IcoolManager({"u1": ctrl})
        await m.start("u1", target=24.0)
        st = m._state("u1")
        await store.update(current_temp=23.8)  # -0.2: 경계 안 → 강풍 유지
        await m._tick("u1", st)
        assert not st.wind_free and st.active
    run(main())
