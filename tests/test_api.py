"""Тесты REST API."""

import pytest
from fastapi.testclient import TestClient

from turbo_calc.api import create_app

VM = {"vcpu": 2, "ram_gb": 4, "disks": [{"type": "ssd", "size_gb": 50}], "os": "astra_orel", "public_ips": 1}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_index_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Калькулятор стоимости" in r.text
    assert "/v1/estimate" in r.text


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["pricelist_items"] >= 80
    assert "X-Request-ID" in r.headers


def test_request_id_is_propagated(client):
    r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"


def test_pricelist_and_category_filter(client):
    r = client.get("/v1/pricelist")
    assert r.status_code == 200
    assert r.json()["vat_included"] is False
    r = client.get("/v1/pricelist", params={"category": "s3"})
    items = r.json()["items"]
    assert items and all(i["category"] == "s3" for i in items)


def test_pricelist_item_found_and_not_found(client):
    assert client.get("/v1/pricelist/vm.vcpu").json()["price"] == "531.00"
    r = client.get("/v1/pricelist/nope")
    assert r.status_code == 404
    assert "nope" in r.json()["detail"]


def test_estimate_ok(client):
    r = client.post("/v1/estimate", json={"customer": "Тест", "vms": [VM]})
    assert r.status_code == 200
    body = r.json()
    assert body["subtotal"] == "4543.10"
    assert body["total"] == "5542.58"
    assert body["customer"] == "Тест"


def test_estimate_validation_error_422(client):
    r = client.post("/v1/estimate", json={"vms": [{"vcpu": 0, "ram_gb": 1, "disks": []}]})
    assert r.status_code == 422
    assert r.json()["detail"]


def test_estimate_domain_error_422(client):
    payload = {"databases": [{"engine": "kafka", "vcpu": 1, "ram_gb": 1, "disk_gb": 1, "backup_copies_gb": 1}]}
    r = client.post("/v1/estimate", json=payload)
    assert r.status_code == 422
    assert "не тарифицируется" in r.json()["detail"]


def test_openapi_schema_available(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "/v1/estimate" in r.json()["paths"]
