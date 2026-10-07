"""A packaged demo must keep its resources and stock separate from development."""

from pathlib import Path
import socket
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
def test_occupied_port_cannot_open_an_unidentified_server_in_frozen_mode(
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
        pytest.fail("A packaged launcher must not open an unidentified occupied server")

    monkeypatch.setattr(run, "bind_server_socket", occupied_port)
    monkeypatch.setattr(run, "read_health", lambda _url: {"app": "Windowstock"})
    expire_reuse_wait(monkeypatch, run)
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


def expire_reuse_wait(monkeypatch, launcher):
    """Bound mismatch polling without sleeping during a launcher unit test."""
    from itertools import count

    monkeypatch.setattr(launcher.time, "monotonic", count(step=3).__next__)
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)


def app_health(database=None):
    """Use the real app's advertised identity rather than inventing health data."""
    with TestClient(create_app(database), base_url="http://127.0.0.1") as client:
        response = client.get("/api/health")
        assert response.status_code == 200, response.text
        return response.json()


def forbid_new_server(monkeypatch, launcher, health):
    def occupied_port(_port):
        raise OSError("Address already in use")

    def unexpected_call(*_args, **_kwargs):
        pytest.fail("Relaunching an occupied port must not create an app or second server")

    monkeypatch.setattr(launcher, "bind_server_socket", occupied_port)
    monkeypatch.setattr(launcher, "read_health", lambda _url: health)
    monkeypatch.setattr(launcher, "create_app", unexpected_call)
    monkeypatch.setattr(launcher.uvicorn, "Server", unexpected_call)


@pytest.mark.parametrize("frozen", [False, True], ids=["development", "portable"])
@pytest.mark.parametrize("no_browser", [False, True], ids=["reopen-browser", "headless"])
def test_relaunch_opens_only_the_same_inventory_instance(
    monkeypatch, tmp_path, capsys, frozen, no_browser
):
    import run

    if frozen:
        package, _bundle = pretend_frozen(monkeypatch, tmp_path)
        database = package / "data" / "inventory.sqlite3"
        arguments = []
        port = 8767
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
        database = tmp_path / "development.sqlite3"
        monkeypatch.setenv("INVENTORY_DB_PATH", str(database))
        arguments = []
        port = 8765

    health = app_health()
    saved_database = database.read_bytes()
    forbid_new_server(monkeypatch, run, health)
    opened = []
    monkeypatch.setattr(run.webbrowser, "open", opened.append)
    monkeypatch.setattr(sys, "argv", ["Windowstock", *arguments, *(["--no-browser"] if no_browser else [])])
    monkeypatch.chdir(tmp_path)

    assert run.main() is None

    assert opened == ([] if no_browser else [f"http://127.0.0.1:{port}"])
    assert database.read_bytes() == saved_database
    output = capsys.readouterr()
    assert "already running" in output.out
    assert output.err == ""


@pytest.mark.parametrize("frozen", [False, True], ids=["development", "portable"])
def test_relaunch_reuses_matching_explicit_database(monkeypatch, tmp_path, frozen):
    import run

    if frozen:
        pretend_frozen(monkeypatch, tmp_path)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
    database = tmp_path / "isolated demo.sqlite3"
    health = app_health(database)
    forbid_new_server(monkeypatch, run, health)
    opened = []
    monkeypatch.setattr(run.webbrowser, "open", opened.append)
    monkeypatch.setattr(sys, "argv", ["Windowstock", "--port", "12345", "--database", str(database)])

    assert run.main() is None
    assert opened == ["http://127.0.0.1:12345"]


def test_relaunch_does_not_open_a_different_development_database(monkeypatch, tmp_path):
    import run

    monkeypatch.delattr(sys, "frozen", raising=False)
    health = app_health(tmp_path / "original.sqlite3")
    requested_database = tmp_path / "other.sqlite3"
    monkeypatch.setenv("INVENTORY_DB_PATH", str(requested_database))
    forbid_new_server(monkeypatch, run, health)
    expire_reuse_wait(monkeypatch, run)
    opened = []
    monkeypatch.setattr(run.webbrowser, "open", opened.append)
    monkeypatch.setattr(sys, "argv", ["Windowstock", "--no-browser"])

    with pytest.raises(SystemExit) as stopped:
        run.main()

    assert stopped.value.code == 1
    assert opened == []
    assert not requested_database.exists()


@pytest.mark.parametrize("other_instance", ["development", "other-portable-copy"])
def test_portable_relaunch_refuses_another_installation_even_with_same_database(
    monkeypatch, tmp_path, other_instance
):
    import run

    database = tmp_path / "shared-by-explicit-cli.sqlite3"
    if other_instance == "development":
        monkeypatch.delattr(sys, "frozen", raising=False)
    else:
        pretend_frozen(monkeypatch, tmp_path / "other copy")
    health = app_health(database)
    saved_database = database.read_bytes()
    pretend_frozen(monkeypatch, tmp_path / "requested copy")
    forbid_new_server(monkeypatch, run, health)
    expire_reuse_wait(monkeypatch, run)
    opened = []
    monkeypatch.setattr(run.webbrowser, "open", opened.append)
    monkeypatch.setattr(sys, "argv", ["Windowstock.exe", "--database", str(database), "--no-browser"])

    with pytest.raises(SystemExit) as stopped:
        run.main()

    assert stopped.value.code == 1
    assert opened == []
    assert database.read_bytes() == saved_database


@pytest.mark.parametrize(
    "health_change",
    [None, {}, {"launcher_id": None}, {"status": "starting"}, {"app": "Other application"}],
    ids=["unreachable", "unknown-response", "missing-identity", "not-ready", "other-app"],
)
def test_relaunch_requires_a_ready_identified_windowstock_server(
    monkeypatch, tmp_path, health_change
):
    import run

    monkeypatch.delattr(sys, "frozen", raising=False)
    database = tmp_path / "inventory.sqlite3"
    monkeypatch.setenv("INVENTORY_DB_PATH", str(database))
    real_health = app_health()
    health = None if health_change is None else ({} if not health_change else real_health | health_change)
    forbid_new_server(monkeypatch, run, health)
    expire_reuse_wait(monkeypatch, run)
    opened = []
    monkeypatch.setattr(run.webbrowser, "open", opened.append)
    monkeypatch.setattr(sys, "argv", ["Windowstock", "--no-browser"])

    with pytest.raises(SystemExit) as stopped:
        run.main()

    assert stopped.value.code == 1
    assert opened == []


def test_relaunch_waits_for_matching_instance_to_finish_starting(monkeypatch, tmp_path):
    import run

    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("INVENTORY_DB_PATH", str(tmp_path / "inventory.sqlite3"))
    health = app_health()
    forbid_new_server(monkeypatch, run, health)
    responses = iter([None, health])
    monkeypatch.setattr(run, "read_health", lambda _url: next(responses))
    monkeypatch.setattr(run.time, "sleep", lambda _seconds: None)
    opened = []
    monkeypatch.setattr(run.webbrowser, "open", opened.append)
    monkeypatch.setattr(sys, "argv", ["Windowstock"])

    assert run.main() is None
    assert opened == ["http://127.0.0.1:8765"]


@pytest.mark.parametrize("frozen", [False, True], ids=["development", "portable"])
def test_ctrl_c_is_a_normal_exit_and_closes_the_listener(monkeypatch, tmp_path, capsys, frozen):
    import run

    if frozen:
        pretend_frozen(monkeypatch, tmp_path)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
    database = tmp_path / "shutdown.sqlite3"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    monkeypatch.setattr(run, "bind_server_socket", lambda _port: listener)
    monkeypatch.setattr(sys, "argv", ["Windowstock", "--port", str(port), "--database", str(database), "--no-browser"])

    class InterruptedServer:
        def __init__(self, _config):
            pass

        def run(self, *, sockets):
            assert sockets == [listener]
            raise KeyboardInterrupt

    monkeypatch.setattr(run.uvicorn, "Server", InterruptedServer)
    assert run.main() is None
    assert listener.fileno() == -1
    output = capsys.readouterr()
    assert "Traceback" not in output.out + output.err
    assert "could not start" not in output.out + output.err
    assert output.err == ""
