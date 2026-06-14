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
    host = server_cfg.get("host", "0.0.0.0")
    port = int(server_cfg.get("port", 8888))

    units_cfg = config.get("units", [])
    if not units_cfg:
        logger.error("config.json에 units 목록이 없습니다.")
        sys.exit(1)

    ctrl_mode = os.environ.get("AC_MODE") or config.get("controller_mode", "real")
    logger.info("AC Bridge Server starting — mode=%s", ctrl_mode)

    # 유닛별 StateStore 및 주소 파싱
    stores: dict[str, StateStore] = {}
    unit_addresses: dict[str, bytes] = {}
    unit_labels: dict[str, str] = {}
    for unit in units_cfg:
        uid = str(unit["id"])
        addr_bytes = bytes.fromhex(str(unit["address"]))
        stores[uid] = StateStore()
        unit_addresses[uid] = addr_bytes
        unit_labels[uid] = unit.get("label", uid)
        logger.info("unit registered: id=%s address=%s label=%s", uid, unit["address"], unit_labels[uid])

    controllers: dict[str, AcController] = {}
    ew11_task: asyncio.Task | None = None

    if ctrl_mode == "mock":
        for uid, store in stores.items():
            controllers[uid] = MockAcController(store)
    else:
        ew11_cfg = config.get("ew11", {})
        ew11 = EW11Client(
            host=ew11_cfg["host"],
            port=int(ew11_cfg["port"]),
            stores=stores,
            unit_addresses=unit_addresses,
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
