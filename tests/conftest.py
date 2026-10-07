from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inventory.main import create_app


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "inventory.sqlite3"


@pytest.fixture
def client(db_path: Path):
    with TestClient(create_app(db_path), base_url="http://127.0.0.1") as test_client:
        yield test_client
