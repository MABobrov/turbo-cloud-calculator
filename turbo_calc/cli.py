"""Интерфейс командной строки.

Команды:
- ``turbo-calc estimate config.json [--format text|json|csv] [--out file]``
- ``turbo-calc pricelist [--category vm]``
- ``turbo-calc serve [--port 8000]``
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from turbo_calc import __version__
from turbo_calc.calculator import Calculator
from turbo_calc.models import Configuration, Estimate


def _fmt(value: Decimal) -> str:
    """Форматирует число в русской записи: разряды через пробел, копейки через запятую."""
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def render_text(est: Estimate) -> str:
    """Возвращает смету в виде текста для терминала."""
    out = io.StringIO()
    width = 100
    title = "Смета «Турбо Облако»"
    if est.customer:
        title += f" для {est.customer}"
    out.write(f"{title}\n")
    out.write(f"Срок: {est.months} мес. Прайс-лист: {est.pricelist_source} от {est.pricelist_captured_at}\n")
    out.write("=" * width + "\n")
    for section in est.sections:
        out.write(f"{section.title}\n")
        for line in section.lines:
            qty = f"{line.quantity:,.0f}".replace(",", " ")
            out.write(
                f"  {line.name:<58} {qty:>10} {line.unit:<9} × {_fmt(line.unit_price):>12} = {_fmt(line.amount):>15}\n"
            )
        out.write(f"  {'Итого по разделу':<96} {_fmt(section.subtotal):>15}\n")
        out.write("-" * width + "\n")
    out.write(f"{'Сумма без НДС':<96} {_fmt(est.subtotal):>15}\n")
    if est.discount_amount:
        out.write(f"{f'Скидка {est.discount_percent} %':<96} {'-' + _fmt(est.discount_amount):>15}\n")
        out.write(f"{'Сумма без НДС после скидки':<96} {_fmt(est.total_ex_vat):>15}\n")
    out.write(f"{f'НДС {est.vat_percent} %':<96} {_fmt(est.vat_amount):>15}\n")
    out.write(f"{'ИТОГО с НДС за срок':<96} {_fmt(est.total):>15}\n")
    out.write(f"{'Среднемесячный платёж без НДС':<96} {_fmt(est.monthly_ex_vat):>15}\n")
    return out.getvalue()


def render_csv(est: Estimate) -> str:
    """Возвращает строки сметы в формате CSV (разделитель «;»)."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow(["Раздел", "SKU", "Наименование", "Количество", "Ед.", "Цена без НДС", "Сумма без НДС"])
    for section in est.sections:
        for line in section.lines:
            writer.writerow(
                [
                    section.title,
                    line.sku,
                    line.name,
                    f"{line.quantity}",
                    line.unit,
                    f"{line.unit_price}",
                    f"{line.amount}",
                ]
            )
    writer.writerow(["", "", "Сумма без НДС", "", "", "", f"{est.subtotal}"])
    writer.writerow(["", "", f"Скидка {est.discount_percent} %", "", "", "", f"-{est.discount_amount}"])
    writer.writerow(["", "", f"НДС {est.vat_percent} %", "", "", "", f"{est.vat_amount}"])
    writer.writerow(["", "", "Итого с НДС", "", "", "", f"{est.total}"])
    return out.getvalue()


def render_json(est: Estimate) -> str:
    return est.model_dump_json(indent=2)


RENDERERS = {"text": render_text, "json": render_json, "csv": render_csv}


def cmd_estimate(args: argparse.Namespace) -> int:
    raw = json.loads(Path(args.config).read_text(encoding="utf-8"))
    try:
        config = Configuration.model_validate(raw)
    except ValidationError as exc:
        print("Ошибка в конфигурации:", file=sys.stderr)
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "<root>"
            print(f"  {loc}: {err['msg']}", file=sys.stderr)
        return 2
    try:
        est = Calculator().estimate(config)
    except ValueError as exc:
        print(f"Ошибка расчёта: {exc}", file=sys.stderr)
        return 2
    text = RENDERERS[args.format](est)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Смета записана в {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_pricelist(args: argparse.Namespace) -> int:
    pl = Calculator().pricelist
    items = pl.by_category(args.category) if args.category else list(pl.items.values())
    print(f"Прайс-лист {pl.source} от {pl.captured_at}, цены в {pl.currency} без НДС")
    for item in items:
        print(f"  {item.sku:<30} {item.name:<58} {_fmt(item.price):>12} / {item.unit} / {item.period}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("turbo_calc.api:app", host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="turbo-calc", description="Калькулятор стоимости «Турбо Облака»")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_est = sub.add_parser("estimate", help="Рассчитать смету по JSON-конфигурации")
    p_est.add_argument("config", help="Путь к JSON-файлу конфигурации")
    p_est.add_argument("--format", choices=RENDERERS, default="text")
    p_est.add_argument("--out", help="Записать результат в файл")
    p_est.set_defaults(func=cmd_estimate)

    p_pl = sub.add_parser("pricelist", help="Показать прайс-лист")
    p_pl.add_argument("--category", help="Категория: vm, gpu, k8s, db, s3, backup, network, os, inference")
    p_pl.set_defaults(func=cmd_pricelist)

    p_srv = sub.add_parser("serve", help="Запустить REST API")
    p_srv.add_argument("--host", default="0.0.0.0")
    p_srv.add_argument("--port", type=int, default=8000)
    p_srv.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
