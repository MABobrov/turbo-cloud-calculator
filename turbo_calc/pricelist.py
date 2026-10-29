"""Прайс-лист «Турбо Облака».

Модуль загружает прайс-лист из JSON-файла и даёт доступ к позициям по коду SKU.
Источник цен: https://turbocloud.ru/prices. Цены указаны в рублях без НДС.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Literal

Period = Literal["month", "hour", "once"]


class UnknownSkuError(KeyError):
    """Запрошенный SKU отсутствует в прайс-листе."""

    def __init__(self, sku: str) -> None:
        super().__init__(sku)
        self.sku = sku

    def __str__(self) -> str:
        return f"SKU «{self.sku}» отсутствует в прайс-листе"


@dataclass(frozen=True, slots=True)
class PriceItem:
    """Одна позиция прайс-листа.

    Attributes:
        sku: Код позиции, например ``vm.vcpu``.
        category: Группа сервиса, например ``vm`` или ``s3``.
        name: Наименование позиции на русском языке.
        unit: Единица тарификации, например ``ГБ``.
        price: Цена за ``per`` единиц в рублях без НДС.
        period: Период тарификации: ``month``, ``hour`` или ``once``.
        per: Число единиц, за которое указана цена (1 000 запросов → 1000).
    """

    sku: str
    category: str
    name: str
    unit: str
    price: Decimal
    period: Period
    per: int = 1

    @property
    def unit_price(self) -> Decimal:
        """Цена за одну единицу тарификации."""
        return self.price / Decimal(self.per)


@dataclass(frozen=True, slots=True)
class PriceList:
    """Прайс-лист: набор позиций и метаданные источника."""

    source: str
    captured_at: str
    currency: str
    items: dict[str, PriceItem]

    def get(self, sku: str) -> PriceItem:
        """Возвращает позицию по SKU. Возбуждает UnknownSkuError, если SKU нет."""
        try:
            return self.items[sku]
        except KeyError as exc:
            raise UnknownSkuError(sku) from exc

    def __contains__(self, sku: object) -> bool:
        return sku in self.items

    def __len__(self) -> int:
        return len(self.items)

    def by_category(self, category: str) -> list[PriceItem]:
        """Возвращает позиции одной категории в порядке прайс-листа."""
        return [item for item in self.items.values() if item.category == category]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PriceList:
        """Создаёт прайс-лист из словаря (структура JSON-файла)."""
        items: dict[str, PriceItem] = {}
        for raw in data["items"]:
            item = PriceItem(
                sku=raw["sku"],
                category=raw["category"],
                name=raw["name"],
                unit=raw["unit"],
                price=Decimal(str(raw["price"])),
                period=raw.get("period", "month"),
                per=int(raw.get("per", 1)),
            )
            if item.sku in items:
                raise ValueError(f"Дублирующийся SKU в прайс-листе: {item.sku}")
            if item.price < 0 or item.per <= 0:
                raise ValueError(f"Некорректная цена или кратность у SKU {item.sku}")
            items[item.sku] = item
        return cls(
            source=data["source"],
            captured_at=data["captured_at"],
            currency=data.get("currency", "RUB"),
            items=items,
        )

    @classmethod
    def from_path(cls, path: Path | str) -> PriceList:
        """Загружает прайс-лист из JSON-файла."""
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


@lru_cache(maxsize=1)
def load_default() -> PriceList:
    """Загружает встроенный прайс-лист ``turbo_calc/data/pricelist.json``."""
    ref = resources.files("turbo_calc").joinpath("data/pricelist.json")
    with ref.open(encoding="utf-8") as fh:
        return PriceList.from_dict(json.load(fh))
