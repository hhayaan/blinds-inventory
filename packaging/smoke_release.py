"""Exercise the actual Windows executable using only disposable inventory."""

from contextlib import closing, contextmanager
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


@contextmanager
def running(executable, port, working_directory, environment, log_path):
    with log_path.open("wb") as output:
        process = subprocess.Popen(
            [str(executable), "--no-browser", "--port", str(port)],
            cwd=working_directory, env=environment,
            stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
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
                # Hidden automation has no console to send Ctrl+C to. SQLite
                # committed transactions survive this forced-stop/restart check.
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
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

        with running(executable, port, launch_directory, environment, log_path) as url:
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
        print("Packaged executable verified: empty separate DB, bundled pages, receive/sale, oversale, barcode, backup, restart, retry.")


if __name__ == "__main__":
    main()
