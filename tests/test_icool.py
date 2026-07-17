"""icool 통합 스모크 — 시작 단계 결정, 무풍↔강풍 전환, _deviated 정합, 습도 보정."""
import asyncio
import time

from afterblow import AfterBlowManager
from ac_controller import MockAcController
from icool import IcoolManager, _hum_bias
from state_store import StateStore


def run(coro):
    return asyncio.run(coro)


class RecordingCtrl(MockAcController):
    """apply_settings 호출 순서를 기록해 명령 시퀀스를 검증할 수 있게 한다."""

    def __init__(self, store):
        super().__init__(store)
        self.applies: list[dict] = []

    async def apply_settings(self, **fields):
        self.applies.append(dict(fields))
        return await super().apply_settings(**fields)


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


def test_external_mode_change_stops_after_debounce():
    # 모드 변경은 실제 종료 신호. 단 한 tick 오차 흡수를 위해 DEVIATE_TICKS 연속돼야 종료.
    async def main():
        store, ctrl = make_unit()
        await store.update(current_temp=27.0)
        m = IcoolManager({"u1": ctrl})
        await m.start("u1", target=24.0)
        st = m._state("u1")
        await store.update(mode="auto")        # 외부에서 모드 변경
        await m._tick("u1", st)
        assert st.active                        # 1틱: 디바운스 유예
        await m._tick("u1", st)
        assert not st.active                    # 2틱 연속: 종료
    run(main())


def test_transient_deviation_recovers_without_stop():
    # 한 tick만 어긋났다가 회복되면 종료하지 않는다(디바운스).
    async def main():
        store, ctrl = make_unit()
        await store.update(current_temp=27.0)
        m = IcoolManager({"u1": ctrl})
        await m.start("u1", target=24.0)
        st = m._state("u1")
        await store.update(mode="auto")        # 순간 어긋남
        await m._tick("u1", st)
        assert st.active and st.deviate_count == 1
        await store.update(mode="cool")        # 회복
        await m._tick("u1", st)
        assert st.active and st.deviate_count == 0
    run(main())


def test_autonomous_fan_vane_change_does_not_stop():
    # AC가 냉방 중 풍량/풍향을 스스로 바꿔도 icool은 유지된다(리포트 A/B/E).
    async def main():
        store, ctrl = make_unit()
        await store.update(current_temp=27.0)
        m = IcoolManager({"u1": ctrl})
        await m.start("u1", target=24.0)        # blow 단계(high, vane all)
        st = m._state("u1")
        await store.update(fan_mode="low", vane_vertical=False, vane_horizontal=False)
        await m._tick("u1", st)
        assert st.active
        await m._tick("u1", st)
        assert st.active                        # 여러 틱 지나도 유지
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


# ── 애프터블로우 전원 OFF 시 icool 복원 충돌 방지 (리포트 D) ──────
def test_stop_restore_false_does_not_touch_ac():
    # restore=False면 상태만 비활성화하고 AC에 아무 명령도 안 보낸다(냉방 복원 없음).
    async def main():
        store = StateStore()
        ctrl = RecordingCtrl(store)
        await store.update(power=True, current_temp=27.0, mode="cool")
        m = IcoolManager({"u1": ctrl})
        await m.start("u1", target=24.0)          # active, saved_state.power=True
        st = m._state("u1")
        assert st.active and st.saved_state["power"] is True
        before = await ctrl.get_status()
        n = len(ctrl.applies)
        await m.stop("u1", reason="after_blow", restore=False)
        assert not st.active
        assert len(ctrl.applies) == n             # 복원 명령 없음
        assert (await ctrl.get_status()) == before
    run(main())


def test_after_blow_power_off_deactivates_icool_without_cool_rebound():
    # icool 동작 중 앱 전원 OFF → 애프터블로우 건조 시작. 이때 icool.stop의
    # "냉방 ON 복원"이 끼어들어 냉방으로 되살아나면 안 된다(리포트 D 리바운드).
    async def main():
        store = StateStore()
        ctrl = RecordingCtrl(store)
        await store.update(power=True, current_temp=27.0, mode="cool")
        icool = IcoolManager({"u1": ctrl})
        await icool.start("u1", target=24.0)
        assert icool._state("u1").active

        ab = AfterBlowManager({"u1": ctrl}, icool)
        await ab.set_enabled("u1", True)
        ab._state("u1").power_on_at = time.monotonic() - 600   # 10분 동작 → 건조 조건 충족

        start_idx = len(ctrl.applies)
        handled = await ab.on_power_off("u1")
        assert handled is True                     # 정상 off 대신 건조 시작
        assert not icool._state("u1").active       # icool 비활성화됨
        after = ctrl.applies[start_idx:]
        assert all(a.get("mode") != "cool" for a in after)   # 냉방 재적용(리바운드) 없음
        assert any(a.get("mode") == "fanOnly" for a in after)  # 송풍 건조만 적용
    run(main())
