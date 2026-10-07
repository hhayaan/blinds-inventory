"""Record build/runtime versions without exposing development paths or data."""

from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys


if __name__ == "__main__":
    destination = Path(sys.argv[1])
    information = {
        "application": "Windowstock",
        "version": "0.1.0",
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": "Windows x64",
        "python": platform.python_version(),
        "dependencies": {
            name: version(name)
            for name in ("fastapi", "uvicorn", "SQLAlchemy", "python-barcode", "pyinstaller")
        },
        "database": "data/inventory.sqlite3 beside Windowstock.exe; created on first launch",
        "initial_inventory": "empty",
    }
    (destination / "BUILD INFO.json").write_text(json.dumps(information, indent=2) + "\n", encoding="utf-8")
