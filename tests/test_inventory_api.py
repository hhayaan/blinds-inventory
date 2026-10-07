import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier
from uuid import uuid4
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from inventory.main import create_app


def create_product(client: TestClient, **fields) -> dict:
    response = client.post(
        "/api/products",
        json={"name": "White roller blind", "category": "Blinds", **fields},
    )
    assert response.status_code == 201, response.text
    return response.json()


def stock(client: TestClient, barcode: str, kind: str, **fields):
    return client.post(
        "/api/stock",
        json={"barcode": barcode, "kind": kind, "request_id": str(uuid4()), **fields},
    )


def accepted_stock(client: TestClient, barcode: str, kind: str, **fields) -> dict:
    response = stock(client, barcode, kind, **fields)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["replayed"] is False
    return result


def product_state(client: TestClient, product_id: int) -> dict:
    response = client.get(f"/api/products/{product_id}")
    assert response.status_code == 200, response.text
    return response.json()


def history(client: TestClient, product_id: int | None = None) -> list[dict]:
    params = {} if product_id is None else {"product_id": product_id}
    response = client.get("/api/movements", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def assert_error(response, status_code: int):
    assert response.status_code == status_code, response.text
    assert response.json()["detail"]


def test_empty_inventory_health_and_creation(client):
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    assert client.get("/api/products").json() == []

    first = create_product(client)
    second = create_product(client, name="Blue curtain")

    assert first["quantity"] == second["quantity"] == 0
    assert first["revision"] >= 1
    assert first["id"] != second["id"]
    assert first["barcode"] and first["barcode"] != second["barcode"]
    assert history(client) == []
    assert {row["id"] for row in client.get("/api/products").json()} == {
        first["id"], second["id"]
    }


def test_receipts_sales_returns_and_history_balance(client):
    product = create_product(client)
    barcode = product["barcode"]
    received = [accepted_stock(client, barcode, "receipt") for _ in range(3)]
    assert [result["product"]["quantity"] for result in received] == [1, 2, 3]

    sold = accepted_stock(client, barcode, "sale")
    returned = accepted_stock(client, barcode, "return", reason="Customer return")
    assert sold["product"]["quantity"] == 2
    assert returned["product"]["quantity"] == 3
    for _ in range(3):
        accepted_stock(client, barcode, "sale")

    before_product = product_state(client, product["id"])
    before_movements = history(client, product["id"])
    assert_error(stock(client, barcode, "sale"), 409)
    assert product_state(client, product["id"]) == before_product
    assert history(client, product["id"]) == before_movements
    assert before_product["quantity"] == 0

    movements = sorted(before_movements, key=lambda row: row["id"])
    balance = 0
    for movement in movements:
        balance += movement["delta"]
        assert movement["quantity_after"] == balance
        assert movement["product_id"] == product["id"]
    assert balance == before_product["quantity"]
    assert [row["kind"] for row in movements] == [
        "receipt", "receipt", "receipt", "sale", "return", "sale", "sale", "sale"
    ]


def test_history_can_be_limited_to_one_product(client):
    first = create_product(client)
    second = create_product(client, name="Curtain rings")
    accepted_stock(client, first["barcode"], "receipt")
    accepted_stock(client, second["barcode"], "receipt")
    assert len(history(client)) == 2
    selected = history(client, first["id"])
    assert len(selected) == 1
    assert selected[0]["product_id"] == first["id"]


def test_retry_returns_original_result_without_changing_current_stock(client):
    product = create_product(client)
    receive_request = str(uuid4())
    received = accepted_stock(
        client, product["barcode"], "receipt", request_id=receive_request
    )
    sale_request = str(uuid4())
    sold = accepted_stock(client, product["barcode"], "sale", request_id=sale_request)
    current = product_state(client, product["id"])
    movements = history(client)
    assert current["quantity"] == 0

    for request_id, kind, original in (
        (receive_request, "receipt", received), (sale_request, "sale", sold)
    ):
        retry = stock(client, product["barcode"], kind, request_id=request_id)
        assert retry.status_code == 200, retry.text
        assert retry.json() == {**original, "replayed": True}

    assert received["product"]["quantity"] == 1
    assert product_state(client, product["id"]) == current
    assert history(client) == movements


def test_reusing_operation_id_for_different_payload_is_rejected(client):
    product = create_product(client)
    other_product = create_product(client, name="Curtain hooks")
    request_id = str(uuid4())
    accepted_stock(client, product["barcode"], "receipt", request_id=request_id)
    before = product_state(client, product["id"])
    before_history = history(client)

    assert_error(stock(client, product["barcode"], "sale", request_id=request_id), 409)
    assert_error(stock(client, other_product["barcode"], "receipt", request_id=request_id), 409)
    assert product_state(client, product["id"]) == before
    assert product_state(client, other_product["id"])["quantity"] == 0
    assert history(client) == before_history


def test_quantity_correction_requires_current_revision_and_records_difference(client):
    product = create_product(client)
    first = accepted_stock(client, product["barcode"], "receipt")["product"]
    current = accepted_stock(client, product["barcode"], "receipt")["product"]
    before_history = history(client)

    assert_error(stock(
        client, product["barcode"], "correction", revision=first["revision"],
        quantity=7, reason="Physical count"
    ), 409)
    assert product_state(client, product["id"]) == current
    assert history(client) == before_history

    result = accepted_stock(
        client, product["barcode"], "correction", revision=current["revision"],
        quantity=5, reason="Physical count"
    )
    assert result["product"]["quantity"] == 5
    assert result["movement"]["delta"] == 3
    assert result["movement"]["quantity_after"] == 5
    assert result["movement"]["reason"] == "Physical count"
    assert result["product"]["revision"] > current["revision"]

    reduced = accepted_stock(
        client, product["barcode"], "correction",
        revision=result["product"]["revision"], quantity=1,
        reason="Damaged stock removed"
    )
    assert reduced["movement"]["delta"] == -4
    assert sum(row["delta"] for row in history(client)) == 1


@pytest.mark.parametrize("quantity", [-1, 1.5, True, "2"])
def test_invalid_correction_quantities_do_not_change_stock(client, quantity):
    product = create_product(client)
    assert_error(stock(
        client, product["barcode"], "correction", revision=product["revision"],
        quantity=quantity, reason="Physical count"
    ), 422)
    assert product_state(client, product["id"]) == product
    assert history(client) == []


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_correction_needs_a_nonblank_reason(client, reason):
    product = create_product(client)
    fields = {"revision": product["revision"], "quantity": 4}
    if reason is not None:
        fields["reason"] = reason
    assert_error(stock(client, product["barcode"], "correction", **fields), 422)
    assert product_state(client, product["id"]) == product
    assert history(client) == []


def test_correction_needs_revision_and_target(client):
    product = create_product(client)
    assert_error(stock(client, product["barcode"], "correction", quantity=2, reason="Count"), 422)
    assert_error(stock(
        client, product["barcode"], "correction", revision=product["revision"], reason="Count"
    ), 422)
    assert product_state(client, product["id"]) == product
    assert history(client) == []


@pytest.mark.parametrize("kind", ["receipt", "sale", "return"])
@pytest.mark.parametrize("quantity", [None, 1])
def test_scans_default_to_one_item_and_accept_explicit_one(client, kind, quantity):
    product = create_product(client)
    current = accepted_stock(client, product["barcode"], "receipt", quantity=5)["product"]
    fields = {} if quantity is None else {"quantity": quantity}
    result = accepted_stock(client, product["barcode"], kind, **fields)
    delta = -1 if kind == "sale" else 1
    assert result["product"]["quantity"] == current["quantity"] + delta
    assert result["product"]["revision"] == current["revision"] + 1
    assert result["movement"]["delta"] == delta
    assert result["movement"]["quantity_after"] == current["quantity"] + delta


@pytest.mark.parametrize("kind", ["receipt", "sale", "return"])
@pytest.mark.parametrize("quantity", [0, -1, 1.5, 2.0, True, False, "2", "", 1_000_000_001])
def test_invalid_scan_quantities_do_not_change_stock(client, kind, quantity):
    product = create_product(client)
    current = accepted_stock(client, product["barcode"], "receipt", quantity=5)["product"]
    before_history = history(client)
    assert_error(stock(client, product["barcode"], kind, quantity=quantity), 422)
    assert product_state(client, product["id"]) == current
    assert history(client) == before_history


def test_grouped_receipts_sales_and_returns_create_one_movement_each(client):
    product = create_product(client)
    received = accepted_stock(client, product["barcode"], "receipt", quantity=8)
    sold = accepted_stock(client, product["barcode"], "sale", quantity=5)
    returned = accepted_stock(client, product["barcode"], "return", quantity=2)
    results = [received, sold, returned]

    assert [result["product"]["quantity"] for result in results] == [8, 3, 5]
    assert [result["product"]["revision"] for result in results] == [
        product["revision"] + offset for offset in (1, 2, 3)
    ]
    movements = sorted(history(client), key=lambda row: row["id"])
    assert [row["kind"] for row in movements] == ["receipt", "sale", "return"]
    assert [row["delta"] for row in movements] == [8, -5, 2]
    assert [row["quantity_after"] for row in movements] == [8, 3, 5]
    assert len({row["request_id"] for row in movements}) == 3
    assert [row["request_id"] for row in movements] == [
        result["movement"]["request_id"] for result in results
    ]


def test_selling_more_than_available_is_rejected_without_partial_changes(client):
    product = create_product(client)
    current = accepted_stock(client, product["barcode"], "receipt", quantity=4)["product"]
    before_history = history(client)
    response = stock(client, product["barcode"], "sale", quantity=5)
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "Not enough in stock."}
    assert product_state(client, product["id"]) == current
    assert history(client) == before_history

    result = accepted_stock(client, product["barcode"], "sale", quantity=4)
    assert result["product"]["quantity"] == 0
    assert result["movement"]["delta"] == -4
    response = stock(client, product["barcode"], "sale")
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "Not enough in stock."}
    assert product_state(client, product["id"]) == result["product"]
    assert len(history(client)) == len(before_history) + 1


@pytest.mark.parametrize("kind", ["receipt", "sale", "return"])
def test_grouped_retry_returns_original_snapshot_and_counts_once(client, kind):
    product = create_product(client)
    accepted_stock(client, product["barcode"], "receipt", quantity=5)
    request_id = str(uuid4())
    original = accepted_stock(
        client, product["barcode"], kind, quantity=3, request_id=request_id
    )
    current = accepted_stock(client, product["barcode"], "receipt", quantity=2)["product"]
    before_history = history(client)
    retry = stock(client, product["barcode"], kind, quantity=3, request_id=request_id)
    assert retry.status_code == 200, retry.text
    assert retry.json() == {**original, "replayed": True}

    assert_error(stock(
        client, product["barcode"], kind, quantity=2, request_id=request_id
    ), 409)
    assert product_state(client, product["id"]) == current
    assert history(client) == before_history
    assert sum(row["request_id"] == request_id for row in before_history) == 1


def test_unknown_barcode_and_invalid_operation_do_not_create_stock(client):
    product = create_product(client)
    assert_error(stock(client, "BL-999999999", "receipt"), 404)
    assert_error(stock(client, product["barcode"], "delete"), 422)
    assert_error(stock(client, product["barcode"], "receipt", request_id="not-a-uuid"), 422)
    assert client.get("/api/products").json() == [product]
    assert history(client) == []


def test_metadata_edit_preserves_identity_and_stock_and_rejects_stale_form(client):
    product = create_product(client, price="12.30")
    current = accepted_stock(client, product["barcode"], "receipt")["product"]
    before_history = history(client)
    response = client.patch(f"/api/products/{product['id']}", json={
        "revision": current["revision"], "name": "White roller blind - small",
        "description": "Updated product description", "price": "24.50",
    })
    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited["id"] == product["id"]
    assert edited["barcode"] == product["barcode"]
    assert edited["quantity"] == 1
    assert edited["price"] == "24.50"
    assert edited["revision"] > current["revision"]
    # History decorates the immutable movements with the current product name.
    assert history(client) == [
        {**movement, "product_name": edited["name"]} for movement in before_history
    ]

    assert_error(client.patch(f"/api/products/{product['id']}", json={
        "revision": current["revision"], "name": "Stale form value"
    }), 409)
    assert product_state(client, product["id"]) == edited


@pytest.mark.parametrize("protected,value", [
    ("id", 1000), ("barcode", "REPLACEMENT"), ("quantity", 8), ("archived", True),
])
def test_product_identity_and_stock_cannot_be_set_by_product_forms(client, protected, value):
    assert_error(client.post("/api/products", json={
        "name": "Blind", protected: value
    }), 422)
    product = create_product(client)
    assert_error(client.patch(f"/api/products/{product['id']}", json={
        "revision": product["revision"], protected: value
    }), 422)
    assert product_state(client, product["id"]) == product
    assert history(client) == []


def test_nonempty_stock_cannot_be_archived_and_archived_product_cannot_be_scanned(client):
    product = create_product(client)
    current = accepted_stock(client, product["barcode"], "receipt")["product"]
    before_history = history(client)
    assert_error(client.post(f"/api/products/{product['id']}/archive", json={
        "revision": current["revision"], "archived": True
    }), 409)
    assert product_state(client, product["id"]) == current
    assert history(client) == before_history

    current = accepted_stock(client, product["barcode"], "sale")["product"]
    response = client.post(f"/api/products/{product['id']}/archive", json={
        "revision": current["revision"], "archived": True
    })
    assert response.status_code == 200, response.text
    archived = response.json()
    assert archived["archived"] is True
    assert client.get("/api/products").json() == []
    assert client.get("/api/products", params={"include_archived": True}).json() == [archived]
    before_history = history(client)
    for kind in ("receipt", "sale", "return"):
        assert_error(stock(client, product["barcode"], kind), 409)
    assert_error(stock(
        client, product["barcode"], "correction", revision=archived["revision"],
        quantity=1, reason="Count"
    ), 409)
    assert product_state(client, product["id"]) == archived
    assert history(client) == before_history

    response = client.post(f"/api/products/{product['id']}/archive", json={
        "revision": archived["revision"], "archived": False
    })
    assert response.status_code == 200, response.text
    assert accepted_stock(client, product["barcode"], "receipt")["product"]["quantity"] == 1


def test_stale_archive_revision_does_not_change_product(client):
    product = create_product(client)
    receipt = accepted_stock(client, product["barcode"], "receipt")["product"]
    current = accepted_stock(client, product["barcode"], "sale")["product"]
    assert_error(client.post(f"/api/products/{product['id']}/archive", json={
        "revision": receipt["revision"], "archived": True
    }), 409)
    assert product_state(client, product["id"]) == current


def test_barcode_svg_is_safe_and_does_not_receive_inventory(client):
    product = create_product(client, name='Blind <script>alert("x")</script> & curtain')
    response = client.get(f"/api/products/{product['id']}/barcode.svg")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("image/svg+xml")
    root = ElementTree.fromstring(response.content)
    assert root.tag.rsplit("}", 1)[-1] == "svg"
    assert any(product["barcode"] in (element.text or "") for element in root.iter())
    for element in root.iter():
        assert element.tag.rsplit("}", 1)[-1] not in {"script", "foreignObject"}
        assert not any(key.lower().startswith("on") for key in element.attrib)
    assert product_state(client, product["id"]) == product
    assert history(client) == []


def test_inventory_and_retry_records_survive_restart(db_path: Path):
    request_id = str(uuid4())
    with TestClient(create_app(db_path), base_url="http://127.0.0.1") as first:
        product = create_product(first)
        result = accepted_stock(
            first, product["barcode"], "receipt", quantity=4, request_id=request_id
        )
        before_history = history(first)

    with TestClient(create_app(db_path), base_url="http://127.0.0.1") as reopened:
        assert product_state(reopened, product["id"]) == result["product"]
        assert history(reopened) == before_history
        retry = stock(
            reopened, product["barcode"], "receipt", quantity=4, request_id=request_id
        )
        assert retry.status_code == 200, retry.text
        assert retry.json() == {**result, "replayed": True}
        assert history(reopened) == before_history


@pytest.mark.parametrize("kind", ["receipt", "sale", "return"])
def test_pre_quantity_release_retry_records_still_replay_after_restart(db_path: Path, kind):
    request_id = str(uuid4())
    with TestClient(create_app(db_path), base_url="http://127.0.0.1") as first:
        product = create_product(first)
        accepted_stock(first, product["barcode"], "receipt", quantity=5)
        original = accepted_stock(
            first, product["barcode"], kind, quantity=1, request_id=request_id
        )
        current = accepted_stock(first, product["barcode"], "receipt", quantity=2)["product"]
        before_history = history(first)

    # Earlier versions stored every one-item scan with quantity:null. Put that
    # historical payload on disk, then replay through a newly started app.
    legacy_payload = {
        "barcode": product["barcode"], "kind": kind, "request_id": request_id,
        "revision": None, "quantity": None, "reason": None,
    }
    with closing(sqlite3.connect(db_path)) as connection:
        with connection:
            connection.execute(
                "UPDATE stock_operations SET payload_json = ? WHERE request_id = ?",
                (json.dumps(legacy_payload, sort_keys=True, separators=(",", ":")), request_id),
            )

    with TestClient(create_app(db_path), base_url="http://127.0.0.1") as reopened:
        retry = stock(reopened, product["barcode"], kind, request_id=request_id)
        assert retry.status_code == 200, retry.text
        assert retry.json() == {**original, "replayed": True}
        assert product_state(reopened, product["id"]) == current
        assert history(reopened) == before_history


def test_backup_is_complete_and_can_be_restored(client, tmp_path: Path):
    first = create_product(client)
    second = create_product(client, name="Curtain rings")
    accepted_stock(client, first["barcode"], "receipt")
    accepted_stock(client, second["barcode"], "receipt")
    request_id = str(uuid4())
    original = accepted_stock(client, first["barcode"], "receipt", request_id=request_id)
    products = client.get("/api/products").json()
    movements = history(client)

    response = client.get("/api/backup")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"SQLite format 3\x00")
    assert "attachment" in response.headers.get("content-disposition", "")
    backup_path = tmp_path / "restored.sqlite3"
    backup_path.write_bytes(response.content)
    with closing(sqlite3.connect(backup_path)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    accepted_stock(client, first["barcode"], "sale")
    with TestClient(create_app(backup_path), base_url="http://127.0.0.1") as restored:
        assert restored.get("/api/products").json() == products
        assert history(restored) == movements
        retry = stock(restored, first["barcode"], "receipt", request_id=request_id)
        assert retry.status_code == 200, retry.text
        assert retry.json() == {**original, "replayed": True}
        assert history(restored) == movements


@pytest.mark.parametrize("available,requested,remaining", [(1, 1, 0), (10, 6, 4)])
def test_two_simultaneous_sales_cannot_oversell_stock(client, available, requested, remaining):
    product = create_product(client)
    current = accepted_stock(client, product["barcode"], "receipt", quantity=available)["product"]
    barrier = Barrier(2)

    def sell_items():
        barrier.wait(timeout=10)
        return stock(client, product["barcode"], "sale", quantity=requested)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(sell_items) for _ in range(2)]
        responses = [future.result(timeout=20) for future in futures]

    assert sorted(response.status_code for response in responses) == [200, 409]
    assert next(response for response in responses if response.status_code == 409).json() == {
        "detail": "Not enough in stock."
    }
    final = product_state(client, product["id"])
    assert final["quantity"] == remaining
    assert final["revision"] == current["revision"] + 1
    movements = history(client, product["id"])
    assert len(movements) == 2
    assert sum(row["kind"] == "sale" for row in movements) == 1
    assert sorted(row["delta"] for row in movements) == [-requested, available]
    assert sum(row["delta"] for row in movements) == remaining
