"""The local skeleton must reject writes submitted by unrelated web pages."""

import pytest


@pytest.mark.parametrize("host", [
    "inventory.example.com", "192.168.1.20", "127.0.0.1@inventory.example.com",
    "user@127.0.0.1", "127.0.0.1/path", "127.0.0.1:invalid",
])
def test_nonlocal_and_malformed_hosts_cannot_read_or_write_inventory(client, host):
    for response in (
        client.get("/api/products", headers={"Host": host}),
        client.post("/api/products", json={"name": "Untrusted item"}, headers={"Host": host}),
    ):
        assert response.status_code == 403
        assert response.json()["detail"]
    assert client.get("/api/products").json() == []


@pytest.mark.parametrize("origin", [
    "https://inventory.example.com", "null", "http://127.0.0.1:8766",
    "https://127.0.0.1", "http://localhost", "http://user@127.0.0.1",
])
def test_other_browser_origins_cannot_change_inventory(client, origin):
    response = client.post(
        "/api/products", json={"name": "Untrusted item"}, headers={"Origin": origin}
    )
    assert response.status_code == 403
    assert response.json()["detail"]
    assert client.get("/api/products").json() == []
    assert client.get("/api/movements").json() == []


@pytest.mark.parametrize("content_type", ["application/x-www-form-urlencoded", "text/plain"])
def test_simple_browser_form_posts_cannot_change_inventory(client, content_type):
    response = client.post(
        "/api/products", content='{"name":"Untrusted item"}',
        headers={"Content-Type": content_type},
    )
    assert response.status_code == 415
    assert response.json()["detail"]
    assert client.get("/api/products").json() == []


@pytest.mark.parametrize("origin", ["http://127.0.0.1", "http://127.0.0.1:80"])
def test_matching_browser_origin_can_submit_json_and_reads_are_not_cached(client, origin):
    response = client.post(
        "/api/products", json={"name": "Trusted item"}, headers={"Origin": origin}
    )
    assert response.status_code == 201, response.text
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"
    products = client.get("/api/products")
    assert products.json() == [response.json()]
    assert products.headers["Cache-Control"] == "no-store"
