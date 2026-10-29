"""Тесты интерфейса командной строки."""

import json
from pathlib import Path

import pytest

from turbo_calc.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "turbo-calc 1." in capsys.readouterr().out


@pytest.mark.parametrize("example", ["web-app.json", "ai-platform.json"])
def test_estimate_examples_text(capsys, example):
    assert main(["estimate", str(EXAMPLES / example)]) == 0
    out = capsys.readouterr().out
    assert "ИТОГО с НДС" in out
    assert "Среднемесячный платёж" in out


def test_estimate_json_and_csv_to_file(tmp_path):
    out_json = tmp_path / "e.json"
    assert main(["estimate", str(EXAMPLES / "web-app.json"), "--format", "json", "--out", str(out_json)]) == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["months"] == 12 and data["sections"]

    out_csv = tmp_path / "e.csv"
    assert main(["estimate", str(EXAMPLES / "web-app.json"), "--format", "csv", "--out", str(out_csv)]) == 0
    lines = out_csv.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("Раздел;SKU;")
    assert lines[-1].startswith(";;Итого с НДС")


def test_estimate_invalid_config_returns_2(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"vms": [{"vcpu": 0, "ram_gb": 1, "disks": []}]}', encoding="utf-8")
    assert main(["estimate", str(bad)]) == 2
    assert "Ошибка в конфигурации" in capsys.readouterr().err


def test_estimate_domain_error_returns_2(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"databases": [{"engine": "kafka", "vcpu": 1, "ram_gb": 1, "disk_gb": 1, "backup_copies_gb": 1}]}',
        encoding="utf-8",
    )
    assert main(["estimate", str(bad)]) == 2
    assert "Ошибка расчёта" in capsys.readouterr().err


def test_pricelist_command(capsys):
    assert main(["pricelist", "--category", "backup"]) == 0
    out = capsys.readouterr().out
    assert "backup.protected_gb" in out and "vm.vcpu" not in out
