"""EW11 TCP 연결, raw bytes 수신 루프, 유닛별 StateStore 업데이트."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import packet_builder as pb
from ac_controller import RealAcController
from packet_parser import MSG_TYPE_ACK, MSG_TYPE_STATUS, ParsedPacket, extract_packets
from state_decoder import decode_codes, decode_outdoor_codes
from state_store import OutdoorStore, StateStore

if TYPE_CHECKING:
    from ac_controller import AcController

logger = logging.getLogger(__name__)

OUTDOOR_SRC        = bytes([0x10, 0x00, 0x00])
INDOOR_SRC_PREFIX  = 0x20   # 실내기 주소 첫 바이트
MAX_BUF            = 8192
RECONNECT_DELAY    = 5
BUS_IDLE_MS        = 100
RECONCILE_INTERVAL = 5


class EW11Client:
    def __init__(
        self,
        host: str,
        port: int,
        stores: dict[str, StateStore],
        unit_addresses: dict[str, bytes],
        controllers: dict[str, AcController] | None = None,
        unit_labels: dict[str, str] | None = None,
        outdoor_store: OutdoorStore | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._stores = stores
        self._outdoor_store = outdoor_store
        self._addr_to_unit: dict[bytes, str] = {v: k for k, v in unit_addresses.items()}
        self._unit_to_addr: dict[str, bytes] = dict(unit_addresses)
        self._controllers = controllers
        self._unit_labels = unit_labels
        self._writer: asyncio.StreamWriter | None = None
        self._buf = bytearray()
        self._last_rx_time: float = 0.0
        self._send_lock = asyncio.Lock()
        self._ack_event = asyncio.Event()

    @property
    def is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def _wait_bus_idle(self) -> None:
        """마지막 RX 이후 BUS_IDLE_MS 만큼 버스가 조용할 때까지 대기."""
        while True:
            idle = asyncio.get_event_loop().time() - self._last_rx_time
            remaining = BUS_IDLE_MS / 1000 - idle
            if remaining <= 0:
                return
            await asyncio.sleep(remaining)

    async def send(self, data: bytes) -> None:
        if not self.is_connected:
            raise RuntimeError("EW11 not connected")

        async with self._send_lock:
            await self._wait_bus_idle()
            self._writer.write(data)
            await self._writer.drain()
            logger.info("EW11 TX: %s", data.hex())

    async def send_with_ack(
        self, data: bytes, timeout: float = 1.0, max_retries: int = 3
    ) -> bool:
        """전송 후 C016 ACK를 받을 때까지 재시도. 전원 명령 전용."""
        if not self.is_connected:
            raise RuntimeError("EW11 not connected")

        async with self._send_lock:
            for attempt in range(1, max_retries + 1):
                self._ack_event.clear()
                await self._wait_bus_idle()
                self._writer.write(data)
                await self._writer.drain()
                logger.info("EW11 TX power (attempt=%d/%d): %s", attempt, max_retries, data.hex())
                try:
                    await asyncio.wait_for(self._ack_event.wait(), timeout=timeout)
                    logger.info("EW11 C016 ACK received (attempt=%d)", attempt)
                    return True
                except asyncio.TimeoutError:
                    logger.warning("EW11 no C016 ACK (attempt=%d/%d)", attempt, max_retries)

        logger.error("EW11 send_with_ack: no ACK after %d attempts", max_retries)
        return False

    async def _periodic_reconcile_loop(self) -> None:
        while True:
            await asyncio.sleep(RECONCILE_INTERVAL)
            if not self.is_connected:
                continue
            for unit_id, store in list(self._stores.items()):
                try:
                    current = await store.get()
                    if not current.power:
                        continue
                    diffs = await store.pending_diffs()
                    if diffs:
                        dst = self._unit_to_addr[unit_id]
                        logger.info("periodic reconcile unit=%s diffs=%s", unit_id, diffs)
                        asyncio.create_task(self._reconcile(dst, diffs))
                except Exception as e:
                    logger.error("periodic reconcile error unit=%s: %s", unit_id, e)

    async def receive_loop(self) -> None:
        asyncio.create_task(self._periodic_reconcile_loop())
        while True:
            try:
                await self._run_connection()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("EW11 error: %s — reconnecting in %ds", e, RECONNECT_DELAY)
                await asyncio.sleep(RECONNECT_DELAY)

    async def _run_connection(self) -> None:
        reader, writer = await asyncio.open_connection(self._host, self._port)
        self._writer = writer
        self._buf.clear()
        logger.info("EW11 connected: %s:%d", self._host, self._port)
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    raise ConnectionResetError("EW11 closed connection")

                self._last_rx_time = asyncio.get_event_loop().time()
                self._buf.extend(chunk)

                if len(self._buf) > MAX_BUF:
                    logger.warning("buffer overflow, resetting")
                    self._buf.clear()
                    continue

                packets, self._buf = extract_packets(self._buf)
                for pkt in packets:
                    await self._handle_packet(pkt)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            logger.info("EW11 connection closed")

    async def _reconcile(self, dst: bytes, diffs: dict) -> None:
        await asyncio.sleep(0.3)
        if not self.is_connected:
            return
        pkt = pb.build_reconcile(dst, diffs)
        if pkt:
            logger.info("EW11 reconcile TX: %s", pkt.hex())
            await self.send(pkt)

    def _auto_register(self, addr: bytes) -> str:
        n = len(self._stores) + 1
        unit_id = addr.hex()
        label = f"에어컨 {n}"
        store = StateStore()
        self._stores[unit_id] = store
        self._addr_to_unit[addr] = unit_id
        self._unit_to_addr[unit_id] = addr
        if self._unit_labels is not None:
            self._unit_labels[unit_id] = label
        if self._controllers is not None:
            self._controllers[unit_id] = RealAcController(addr, store, self)
        logger.info("auto-registered unit: id=%s addr=%s label=%s", unit_id, addr.hex(), label)
        return unit_id

    async def _handle_packet(self, pkt: ParsedPacket) -> None:
        if pkt.src == OUTDOOR_SRC:
            # 실외기는 C014 브로드캐스트로 전력/에너지/외기온도 등을 전송.
            if pkt.msg_type == MSG_TYPE_STATUS and self._outdoor_store is not None:
                updates = decode_outdoor_codes(pkt.codes)
                if updates:
                    await self._outdoor_store.update(**updates)
                    logger.info("EW11 RX C014 outdoor: %s", updates)
            return
        if pkt.msg_type == MSG_TYPE_ACK:
            self._ack_event.set()
            return
        if pkt.msg_type != MSG_TYPE_STATUS:
            return

        unit_id = self._addr_to_unit.get(pkt.src)
        if unit_id is None:
            if pkt.src[0] == INDOOR_SRC_PREFIX:
                unit_id = self._auto_register(pkt.src)
            else:
                logger.debug("unknown src: %s", pkt.src.hex())
                return
        logger.info("EW11 RX C014: unit=%s codes=%s", unit_id, [(hex(c), v.hex()) for c, v in pkt.codes])

        store = self._stores.get(unit_id)
        if store is None:
            return

        updates = decode_codes(pkt.codes)
        if updates:
            diffs = await store.update(**updates)
            logger.debug("unit=%s updated: %s", unit_id, updates)
            if diffs:
                current = await store.get()
                if current.power:
                    logger.info("unit=%s state mismatch, reconciling: %s", unit_id, diffs)
                    dst = self._unit_to_addr[unit_id]
                    asyncio.create_task(self._reconcile(dst, diffs))
