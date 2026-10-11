"""
VsensPython main entry point.

Starts the WebSocket server and, when available, the PySide6 monitor GUI.
Falls back to headless server mode automatically when GUI runtime support is
not available.
"""
import asyncio
import argparse
import importlib
import logging
import os
import sys
import threading
from pathlib import Path

project_root = Path(__file__).parent 
os.chdir(project_root)

from monitor_stats import install_log_handler

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
install_log_handler(logging.DEBUG)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the Vsens Python WebSocket server.")
    parser.add_argument("--gui", action="store_true", help="Force startup with the monitor GUI.")
    parser.add_argument("--headless", action="store_true", help="Start only the WebSocket server.")
    parser.add_argument("--host", default=None, help="WebSocket bind host. Use 0.0.0.0 to accept external connections.")
    parser.add_argument("--port", type=int, help="WebSocket server port. Defaults to the server default.")
    args, _unknown = parser.parse_known_args(argv)
    return args


def _gui_runtime_available() -> bool:
    try:
        importlib.import_module("monitor_gui")
        return True
    except Exception:
        return False


def _should_run_with_gui(args: argparse.Namespace | None = None) -> bool:
    args = args or _parse_args()
    if args.headless:
        return False
    if args.gui:
        return True
    return _gui_runtime_available()


def _run_server(host: str | None = None, port: int | None = None) -> None:
    try:
        from vsens_server import VsensWebSocketServer

        kwargs = {}
        if host is not None:
            kwargs["host"] = host
        if port is not None:
            kwargs["port"] = port
        server = VsensWebSocketServer(**kwargs)
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("[Main] Server stopped by keyboard interrupt.")
    except Exception as exc:
        print(f"[Main] Server error: {exc}")


def _run_gui() -> int:
    from monitor_gui import run_monitor_gui

    return run_monitor_gui()


if __name__ == "__main__":
    args = _parse_args()
    print(f"[Main] Working directory: {os.getcwd()}")

    if _should_run_with_gui(args):
        server_thread = threading.Thread(
            target=_run_server,
            kwargs={"host": args.host, "port": args.port},
            daemon=True,
        )
        server_thread.start()
        exit_code = _run_gui()
        print("[Main] Application closed.")
        sys.exit(exit_code)

    print("[Main] GUI unavailable; starting in headless mode.")
    _run_server(host=args.host, port=args.port)
