"""asyncio 기반 TCP 서버 — Edge Driver 연결 수락."""
from __future__ import annotations

import asyncio
import logging
from asyncio import StreamReader, StreamWriter

from ac_controller import AcController
from session import Session

logger = logging.getLogger(__name__)


class TcpServer:
    def __init__(self, host: str, port: int, controllers: dict[str, AcController]) -> None:
        self._host = host
        self._port = port
        self._controllers = controllers
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self._host,
            port=self._port,
        )
        addrs = [str(s.getsockname()) for s in self._server.sockets]
        logger.info("TCP server listening on %s", addrs)

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        async with self._server:
            await self._server.serve_forever()

    async def _handle_client(self, reader: StreamReader, writer: StreamWriter) -> None:
        peer = writer.get_extra_info("peername", default="unknown")
        peer_str = f"{peer[0]}:{peer[1]}" if isinstance(peer, tuple) else str(peer)
        session = Session(reader, writer, self._controllers, peer_str)
        await session.run()
