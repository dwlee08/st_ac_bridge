"""state_decoder — 코드→필드 디코딩, unknown fallback (T0 스냅샷)."""
from protocol import FAN_CODES, MODE_CODES
from state_decoder import decode_codes


def test_mode_decode_all():
    for name, code in MODE_CODES.items():
        assert decode_codes([(0x4001, bytes([code]))])["mode"] == name


def test_fan_decode_all():
    for name, code in FAN_CODES.items():
        assert decode_codes([(0x4006, bytes([code]))])["fan_mode"] == name


def test_unknown_mode_falls_back_to_cool():
    assert decode_codes([(0x4001, bytes([0x7F]))])["mode"] == "cool"


def test_unknown_fan_falls_back_to_auto():
    assert decode_codes([(0x4006, bytes([0x7F]))])["fan_mode"] == "auto"


def test_scalar_decodes():
    codes = [
        (0x4000, b"\x01"),
        (0x4201, (235).to_bytes(2, "big")),
        (0x4203, (267).to_bytes(2, "big")),
        (0x4060, b"\x09"),
        (0x4007, b"\x10"),
        (0x4038, b"\x37"),
    ]
    u = decode_codes(codes)
    assert u["power"] is True
    assert u["target_temp"] == 23.5
    assert u["current_temp"] == 26.7
    assert u["wind_free"] is True
    assert u["long_wind"] is True
    assert u["humidity"] == 55


def test_zero_current_temp_ignored():
    # 0.0은 미수신으로 보고 필드 자체를 만들지 않음
    assert "current_temp" not in decode_codes([(0x4203, b"\x00\x00")])
