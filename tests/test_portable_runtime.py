"""A packaged demo must keep its resources and stock separate from development."""

from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

from inventory.main import create_app


def pretend_frozen(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    package = tmp_path / "Extracted demo"
    bundle = package / "_internal"
    (bundle / "web").mkdir(parents=True)
    executable = package / "Windowstock.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    return package, bundle


def test_frozen_demo_uses_bundled_frontend_and_its_own_persistent_database(monkeypatch, tmp_path):
    package, bundle = pretend_frozen(monkeypatch, tmp_path)
    (bundle / "web" / "index.html").write_text("<h1>Portable inventory</h1>", encoding="utf-8")
    (bundle / "web" / "print.html").write_text("<h1>Portable labels</h1>", encoding="utf-8")
    (bundle / "web" / "app.js").write_text("// portable script", encoding="utf-8")
    development_database = tmp_path / "development.sqlite3"
    development_database.write_bytes(b"Do not open or replace the development database")
    monkeypatch.setenv("INVENTORY_DB_PATH", str(development_database))
    monkeypatch.chdir(tmp_path)

    application = create_app()
    expected_database = package / "data" / "inventory.sqlite3"
    assert application.state.db_path == expected_database.resolve()
    with TestClient(application, base_url="http://127.0.0.1") as client:
        assert client.get("/api/products").json() == []
        assert client.get("/").text == "<h1>Portable inventory</h1>"
        assert client.get("/print").text == "<h1>Portable labels</h1>"
        assert client.get("/static/app.js").text == "// portable script"
        created = client.post("/api/products", json={"name": "Demo curtain"})
        assert created.status_code == 201, created.text

    with TestClient(create_app(), base_url="http://127.0.0.1") as restarted:
        assert restarted.get("/api/products").json() == [created.json()]
    assert expected_database.is_file()
    assert not (bundle / "data").exists()
    assert development_database.read_bytes() == b"Do not open or replace the development database"


def test_explicit_database_is_available_for_isolated_packaged_validation(monkeypatch, tmp_path):
    package, _bundle = pretend_frozen(monkeypatch, tmp_path)
    validation_database = tmp_path / "validation.sqlite3"
    application = create_app(validation_database)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").status_code == 200
        assert application.state.db_path == validation_database.resolve()
    assert validation_database.is_file()
    assert not (package / "data").exists()


def test_source_database_default_and_environment_override_remain_supported(monkeypatch, tmp_path):
    from inventory import paths

    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("INVENTORY_DB_PATH", raising=False)
    assert paths.default_database_path().resolve() == (
        Path(__file__).resolve().parents[1] / "data" / "inventory.sqlite3"
    )
    database = tmp_path / "configured.sqlite3"
    monkeypatch.setenv("INVENTORY_DB_PATH", str(database))
    application = create_app()
    with TestClient(application, base_url="http://127.0.0.1") as client:
        assert application.state.db_path == database.resolve()
        assert client.get("/api/products").json() == []


@pytest.mark.parametrize("arguments, expected_port", [([], 8767), (["--port", "8765"], 8765)])
def test_occupied_port_cannot_open_a_development_window_in_frozen_mode(
    monkeypatch, tmp_path, capsys, arguments, expected_port
):
    import run

    pretend_frozen(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["Windowstock.exe", *arguments])
    attempted_ports = []

    def occupied_port(port):
        attempted_ports.append(port)
        raise OSError("A development server already owns this port")

    def unexpected_call(*_args, **_kwargs):
        pytest.fail("A packaged launcher must not reuse or open an occupied server")

    monkeypatch.setattr(run, "bind_server_socket", occupied_port)
    monkeypatch.setattr(run, "read_health", unexpected_call)
    monkeypatch.setattr(run.webbrowser, "open", unexpected_call)
    monkeypatch.setattr(run.uvicorn, "Server", unexpected_call)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as stopped:
        run.main()
    assert stopped.value.code == 1
    assert attempted_ports == [expected_port]
    error = capsys.readouterr().err
    assert str(expected_port) in error
    assert "choose another port" in error
