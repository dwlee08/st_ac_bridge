"""테스트 공용 헬퍼."""
from packet_parser import extract_packets


def packet_items(pkt: bytes) -> list[tuple[int, bytes]]:
    """빌드된 C013 패킷 → (code, value) 목록. seq는 비교에서 제외된다."""
    packets, rest = extract_packets(bytearray(pkt))
    assert len(packets) == 1 and not rest, f"invalid packet: {pkt.hex()}"
    return packets[0].codes


class FakeEW11:
    """RealAcController용 전송 스파이 — 보낸 패킷만 기록."""

    def __init__(self):
        self.sent: list[bytes] = []

    async def send_with_ack(self, pkt: bytes, **kw) -> bool:
        self.sent.append(pkt)
        return True

    async def send(self, pkt: bytes) -> None:
        self.sent.append(pkt)
