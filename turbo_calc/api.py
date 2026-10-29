"""REST API калькулятора на FastAPI.

Эндпоинты:
- ``GET  /``                  — веб-интерфейс калькулятора (одна HTML-страница).
- ``GET  /health``            — проверка работоспособности.
- ``GET  /v1/pricelist``      — прайс-лист (фильтр по категории).
- ``GET  /v1/pricelist/{sku}``— одна позиция прайс-листа.
- ``POST /v1/estimate``       — расчёт сметы по конфигурации.

Каждый ответ содержит заголовок ``X-Request-ID``.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from importlib import resources

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from turbo_calc import __version__
from turbo_calc.calculator import Calculator
from turbo_calc.models import Configuration, Estimate
from turbo_calc.pricelist import PriceItem, UnknownSkuError

logger = logging.getLogger("turbo_calc.api")


class PriceItemOut(BaseModel):
    """Позиция прайс-листа в ответе API."""

    sku: str
    category: str
    name: str
    unit: str
    price: Decimal
    period: str
    per: int

    @classmethod
    def from_item(cls, item: PriceItem) -> PriceItemOut:
        return cls(
            sku=item.sku,
            category=item.category,
            name=item.name,
            unit=item.unit,
            price=item.price,
            period=item.period,
            per=item.per,
        )


class PriceListOut(BaseModel):
    """Прайс-лист в ответе API."""

    source: str
    captured_at: str
    currency: str
    vat_included: bool = False
    items: list[PriceItemOut]


class HealthOut(BaseModel):
    status: str
    version: str
    pricelist_captured_at: str
    pricelist_items: int


def create_app(calculator: Calculator | None = None) -> FastAPI:
    """Создаёт приложение FastAPI. Калькулятор можно подменить в тестах."""
    calc = calculator or Calculator()
    app = FastAPI(
        title="Turbo Cloud Calculator",
        version=__version__,
        description="Калькулятор стоимости облачных ресурсов «Турбо Облака» (ООО «Турбо»).",
    )

    @app.middleware("http")
    async def request_id_and_timing(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_id=%s method=%s path=%s status=%s elapsed_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> HTMLResponse:
        """Отдаёт веб-интерфейс калькулятора."""
        page = resources.files("turbo_calc").joinpath("static/index.html").read_text(encoding="utf-8")
        return HTMLResponse(page)

    @app.get("/health", response_model=HealthOut, tags=["service"])
    def health() -> HealthOut:
        return HealthOut(
            status="ok",
            version=__version__,
            pricelist_captured_at=calc.pricelist.captured_at,
            pricelist_items=len(calc.pricelist),
        )

    @app.get("/v1/pricelist", response_model=PriceListOut, tags=["pricelist"])
    def pricelist(
        category: str | None = Query(default=None, description="Фильтр по категории, например vm"),
    ) -> PriceListOut:
        pl = calc.pricelist
        items = pl.by_category(category) if category else list(pl.items.values())
        return PriceListOut(
            source=pl.source,
            captured_at=pl.captured_at,
            currency=pl.currency,
            items=[PriceItemOut.from_item(i) for i in items],
        )

    @app.get("/v1/pricelist/{sku}", response_model=PriceItemOut, tags=["pricelist"])
    def pricelist_item(sku: str) -> PriceItemOut:
        try:
            return PriceItemOut.from_item(calc.pricelist.get(sku))
        except UnknownSkuError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/estimate", response_model=Estimate, tags=["estimate"])
    def estimate(config: Configuration) -> Estimate:
        return calc.estimate(config)

    return app


app = create_app()


def main() -> None:
    """Запускает сервер разработки."""
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    uvicorn.run("turbo_calc.api:app", host="0.0.0.0", port=8000)
