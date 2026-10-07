"""Separate packaged resources from writable inventory data."""

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
    root = Path(sys.executable).resolve().parent if is_frozen() else resource_root()
    return root / "data" / "inventory.sqlite3"
