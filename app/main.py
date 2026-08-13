"""AC Bridge Server 진입점."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from ac_controller import AcController, MockAcController, RealAcController
from afterblow import AfterBlowManager
from ew11_client import EW11Client
from icool import IcoolManager
from packet_parser import is_physical_address
from state_store import OutdoorStore, StateStore
from stream import StreamHub
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
    outdoor_store = OutdoorStore()   # 실외기 공용 상태 (전력/에너지/외기온도)
    ew11_task: asyncio.Task | None = None

    # units가 명시된 경우 사전 등록 (mock 모드 또는 명시적 고정 설정)
    units_cfg = config.get("units", [])
    for unit in units_cfg:
        uid = str(unit["id"])
        addr_bytes = bytes.fromhex(str(unit["address"]))
        if not is_physical_address(addr_bytes):
            # 와일드카드 주소(예: 20ffff)는 개별 실내기가 아니라 브로드캐스트다.
            logger.error("unit skipped — not a physical address: id=%s address=%s",
                         uid, unit["address"])
            continue
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
            outdoor_store=outdoor_store,
            ignore_addresses=config.get("ignore_addresses", []),
        )
        for uid, store in stores.items():
            controllers[uid] = RealAcController(unit_addresses[uid], store, ew11)
        ew11_task = asyncio.create_task(ew11.receive_loop(), name="ew11-recv")

    # 인텔리전트 냉방 매니저 + 제어 루프 (상주 프로세스에서 온도 제어/타이머/종료 담당)
    icool = IcoolManager(controllers)
    icool_task = asyncio.create_task(icool.run_loop(), name="icool-loop")

    # 스마트 애프터 블로우 매니저 + 루프 (전원 OFF 시 송풍 건조)
    afterblow = AfterBlowManager(controllers, icool)
    afterblow_task = asyncio.create_task(afterblow.run_loop(), name="afterblow-loop")

    # 이벤트 스트림 허브 (구독자에게 상태 변경 push) + 변경 감지 스윕
    hub = StreamHub(controllers, icool, outdoor_store, afterblow)
    hub_task = asyncio.create_task(hub.run_loop(), name="stream-hub")

    server = TcpServer(
        host=host, port=port, controllers=controllers,
        unit_labels=unit_labels, outdoor_store=outdoor_store,
        icool=icool, afterblow=afterblow, hub=hub,
    )
    try:
        await server.serve_forever()
    finally:
        for task in (ew11_task, icool_task, afterblow_task, hub_task):
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
