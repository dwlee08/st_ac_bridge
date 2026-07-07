"""session — unit_id 필수화(R2), SET_FAN 가드(R1), SET_MODE fanOnly 보정(D1)."""
import asyncio

from ac_controller import MockAcController
from protocol import Request
from session import Session
from state_store import StateStore


def make_session(controllers):
    return Session(reader=None, writer=None, controllers=controllers, peer="test")


def req(cmd, **params):
    return Request(id="1", cmd=cmd, params=params)


def run(coro):
    return asyncio.run(coro)


def setup():
    store = StateStore()
    ctrl = MockAcController(store)
    sess = make_session({"u1": ctrl})
    return store, ctrl, sess


# ── R2: unit_id 필수화 ───────────────────────────────────────────
def test_missing_unit_id_is_explicit_error():
    _, _, sess = setup()
    async def main():
        resp = await sess._dispatch(req("STATUS"))
        assert not resp.ok and "missing required param: unit_id" in resp.error
    run(main())


def test_unknown_unit_id_distinct_error():
    _, _, sess = setup()
    async def main():
        resp = await sess._dispatch(req("STATUS", unit_id="nope"))
        assert not resp.ok and "unknown unit_id: nope" in resp.error
    run(main())


def test_non_unit_commands_unaffected():
    _, _, sess = setup()
    async def main():
        resp = await sess._dispatch(req("PING"))
        assert resp.ok and resp.data == {"pong": True}
        resp = await sess._dispatch(req("LIST_UNITS"))
        assert resp.ok and resp.data["units"][0]["id"] == "u1"
    run(main())


def test_status_includes_unit_id():
    _, _, sess = setup()
    async def main():
        resp = await sess._dispatch(req("STATUS", unit_id="u1"))
        assert resp.ok and resp.data["unit_id"] == "u1"
    run(main())


# ── R1: SET_FAN 가드 ─────────────────────────────────────────────
def test_fan_auto_rejected_in_fanonly_mode():
    store, _, sess = setup()
    async def main():
        await store.update(mode="fanOnly")
        resp = await sess._dispatch(req("SET_FAN", unit_id="u1", fan="auto"))
        assert not resp.ok and "fanOnly" in resp.error
    run(main())


def test_fan_auto_allowed_in_cool_mode():
    store, _, sess = setup()
    async def main():
        await store.update(mode="cool")
        resp = await sess._dispatch(req("SET_FAN", unit_id="u1", fan="auto"))
        assert resp.ok
    run(main())


# ── D1: SET_MODE fanOnly 풍량 자동 보정 ──────────────────────────
def test_fanonly_with_auto_fan_corrects_to_low():
    store, _, sess = setup()
    async def main():
        await store.update(fan_mode="auto")
        resp = await sess._dispatch(req("SET_MODE", unit_id="u1", mode="fanOnly"))
        assert resp.ok and resp.data == {"fan_corrected": "low"}
        st = await store.get()
        assert st.mode == "fanOnly" and st.fan_mode == "low"
    run(main())


def test_fanonly_with_explicit_fan_no_correction():
    store, _, sess = setup()
    async def main():
        await store.update(fan_mode="high")
        resp = await sess._dispatch(req("SET_MODE", unit_id="u1", mode="fanOnly"))
        assert resp.ok and resp.data is None
        st = await store.get()
        assert st.mode == "fanOnly" and st.fan_mode == "high"
    run(main())


def test_invalid_mode_rejected():
    _, _, sess = setup()
    async def main():
        resp = await sess._dispatch(req("SET_MODE", unit_id="u1", mode="fan"))
        assert not resp.ok  # "fan"은 유효 모드가 아님
    run(main())
