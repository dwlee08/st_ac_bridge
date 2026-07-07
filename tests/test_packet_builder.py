"""packet_builder — payload item 동등성(R6 기준: seq 제외, companion 표 기반)."""
import packet_builder as pb
from helpers import packet_items

DST = b"\x20\x00\x00"

# 명령별 companion 필드 계약 (REFACTOR_PLAN.md R6 표)
def test_set_power_on_with_temp():
    items = packet_items(pb.build_set_power(DST, True, 23.5))
    assert items == [(0x4000, b"\x01"), (0x4201, (235).to_bytes(2, "big"))]


def test_set_power_off_is_power_only():
    assert packet_items(pb.build_set_power(DST, False)) == [(0x4000, b"\x00")]


def test_set_temp_carries_power_echo():
    items = packet_items(pb.build_set_target_temp(DST, 24.0, power=True))
    assert items == [(0x4000, b"\x01"), (0x4201, (240).to_bytes(2, "big"))]


def test_set_mode_single_code():
    assert packet_items(pb.build_set_mode(DST, "dry")) == [(0x4001, b"\x02")]


def test_set_fan_single_code():
    assert packet_items(pb.build_set_fan_mode(DST, "high")) == [(0x4006, b"\x03")]


def test_set_vane_on_carries_wind_modes_off():
    items = dict(packet_items(pb.build_set_vane(DST, True, True)))
    assert items[0x4011] == b"\x01" and items[0x407E] == b"\x01"
    assert items[0x4060] == b"\x00"   # wind_free off
    assert items[0x4007] == b"\x0e"   # long_wind off


def test_set_vane_off_no_companions():
    items = dict(packet_items(pb.build_set_vane(DST, False, False)))
    assert set(items) == {0x4011, 0x407E}


def test_wind_free_on_carries_long_wind_off():  # D2 의도 변경
    items = dict(packet_items(pb.build_set_wind_free(DST, True)))
    assert items[0x4060] == b"\x09"
    assert items[0x4011] == b"\x00" and items[0x407E] == b"\x00"
    assert items[0x4007] == b"\x0e"   # D2: long_wind off를 wire에 명시


def test_wind_free_off_single_code():
    assert packet_items(pb.build_set_wind_free(DST, False)) == [(0x4060, b"\x00")]


def test_long_wind_on_carries_wind_free_off():  # D2 의도 변경
    items = dict(packet_items(pb.build_set_long_wind(DST, True)))
    assert items[0x4007] == b"\x10"
    assert items[0x4011] == b"\x00" and items[0x407E] == b"\x00"
    assert items[0x4060] == b"\x00"   # D2: wind_free off를 wire에 명시


def test_reconcile_equals_wrappers_semantically():
    # 단일 매핑 지점 검증: 래퍼와 build_reconcile이 같은 필드셋에서 같은 items
    fields = {"mode": "cool", "fan_mode": "low"}
    a = packet_items(pb.build_reconcile(DST, fields))
    b = packet_items(pb.build_fields(DST, fields))
    assert a == b == [(0x4001, b"\x01"), (0x4006, b"\x01")]


def test_reconcile_empty_returns_empty_bytes():
    assert pb.build_reconcile(DST, {}) == b""


def test_crc_roundtrip_via_parser():
    # 생성 패킷이 기존 파서로 왕복 파싱됨 (CRC·SIZE 정합)
    pkt = pb.build_fields(DST, {"power": True, "mode": "cool", "target_temp": 23.0,
                                "fan_mode": "high", "vane_vertical": True,
                                "vane_horizontal": True, "wind_free": False,
                                "long_wind": False, "auto_clean": False})
    items = packet_items(pkt)
    assert len(items) == 9


def test_seq_increments_per_packet():
    a = pb.build_set_mode(DST, "cool")
    b = pb.build_set_mode(DST, "cool")
    assert a != b                      # seq(+CRC)만 다름
    assert packet_items(a) == packet_items(b)  # payload item은 동일
