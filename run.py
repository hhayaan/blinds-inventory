"""Launch the local inventory server and open its browser interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

import uvicorn

from inventory.main import create_app
from inventory.paths import default_database_path, is_frozen


def bind_server_socket(port: int) -> socket.socket:
    """Reserve our own listener before any browser can open this address."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(2048)
        listener.setblocking(False)
        return listener
    except OSError:
        listener.close()
        raise


def exit_with_error(message: str, *, no_browser: bool) -> None:
    print(f"\nWindowstock could not start: {message}", file=sys.stderr)
    # A double-clicked console otherwise disappears before the message is read.
    # Headless CLI checks and normal development commands must never wait here.
    if is_frozen() and not no_browser and sys.stdin and sys.stdin.isatty():
        try:
            input("Press Enter to close this window.")
        except (EOFError, KeyboardInterrupt):
            pass
    raise SystemExit(1)


def read_health(url: str) -> dict | None:
    try:
        with urlopen(f"{url}/api/health", timeout=0.5) as response:
            result = json.load(response)
            return result if isinstance(result, dict) else None
    except (OSError, URLError, ValueError):
        return None


def open_when_ready(url: str) -> None:
    for _ in range(100):
        if read_health(url):
            webbrowser.open(url)
            return
        time.sleep(0.1)


def port_number(value: str) -> int:
    result = int(value)
    if not 1 <= result <= 65535:
        raise argparse.ArgumentTypeError("Choose a port between 1 and 65535.")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Windowstock on this PC.")
    parser.add_argument("--port", type=port_number, default=8767 if is_frozen() else 8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--database", type=Path, help="Optional SQLite path for an isolated demo.")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}"

    if not is_frozen():
        with socket.socket() as probe:
            in_use = probe.connect_ex(("127.0.0.1", args.port)) == 0
        if in_use:
            health = read_health(url)
            if health and health.get("app") == "Windowstock" and not args.database:
                print(f"Windowstock is already running at {url}")
                if not args.no_browser:
                    webbrowser.open(url)
                return

    try:
        listener = bind_server_socket(args.port)
    except OSError as error:
        exit_with_error(
            f"Cannot listen on port {args.port}. It may already be in use. "
            f"Close the other instance or choose another port with --port. ({error})",
            no_browser=args.no_browser,
        )

    with listener:
        try:
            application = create_app(args.database)
            print(
                f"Windowstock: {url}\n"
                f"Inventory database: {application.state.db_path}\n"
                "Keep this window open. Press Ctrl+C to stop the application."
            )
            config = uvicorn.Config(
                application, host="127.0.0.1", port=args.port,
                log_level="info", access_log=False,
                loop="asyncio", http="h11", ws="none", lifespan="on",
            )
            if not args.no_browser:
                threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
            uvicorn.Server(config).run(sockets=[listener])
        except Exception as error:
            database = args.database or default_database_path()
            exit_with_error(
                f"{error}\nCheck that the application folder is writable. "
                f"Database: {database}",
                no_browser=args.no_browser,
            )


if __name__ == "__main__":
    main()
