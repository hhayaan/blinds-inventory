"""HTTP app for a single-PC inventory service and its browser interface."""

import os
import sqlite3
import tempfile
from contextlib import asynccontextmanager, closing
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

from barcode import Code128
from barcode.writer import SVGWriter
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.background import BackgroundTask

from .database import open_database, utc_now
from .paths import launcher_identity, resolve_database_path, resource_root
from .schemas import ArchiveRequest, ProductCreate, ProductPatch, StockRequest
from .service import InventoryService


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def create_app(db_path: str | Path | None = None) -> FastAPI:
    database_path = resolve_database_path(db_path)
    instance_id = launcher_identity(database_path)
    engine = open_database(database_path)
    inventory = InventoryService(engine)

    @asynccontextmanager
    async def lifespan(_application):
        yield
        engine.dispose()

    application = FastAPI(title="Window inventory", version="0.1.0", lifespan=lifespan)
    application.state.db_path = database_path
    application.state.engine = engine

    @application.middleware("http")
    async def local_access_only(request: Request, call_next):
        # A local skeleton has no accounts. Reject non-loopback Host headers and
        # foreign browser origins rather than exposing its writes to other sites.
        try:
            host_url = urlsplit("http://" + request.headers.get("host", ""))
            hostname = host_url.hostname
            port = host_url.port or (443 if request.url.scheme == "https" else 80)
        except ValueError:
            return JSONResponse({"detail": "Invalid local host"}, status_code=403)
        if (
            hostname not in LOOPBACK_HOSTS
            or host_url.username
            or host_url.password
            or host_url.path
            or host_url.query
            or host_url.fragment
        ):
            return JSONResponse({"detail": "This version only accepts local PC requests"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin:
                try:
                    origin_url = urlsplit(origin)
                    origin_port = origin_url.port or (443 if origin_url.scheme == "https" else 80)
                    matches = (
                        origin_url.scheme == request.url.scheme
                        and origin_url.hostname == hostname
                        and origin_port == port
                        and not origin_url.username
                        and not origin_url.password
                    )
                except ValueError:
                    matches = False
                if not matches:
                    return JSONResponse({"detail": "Inventory changes must come from this application's own window"}, status_code=403)
            if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                return JSONResponse({"detail": "Inventory changes require JSON"}, status_code=415)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(OperationalError)
    async def database_unavailable(_request, _error):
        return JSONResponse({"detail": "The inventory database is busy or unavailable. Please retry."}, status_code=503)

    @application.exception_handler(IntegrityError)
    async def database_conflict(_request, _error):
        return JSONResponse({"detail": "The change conflicts with an existing inventory record."}, status_code=409)

    @application.get("/api/health")
    def health():
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {
            "app": "Windowstock", "status": "ok", "version": "0.1.0",
            "storage": "sqlite", "launcher_id": instance_id,
        }

    @application.get("/api/products")
    def products(include_archived: bool = False):
        return inventory.list_products(include_archived)

    @application.post("/api/products", status_code=201)
    def create_product(fields: ProductCreate):
        return inventory.create_product(fields)

    @application.get("/api/products/{product_id}")
    def get_product(product_id: int):
        return inventory.get_product(product_id)

    @application.patch("/api/products/{product_id}")
    def update_product(product_id: int, change: ProductPatch):
        return inventory.patch_product(product_id, change)

    @application.post("/api/products/{product_id}/archive")
    def archive_product(product_id: int, change: ArchiveRequest):
        return inventory.archive_product(product_id, change)

    @application.post("/api/stock")
    def stock(request: StockRequest):
        return inventory.apply_stock(request)

    @application.get("/api/movements")
    def movements(product_id: int | None = Query(default=None, ge=1)):
        return inventory.list_movements(product_id)

    @application.get("/api/products/{product_id}/barcode.svg")
    def barcode_svg(product_id: int):
        product = inventory.get_product(product_id)
        output = BytesIO()
        Code128(product["barcode"], writer=SVGWriter()).write(output, {
            "module_width": 0.3,
            "module_height": 15,
            "quiet_zone": 6.5,
            "font_size": 10,
            "text_distance": 3,
        })
        return Response(output.getvalue(), media_type="image/svg+xml")

    @application.get("/api/backup")
    def backup():
        # Copy via SQLite's supported backup API, not a filesystem copy: committed
        # changes may still live in the WAL while the application is running.
        descriptor, temporary_path = tempfile.mkstemp(prefix="inventory-backup-", suffix=".sqlite3")
        os.close(descriptor)
        try:
            with closing(sqlite3.connect(database_path)) as source, closing(sqlite3.connect(temporary_path)) as destination:
                source.backup(destination)
        except sqlite3.Error as error:
            Path(temporary_path).unlink(missing_ok=True)
            raise HTTPException(503, "Could not create the database backup. Please retry.") from error
        filename = "inventory-backup-" + utc_now().replace(":", "").replace(".", "-") + ".sqlite3"
        return FileResponse(
            temporary_path,
            media_type="application/vnd.sqlite3",
            filename=filename,
            background=BackgroundTask(Path(temporary_path).unlink, missing_ok=True),
        )

    web_path = resource_root() / "web"
    application.mount("/static", StaticFiles(directory=web_path, check_dir=False), name="static")

    @application.get("/", include_in_schema=False)
    def index():
        index_path = web_path / "index.html"
        if not index_path.is_file():
            raise HTTPException(503, "The inventory frontend is not available yet")
        return FileResponse(index_path, media_type="text/html", headers={"Cache-Control": "no-store"})

    @application.get("/print", include_in_schema=False)
    def print_sheet():
        print_path = web_path / "print.html"
        if not print_path.is_file():
            raise HTTPException(503, "The printable label page is not available yet")
        return FileResponse(print_path, media_type="text/html", headers={"Cache-Control": "no-store"})

    return application
