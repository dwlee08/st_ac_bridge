"""AC Bridge Server 진입점."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from ac_controller import AcController, MockAcController, RealAcController
from ew11_client import EW11Client
from state_store import StateStore
from tcp_server import TcpServer


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def setup_logging(level_str: str) -> None:
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


async def main() -> None:
    config_path = os.environ.get("CONFIG_PATH", "/app/config.json")
    if not os.path.exists(config_path):
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")

    config = load_config(config_path)

    log_level = os.environ.get("LOG_LEVEL") or config.get("log_level", "INFO")
    setup_logging(log_level)

    logger = logging.getLogger(__name__)

    server_cfg = config.get("server", {})
    host = os.environ.get("SERVER_HOST") or server_cfg.get("host", "0.0.0.0")
    port = int(os.environ.get("SERVER_PORT") or server_cfg.get("port", 8888))

    ctrl_mode = os.environ.get("AC_MODE") or config.get("controller_mode", "real")
    logger.info("AC Bridge Server starting — mode=%s", ctrl_mode)

    stores: dict[str, StateStore] = {}
    unit_addresses: dict[str, bytes] = {}
    unit_labels: dict[str, str] = {}
    controllers: dict[str, AcController] = {}
    ew11_task: asyncio.Task | None = None

    # units가 명시된 경우 사전 등록 (mock 모드 또는 명시적 고정 설정)
    units_cfg = config.get("units", [])
    for unit in units_cfg:
        uid = str(unit["id"])
        addr_bytes = bytes.fromhex(str(unit["address"]))
        stores[uid] = StateStore()
        unit_addresses[uid] = addr_bytes
        unit_labels[uid] = unit.get("label", uid)
        logger.info("unit pre-registered: id=%s address=%s label=%s", uid, unit["address"], unit_labels[uid])

    if ctrl_mode == "mock":
        for uid, store in stores.items():
            controllers[uid] = MockAcController(store)
    else:
        ew11_cfg = config.get("ew11", {})
        ew11_host = os.environ.get("EW11_HOST") or ew11_cfg.get("host")
        ew11_port = int(os.environ.get("EW11_PORT") or ew11_cfg.get("port", 8899))
        if not ew11_host:
            logger.error("EW11 host not configured. Set ew11.host in config.json or EW11_HOST env var.")
            sys.exit(1)
        ew11 = EW11Client(
            host=ew11_host,
            port=ew11_port,
            stores=stores,
            unit_addresses=unit_addresses,
            controllers=controllers,
            unit_labels=unit_labels,
        )
        for uid, store in stores.items():
            controllers[uid] = RealAcController(unit_addresses[uid], store, ew11)
        ew11_task = asyncio.create_task(ew11.receive_loop(), name="ew11-recv")

    server = TcpServer(host=host, port=port, controllers=controllers, unit_labels=unit_labels)
    try:
        await server.serve_forever()
    finally:
        if ew11_task:
            ew11_task.cancel()
            await asyncio.gather(ew11_task, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
