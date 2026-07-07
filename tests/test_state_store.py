"""state_store — 격리·override·settled·외부 전원 ON 클리어 (T0 + R7)."""
import asyncio

import pytest

from state_store import AcStatus, OutdoorStore, StateStore


def run(coro):
    return asyncio.run(coro)


def test_get_returns_isolated_copy():
    async def main():
        s = StateStore()
        a = await s.get()
        a.power = True
        a.target_temp = 99.0
        b = await s.get()
        assert b.power is False and b.target_temp == 24.0
    run(main())


def test_outdoor_get_isolated():
    async def main():
        s = OutdoorStore()
        a = await s.get()
        a.power_w = 12345
        assert (await s.get()).power_w is None
    run(main())


def test_desired_override_applied():
    async def main():
        s = StateStore()
        await s.set_desired(fan_mode="high", target_temp=23.0)
        st = await s.get()
        assert st.fan_mode == "high" and st.target_temp == 23.0
    run(main())


def test_update_settles_matching_desired():
    async def main():
        s = StateStore()
        await s.set_desired(fan_mode="high")
        diffs = await s.update(fan_mode="high")
        assert diffs == {}
        assert await s.pending_diffs() == {}
    run(main())


def test_update_returns_diffs_for_mismatch():
    async def main():
        s = StateStore()
        await s.update(power=True)
        await s.set_desired(fan_mode="high")
        diffs = await s.update(fan_mode="low")
        assert diffs == {"fan_mode": "high"}
    run(main())


def test_readonly_fields_not_desired():
    async def main():
        s = StateStore()
        await s.set_desired(current_temp=10.0, humidity=99)  # reconcile 대상 아님
        assert await s.pending_diffs() == {}
    run(main())


# ── 외부 전원 ON 정책 ────────────────────────────────────────────
def test_external_power_on_clears_pending():
    async def main():
        s = StateStore()
        await s.set_desired(fan_mode="high", mode="cool")
        diffs = await s.update(power=True, fan_mode="auto", mode="auto")
        assert diffs == {}
        st = await s.get()
        assert st.fan_mode == "auto" and st.mode == "auto"
    run(main())


def test_bridge_power_on_keeps_pending():
    async def main():
        s = StateStore()
        await s.set_desired(power=True, fan_mode="high")  # 브릿지 명령 경로
        diffs = await s.update(power=True, fan_mode="auto")
        assert diffs == {"fan_mode": "high"}  # reconcile 안전망 유지
    run(main())


def test_remote_on_wins_over_pending_off():
    async def main():
        s = StateStore()
        await s.update(power=True)
        await s.set_desired(power=False)
        await s.update(power=False)          # 꺼짐 확인 → settled
        await s.set_desired(mode="dry")      # 꺼진 채 조작
        diffs = await s.update(power=True)   # 리모컨 ON
        assert diffs == {}
        assert (await s.get()).power is True
    run(main())
