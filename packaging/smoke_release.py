"""Exercise the actual Windows executable using only disposable inventory."""

from contextlib import closing, contextmanager
import ctypes
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


def request(base_url, path, *, method="GET", payload=None, expected=200):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    try:
        response = urlopen(Request(base_url + path, data=data, headers=headers, method=method), timeout=5)
    except HTTPError as error:
        response = error
    with response:
        body = response.read()
        if response.status != expected:
            raise RuntimeError(f"{method} {path}: expected {expected}, got {response.status}: {body!r}")
        return json.loads(body) if "application/json" in response.headers.get("Content-Type", "") else body


def send_console_ctrl_c(process_id):
    """Send a real Windows Ctrl+C event only to a disposable test console."""
    console = ctypes.WinDLL("kernel32", use_last_error=True)
    console.FreeConsole()
    if not console.AttachConsole(process_id):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        # The helper shares the test console, so protect it from its own event.
        if not console.SetConsoleCtrlHandler(None, True):
            raise ctypes.WinError(ctypes.get_last_error())
        if not console.GenerateConsoleCtrlEvent(0, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        time.sleep(0.2)
    finally:
        console.FreeConsole()


@contextmanager
def running(executable, port, working_directory, environment, log_path, *, force_stop=False, launch_args=()):
    with log_path.open("wb") as output:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        process = subprocess.Popen(
            [str(executable), *launch_args, "--no-browser", "--port", str(port)],
            cwd=working_directory, env=environment,
            stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup,
        )
        try:
            url = f"http://127.0.0.1:{port}"
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError(f"Packaged application exited:\n{log_path.read_text(errors='replace')}")
                try:
                    if request(url, "/api/health")["app"] == "Windowstock":
                        break
                except (OSError, URLError):
                    time.sleep(0.1)
            else:
                raise RuntimeError(f"Packaged application never became ready:\n{log_path.read_text(errors='replace')}")
            yield url
        finally:
            if process.poll() is None:
                try:
                    if force_stop:
                        process.terminate()
                    else:
                        # A separate helper attaches to our test-only console,
                        # leaving the build runner's own console unaffected.
                        signal_result = subprocess.run(
                            [sys.executable, str(Path(__file__).resolve()), "--send-ctrl-c", str(process.pid)],
                            capture_output=True, text=True, timeout=5,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                        if signal_result.returncode != 0:
                            raise RuntimeError(f"Could not signal the test console: {signal_result.stderr}")
                    process.wait(timeout=10)
                    if not force_stop:
                        shutdown_log = log_path.read_text(errors="replace")
                        if process.returncode != 0 or "Traceback" in shutdown_log or "Application shutdown complete" not in shutdown_log:
                            raise RuntimeError(f"Ctrl+C did not stop the server cleanly ({process.returncode}):\n{shutdown_log}")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10)


def main():
    bundle = Path(sys.argv[1]).resolve()
    work_root = Path(__file__).resolve().parents[1] / "release" / "work"
    if bundle.parent != work_root / "dist":
        raise RuntimeError("Smoke-test bundle must be staged under release/work/dist.")
    if not (bundle / "Windowstock.exe").is_file():
        raise RuntimeError("No packaged executable to validate.")

    # All temporary copies, databases, and logs live under generated build work.
    with tempfile.TemporaryDirectory(prefix="smoke-", dir=work_root) as temporary:
        temporary_root = Path(temporary)
        extracted = temporary_root / "Extracted demo with spaces" / "Windowstock"
        shutil.copytree(bundle, extracted)
        launch_directory = temporary_root / "Unrelated working directory"
        launch_directory.mkdir()
        sentinel = launch_directory / "development.sqlite3"
        sentinel_content = b"The release must never read or overwrite this development database."
        sentinel.write_bytes(sentinel_content)
        environment = dict(os.environ)
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            environment.pop(key, None)
        windows_directory = Path(environment.get("SystemRoot", r"C:\Windows"))
        environment["PATH"] = os.pathsep.join([str(windows_directory / "System32"), str(windows_directory)])
        environment["INVENTORY_DB_PATH"] = str(sentinel)
        with socket.socket() as free_port:
            free_port.bind(("127.0.0.1", 0))
            port = free_port.getsockname()[1]
        executable = extracted / "Windowstock.exe"
        database = extracted / "data" / "inventory.sqlite3"
        log_path = temporary_root / "application.log"

        with running(executable, port, launch_directory, environment, log_path, force_stop=True) as url:
            assert request(url, "/api/products") == [], "Release did not start empty"
            assert database.is_file(), "Database was not created beside the executable"
            assert b"Windowstock" in request(url, "/"), "Bundled main page is unavailable"
            assert b"prepareLabels" in request(url, "/static/print.js"), "Bundled print script is unavailable"
            assert request(url, "/static/app.js"), "Bundled application script is unavailable"
            assert request(url, "/static/styles.css"), "Bundled styles are unavailable"
            product = request(url, "/api/products", method="POST", payload={"name": "Portable QA curtain"}, expected=201)
            barcode = product["barcode"]
            receipt = {"barcode": barcode, "kind": "receipt", "quantity": 3, "request_id": str(uuid4())}
            request(url, "/api/stock", method="POST", payload=receipt)
            sale = {"barcode": barcode, "kind": "sale", "quantity": 1, "request_id": str(uuid4())}
            request(url, "/api/stock", method="POST", payload=sale)
            error = request(url, "/api/stock", method="POST", payload={
                "barcode": barcode, "kind": "sale", "quantity": 3, "request_id": str(uuid4()),
            }, expected=409)
            assert error["detail"] == "Not enough in stock."
            assert request(url, f"/api/products/{product['id']}")["quantity"] == 2
            assert len(request(url, "/api/movements")) == 2, "Rejected sale changed movement history"
            relaunched = subprocess.run(
                [str(executable), "--no-browser", "--port", str(port)],
                cwd=launch_directory, env=environment,
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            assert relaunched.returncode == 0 and "already running" in relaunched.stdout, relaunched.stdout + relaunched.stderr
            assert request(url, f"/api/products/{product['id']}")["quantity"] == 2
            different_database = temporary_root / "other-inventory.sqlite3"
            mismatched = subprocess.run(
                [str(executable), "--no-browser", "--port", str(port), "--database", str(different_database)],
                cwd=launch_directory, env=environment,
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            assert mismatched.returncode == 1 and "already running" not in mismatched.stdout
            assert not different_database.exists(), "Relaunch opened an unrelated inventory"
            assert b"<svg" in request(url, f"/api/products/{product['id']}/barcode.svg")
            assert b"label-sheet" in request(url, "/print?product_id=1&copies=2&width=70&height=40")
            backup_path = temporary_root / "backup.sqlite3"
            backup_path.write_bytes(request(url, "/api/backup"))
            with closing(sqlite3.connect(backup_path)) as backup:
                assert backup.execute("SELECT quantity FROM products").fetchone() == (2,)
            assert sentinel.read_bytes() == sentinel_content, "Release touched development database"

        with running(executable, port, launch_directory, environment, log_path) as url:
            assert request(url, f"/api/products/{product['id']}")["quantity"] == 2, "Inventory did not persist"
            request(url, "/api/stock", method="POST", payload=receipt)
            assert request(url, f"/api/products/{product['id']}")["quantity"] == 2, "Receipt retry counted twice"
            assert len(request(url, "/api/movements")) == 2
        assert sentinel.read_bytes() == sentinel_content
        assert not (bundle / "data").exists(), "Smoke test polluted deliverable"
        print("Packaged executable verified: separate DB, assets, stock, barcode, backup, restart/retry, matching relaunch, database isolation, clean Windows Ctrl+C.")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--send-ctrl-c":
        send_console_ctrl_c(int(sys.argv[2]))
    else:
        main()
