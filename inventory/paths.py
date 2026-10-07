"""Separate packaged resources from writable inventory data."""

import hashlib
import json
import os
from pathlib import Path
import sys


def is_frozen() -> bool:
    """PyInstaller sets this flag only inside the packaged executable."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Frontend files live in the source tree or the PyInstaller bundle."""
    if is_frozen():
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent.parent


def default_database_path() -> Path:
    """A portable copy owns its data next to its executable."""
    return application_root() / "data" / "inventory.sqlite3"


def application_root() -> Path:
    """Identify an installation independently of its bundled resource location."""
    return Path(sys.executable).resolve().parent if is_frozen() else resource_root()


def resolve_database_path(db_path: str | Path | None = None) -> Path:
    """Select storage once, before either starting or reusing a local server."""
    # A portable demo must ignore inherited development configuration. An
    # explicit factory/CLI path still supports isolated validation databases.
    environment_path = None if is_frozen() else os.environ.get("INVENTORY_DB_PATH")
    selected_path = db_path or environment_path or default_database_path()
    return Path(selected_path).expanduser().resolve()


def launcher_identity(db_path: str | Path) -> str:
    """Opaque identifier for this installation and its selected inventory."""
    paths = [application_root(), Path(db_path).expanduser().resolve()]
    normalized = [os.path.normcase(str(path)) for path in paths]
    payload = json.dumps(normalized, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
