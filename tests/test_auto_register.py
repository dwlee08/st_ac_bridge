"""실내기 자동 등록 게이트 — 유령 유닛(20ffff 등) 차단 검증."""
import asyncio

import packet_builder as pb
import pytest
from ew11_client import MIN_SIGHTINGS_TO_REGISTER, EW11Client
from packet_parser import ParsedPacket, is_physical_address


def run(coro):
    return asyncio.run(coro)


def make_client(**kw) -> EW11Client:
    return EW11Client(host="127.0.0.1", port=8899, stores={}, unit_addresses={},
                      controllers={}, unit_labels={}, **kw)


def status_pkt(src_hex: str, codes=None) -> ParsedPacket:
    return ParsedPacket(
        src=bytes.fromhex(src_hex), dst=b"\xb0\xff\xff", msg_type=0xC014, seq=0,
        codes=[(0x4000, b"\x01"), (0x4201, b"\x00\xf0")] if codes is None else codes,
    )


def feed(client: EW11Client, pkt: ParsedPacket, times: int = 1) -> None:
    async def main():
        for _ in range(times):
            await client._handle_packet(pkt)
    run(main())


# ── 주소 판별 ───────────────────────────────────────────────────
def test_wildcard_addresses_are_not_physical():
    assert not is_physical_address(b"\x20\xff\xff")   # 모든 실내기 브로드캐스트
    assert not is_physical_address(b"\x20\x00\xff")
    assert not is_physical_address(b"\x20\xff\x00")
    assert not is_physical_address(b"\xff\xff\xff")


def test_real_indoor_addresses_are_physical():
    assert is_physical_address(b"\x20\x00\x00", klass=0x20)
    assert is_physical_address(b"\x20\x01\x03", klass=0x20)


def test_class_mismatch_rejected():
    assert not is_physical_address(b"\x50\x00\x00", klass=0x20)  # 유선 리모컨


# ── 자동 등록 게이트 ─────────────────────────────────────────────
def test_wildcard_src_never_registers():
    c = make_client()
    feed(c, status_pkt("20ffff"), times=5)
    assert c._stores == {} and c._unit_to_addr == {}


def test_real_indoor_registers_after_min_sightings():
    c = make_client()
    feed(c, status_pkt("200000"))
    assert c._stores == {}, "첫 관측만으로 등록되면 안 된다"
    feed(c, status_pkt("200000"), times=MIN_SIGHTINGS_TO_REGISTER - 1)
    assert list(c._stores) == ["200000"]
    assert c._unit_to_addr["200000"] == b"\x20\x00\x00"
    assert c._unit_labels["200000"] == "에어컨 1"


def test_status_codeless_packet_does_not_register():
    # 실내기 클래스지만 운전 상태 코드가 없는 C014(설치/진단 알림 등)
    c = make_client()
    feed(c, status_pkt("200001", codes=[(0x8001, b"\x02")]), times=5)
    assert c._stores == {}


def test_non_indoor_class_does_not_register():
    c = make_client()
    feed(c, status_pkt("500000"), times=5)   # 유선 리모컨
    feed(c, status_pkt("620000"), times=5)   # WiFi 킷(브릿지 자신의 에코)
    assert c._stores == {}


def test_ignore_addresses_blocks_registration():
    c = make_client(ignore_addresses=["200002"])
    feed(c, status_pkt("200002"), times=5)
    assert c._stores == {}


# ── 송신 방어선 ─────────────────────────────────────────────────
def test_builder_refuses_wildcard_destination():
    with pytest.raises(ValueError):
        pb.build_set_power(b"\x20\xff\xff", True)


def test_builder_allows_physical_destination():
    assert pb.build_set_power(b"\x20\x00\x00", True)
