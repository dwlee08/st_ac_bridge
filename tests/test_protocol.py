"""R4(enum 단일 진실원)·R5(normalize_airflow 진리표) 검증."""
from protocol import (
    FAN_BY_CODE,
    FAN_CODES,
    MODE_BY_CODE,
    MODE_CODES,
    VALID_FAN_MODES,
    VALID_MODES,
    normalize_airflow,
)


def test_mode_roundtrip():
    for name, code in MODE_CODES.items():
        assert MODE_BY_CODE[code] == name


def test_fan_roundtrip():
    for name, code in FAN_CODES.items():
        assert FAN_BY_CODE[code] == name


def test_valid_sets_derived():
    assert VALID_MODES == set(MODE_CODES)
    assert VALID_FAN_MODES == set(FAN_CODES)
    assert "fanOnly" in VALID_MODES  # "fan"이 아님 (R1의 근원)


# ── normalize_airflow 진리표 (D2 확정 규칙) ──────────────────────
def test_wind_free_on_forces_companions_off():
    out = normalize_airflow({"wind_free": True})
    assert out == {"wind_free": True, "long_wind": False,
                   "vane_vertical": False, "vane_horizontal": False}


def test_long_wind_on_forces_companions_off():
    out = normalize_airflow({"long_wind": True})
    assert out == {"long_wind": True, "wind_free": False,
                   "vane_vertical": False, "vane_horizontal": False}


def test_vane_on_forces_wind_modes_off():
    out = normalize_airflow({"vane_vertical": True, "vane_horizontal": False})
    assert out == {"vane_vertical": True, "vane_horizontal": False,
                   "wind_free": False, "long_wind": False}


def test_all_off_passthrough():
    fields = {"vane_vertical": False, "vane_horizontal": False}
    assert normalize_airflow(fields) == fields


def test_wind_free_off_no_side_effects():
    assert normalize_airflow({"wind_free": False}) == {"wind_free": False}


def test_priority_wind_free_over_conflicting_input():
    # 모순된 입력(무풍+풍향 동시 on)은 wind_free가 이긴다
    out = normalize_airflow({"wind_free": True, "vane_vertical": True})
    assert out["wind_free"] is True and out["vane_vertical"] is False


def test_non_airflow_fields_untouched():
    out = normalize_airflow({"wind_free": True, "target_temp": 24.0, "mode": "cool"})
    assert out["target_temp"] == 24.0 and out["mode"] == "cool"


def test_input_dict_not_mutated():
    fields = {"wind_free": True}
    normalize_airflow(fields)
    assert fields == {"wind_free": True}
