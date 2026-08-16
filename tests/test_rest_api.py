"""REST 라우팅 — 경로/메서드 매핑, 에러 상태코드, TCP와 동일한 검증 규칙."""
import asyncio

from ac_controller import MockAcController
from commands import CommandService
from icool import IcoolManager
from rest_api import Router
from state_store import OutdoorStore, StateStore


def run(coro):
    return asyncio.run(coro)


def setup():
    store = StateStore()
    controllers = {"u1": MockAcController(store)}
    svc = CommandService(controllers,
                         unit_labels={"u1": "에어컨 1"},
                         outdoor_store=OutdoorStore(),
                         icool=IcoolManager(controllers))
    return store, Router(svc)


def call(router, method, path, body=None):
    return run(router.dispatch(method, path, body or {}))


# ── 조회 ────────────────────────────────────────────────────────
def test_health():
    _, r = setup()
    status, payload = call(r, "GET", "/api/v1/health")
    assert status == 200 and payload["ok"] and payload["data"]["units"] == 1


def test_list_units():
    _, r = setup()
    status, payload = call(r, "GET", "/api/v1/units")
    assert status == 200
    assert payload["data"]["units"] == [{"id": "u1", "label": "에어컨 1"}]


def test_unit_status_includes_unit_id():
    _, r = setup()
    status, payload = call(r, "GET", "/api/v1/units/u1")
    assert status == 200 and payload["data"]["unit_id"] == "u1"


def test_outdoor_status():
    _, r = setup()
    status, payload = call(r, "GET", "/api/v1/outdoor")
    assert status == 200 and payload["ok"]


# ── 제어 ────────────────────────────────────────────────────────
def test_set_power():
    store, r = setup()
    status, payload = call(r, "POST", "/api/v1/units/u1/power", {"on": True})
    assert status == 200 and payload["ok"]
    assert run(store.get()).power is True


def test_set_temperature_rounds_to_half_degree():
    store, r = setup()
    call(r, "POST", "/api/v1/units/u1/temperature", {"temp": 23.4})
    assert run(store.get()).target_temp == 23.5


def test_set_vane_keeps_omitted_axis():
    store, r = setup()
    run(store.update(vane_horizontal=True))
    call(r, "POST", "/api/v1/units/u1/vane", {"vertical": True})
    st = run(store.get())
    assert st.vane_vertical is True and st.vane_horizontal is True


def test_icool_duration_route():
    _, r = setup()
    status, payload = call(r, "POST", "/api/v1/units/u1/icool/duration", {"duration": 30})
    assert status == 200 and payload["ok"]


# ── 에러 매핑 ───────────────────────────────────────────────────
def test_unknown_unit_is_404():
    _, r = setup()
    status, payload = call(r, "GET", "/api/v1/units/nope")
    assert status == 404 and "unknown unit_id: nope" in payload["error"]


def test_invalid_param_is_400():
    _, r = setup()
    status, payload = call(r, "POST", "/api/v1/units/u1/power", {"on": "yes"})
    assert status == 400 and "must be boolean" in payload["error"]


def test_out_of_range_temp_is_400():
    _, r = setup()
    status, payload = call(r, "POST", "/api/v1/units/u1/temperature", {"temp": 40})
    assert status == 400 and "out of range" in payload["error"]


def test_unavailable_feature_is_503():
    # icool 매니저 없이 구성된 서비스 → 503
    svc = CommandService({"u1": MockAcController(StateStore())})
    status, payload = call(Router(svc), "POST", "/api/v1/units/u1/icool", {"on": True})
    assert status == 503 and "icool not available" in payload["error"]


def test_wrong_method_is_405():
    _, r = setup()
    assert call(r, "GET", "/api/v1/units/u1/power")[0] == 405
    assert call(r, "POST", "/api/v1/units")[0] == 405


def test_unknown_route_is_404():
    _, r = setup()
    assert call(r, "GET", "/api/v1/nope")[0] == 404
    assert call(r, "GET", "/units")[0] == 404
    assert call(r, "POST", "/api/v1/units/u1/bogus")[0] == 404


# ── 송풍 모드 가드가 REST에도 동일 적용되는지 (TCP와 단일 구현 공유) ──
def test_fan_auto_rejected_in_fanonly_mode():
    store, r = setup()
    run(store.update(mode="fanOnly"))
    status, payload = call(r, "POST", "/api/v1/units/u1/fan", {"fan": "auto"})
    assert status == 400 and "fanOnly" in payload["error"]


def test_fanonly_corrects_auto_fan():
    store, r = setup()
    run(store.update(fan_mode="auto"))
    status, payload = call(r, "POST", "/api/v1/units/u1/mode", {"mode": "fanOnly"})
    assert status == 200 and payload["data"] == {"fan_corrected": "low"}
