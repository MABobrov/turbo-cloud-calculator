"""Тесты прайс-листа."""

from decimal import Decimal

import pytest

from turbo_calc.pricelist import PriceList, UnknownSkuError, load_default


def test_default_pricelist_loads_and_has_source():
    pl = load_default()
    assert pl.source == "https://turbocloud.ru/prices"
    assert pl.currency == "RUB"
    assert len(pl) >= 80


@pytest.mark.parametrize(
    ("sku", "price"),
    [
        ("vm.vcpu", "531.00"),
        ("vm.ram_gb", "250.00"),
        ("disk.ssd", "16.00"),
        ("net.ip", "170.00"),
        ("gpu.h200.full", "444933.34"),
        ("s3.std_gb", "1.78"),
        ("k8s.cp_ha", "13939.20"),
        ("db.admin", "8000.00"),
        ("inference.h200_vram_gb_hour", "7.50"),
    ],
)
def test_prices_match_site(sku, price):
    assert load_default().get(sku).price == Decimal(price)


def test_unit_price_for_request_packages():
    item = load_default().get("s3.std_put")
    assert item.per == 1000
    assert item.unit_price == Decimal("0.0005")
    assert item.period == "once"


def test_unknown_sku_raises():
    with pytest.raises(UnknownSkuError, match="нет-такого"):
        load_default().get("нет-такого")


def test_by_category_and_contains():
    pl = load_default()
    assert "vm.vcpu" in pl
    assert "x" not in pl
    assert all(i.category == "gpu" for i in pl.by_category("gpu"))
    assert len(pl.by_category("gpu")) == 15


def test_from_dict_rejects_duplicates_and_bad_values():
    base = {"source": "s", "captured_at": "d"}
    dup = {
        **base,
        "items": [
            {"sku": "a", "category": "c", "name": "n", "unit": "u", "price": "1"},
            {"sku": "a", "category": "c", "name": "n", "unit": "u", "price": "2"},
        ],
    }
    with pytest.raises(ValueError, match="Дублирующийся"):
        PriceList.from_dict(dup)
    bad = {**base, "items": [{"sku": "a", "category": "c", "name": "n", "unit": "u", "price": "-1"}]}
    with pytest.raises(ValueError, match="Некорректная"):
        PriceList.from_dict(bad)


def test_from_path(tmp_path):
    p = tmp_path / "pl.json"
    p.write_text(
        '{"source":"s","captured_at":"d","items":[{"sku":"a","category":"c","name":"n","unit":"u","price":"1.5"}]}',
        encoding="utf-8",
    )
    pl = PriceList.from_path(p)
    assert pl.get("a").price == Decimal("1.5")
