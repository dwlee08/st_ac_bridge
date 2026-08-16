"""asyncio 기반 최소 HTTP/1.1 서버 — REST API + SSE 스트림 제공.

이미지에 외부 의존성을 넣지 않기 위해(현재 Dockerfile은 pip 설치가 없다)
표준 라이브러리만으로 필요한 만큼의 HTTP만 구현한다.
지원 범위: 요청라인 + 헤더 + Content-Length 본문, keep-alive, SSE 응답.
지원하지 않음: chunked 요청 본문, HTTPS, 멀티파트.
"""
from __future__ import annotations

import asyncio
import json
import logging
from asyncio import StreamReader, StreamWriter

from rest_api import EVENTS_PATH, Router, err
from stream import SseSubscriber, StreamHub

logger = logging.getLogger(__name__)

MAX_HEADER_LINES = 64
MAX_LINE         = 8192
MAX_BODY         = 64 * 1024
IDLE_TIMEOUT     = 65      # keep-alive 유휴 연결 정리(초)
SSE_KEEPALIVE    = 20      # SSE 주석 핑 주기(초). 죽은 연결 조기 감지 + 중간 장비 타임아웃 방지

_STATUS_TEXT = {
    200: "OK", 400: "Bad Request", 404: "Not Found",
    405: "Method Not Allowed", 408: "Request Timeout",
    413: "Payload Too Large", 500: "Internal Server Error",
    503: "Service Unavailable",
}


class BadRequest(Exception):
    pass


class HttpServer:
    def __init__(
        self,
        host: str,
        port: int,
        router: Router,
        hub: StreamHub | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._router = router
        self._hub = hub
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, host=self._host, port=self._port)
        addrs = [str(s.getsockname()) for s in self._server.sockets]
        logger.info("REST API listening on %s", addrs)

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        async with self._server:
            await self._server.serve_forever()

    # ── 요청 파싱 ───────────────────────────────────────────────
    async def _read_line(self, reader: StreamReader) -> str:
        line = await reader.readline()
        if len(line) > MAX_LINE:
            raise BadRequest("line too long")
        return line.decode("latin-1").rstrip("\r\n")

    async def _read_request(self, reader: StreamReader):
        """(method, path, headers, body dict) 반환. 연결 종료면 None."""
        try:
            start = await asyncio.wait_for(self._read_line(reader), timeout=IDLE_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            return None
        if not start:
            return None

        parts = start.split(" ")
        if len(parts) != 3:
            raise BadRequest(f"malformed request line: {start!r}")
        method, target, _version = parts
        path = target.split("?", 1)[0]          # 쿼리스트링은 쓰지 않는다

        headers: dict[str, str] = {}
        for _ in range(MAX_HEADER_LINES):
            line = await self._read_line(reader)
            if not line:
                break
            name, sep, value = line.partition(":")
            if not sep:
                raise BadRequest(f"malformed header: {line!r}")
            headers[name.strip().lower()] = value.strip()
        else:
            raise BadRequest("too many headers")

        body: dict = {}
        length = int(headers.get("content-length") or 0)
        if length > MAX_BODY:
            raise BadRequest("body too large")
        if length > 0:
            raw = await reader.readexactly(length)
            if raw.strip():
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    raise BadRequest(f"JSON parse error: {e}") from e
                if not isinstance(parsed, dict):
                    raise BadRequest("expected JSON object body")
                body = parsed
        return method.upper(), path, headers, body

    # ── 응답 ────────────────────────────────────────────────────
    @staticmethod
    def _write_json(writer: StreamWriter, status: int, payload: dict, keep_alive: bool) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        head = (
            f"HTTP/1.1 {status} {_STATUS_TEXT.get(status, 'OK')}\r\n"
            "Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(data)}\r\n"
            f"Connection: {'keep-alive' if keep_alive else 'close'}\r\n"
            "\r\n"
        ).encode("latin-1")
        writer.write(head + data)

    async def _handle_client(self, reader: StreamReader, writer: StreamWriter) -> None:
        peer = writer.get_extra_info("peername", default="unknown")
        peer_str = f"{peer[0]}:{peer[1]}" if isinstance(peer, tuple) else str(peer)
        try:
            while True:
                try:
                    request = await self._read_request(reader)
                except BadRequest as e:
                    logger.warning("bad request from %s: %s", peer_str, e)
                    self._write_json(writer, 400, err(str(e)), keep_alive=False)
                    await writer.drain()
                    return
                if request is None:
                    return

                method, path, headers, body = request
                if method == "GET" and path == EVENTS_PATH:
                    await self._serve_events(reader, writer, peer_str)
                    return

                status, payload = await self._router.dispatch(method, path, body)
                keep_alive = headers.get("connection", "").lower() != "close"
                logger.info("%s %s → %d (%s)", method, path, status, peer_str)
                self._write_json(writer, status, payload, keep_alive)
                await writer.drain()
                if not keep_alive:
                    return
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        except Exception:
            logger.exception("HTTP connection error (%s)", peer_str)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # ── SSE ─────────────────────────────────────────────────────
    async def _serve_events(
        self, reader: StreamReader, writer: StreamWriter, peer_str: str,
    ) -> None:
        """이 연결을 이벤트 스트림으로 전환. 허브가 스냅샷 + 변경분을 push한다."""
        if self._hub is None:
            self._write_json(writer, 503, err("stream not available"), keep_alive=False)
            await writer.drain()
            return

        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream; charset=utf-8\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )
        await writer.drain()

        sub = SseSubscriber(writer)
        await self._hub.add_subscriber(sub)
        logger.info("SSE subscriber connected (%s)", peer_str)
        try:
            while True:
                # 클라이언트가 끊으면 EOF. 그때까지는 주기적으로 주석 핑을 보내
                # 죽은 연결을 조기에 감지한다(쓰기 실패 → 예외 → 정리).
                try:
                    chunk = await asyncio.wait_for(reader.read(256), timeout=SSE_KEEPALIVE)
                    if not chunk:
                        break
                except asyncio.TimeoutError:
                    writer.write(b": ping\n\n")
                    await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            await self._hub.remove_subscriber(sub)
            logger.info("SSE subscriber disconnected (%s)", peer_str)
