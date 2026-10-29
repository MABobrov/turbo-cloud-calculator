"""Тесты расчёта сметы. Ожидаемые суммы посчитаны вручную по прайс-листу."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from turbo_calc.calculator import Calculator, money
from turbo_calc.models import Configuration

D = Decimal


def cfg(**kwargs) -> Configuration:
    return Configuration.model_validate(kwargs)


SSD_50 = [{"type": "ssd", "size_gb": 50}]


@pytest.fixture(scope="module")
def calc() -> Calculator:
    return Calculator()


def test_money_rounds_half_up():
    assert money(D("1.005")) == D("1.01")
    assert money(D("1.004")) == D("1.00")


def test_single_vm_one_month(calc):
    est = calc.estimate(cfg(vms=[{"vcpu": 2, "ram_gb": 4, "disks": SSD_50, "os": "astra_orel", "public_ips": 1}]))
    # 2×531 + 4×250 + 50×16 + 1511.10 + 170
    assert est.subtotal == D("4543.10")
    assert est.vat_amount == D("999.48")
    assert est.total == D("5542.58")
    assert est.monthly_ex_vat == D("4543.10")
    assert [line.sku for line in est.sections[0].lines] == [
        "vm.vcpu",
        "vm.ram_gb",
        "disk.ssd",
        "os.astra_orel",
        "net.ip",
    ]


def test_vm_count_and_months_multiply(calc):
    est = calc.estimate(
        cfg(months=3, vms=[{"count": 2, "vcpu": 2, "ram_gb": 4, "disks": SSD_50, "os": "astra_orel", "public_ips": 1}])
    )
    assert est.subtotal == D("27258.60")
    assert est.monthly_ex_vat == D("9086.20")


def test_vm_high_capacity_uses_hc_skus(calc):
    est = calc.estimate(cfg(vms=[{"vcpu": 1, "ram_gb": 1, "high_capacity": True, "disks": SSD_50}]))
    skus = {line.sku for line in est.sections[0].lines}
    assert {"vm.vcpu_hc", "vm.ram_gb_hc"} <= skus
    assert est.subtotal == D("617") + D("250") + D("800")


def test_disks_grouped_by_type(calc):
    disks = [{"type": "ssd", "size_gb": 10}, {"type": "sata", "size_gb": 100}, {"type": "ssd", "size_gb": 30}]
    est = calc.estimate(cfg(vms=[{"vcpu": 1, "ram_gb": 1, "disks": disks}]))
    by_sku = {line.sku: line for line in est.sections[0].lines}
    assert by_sku["disk.ssd"].quantity == D(40)
    assert by_sku["disk.sata"].quantity == D(100)


def test_discount_applied_before_vat(calc):
    est = calc.estimate(
        cfg(discount_percent="10", vms=[{"vcpu": 2, "ram_gb": 4, "disks": SSD_50, "os": "astra_orel", "public_ips": 1}])
    )
    assert est.discount_amount == D("454.31")
    assert est.total_ex_vat == D("4088.79")
    assert est.vat_amount == D("899.53")
    assert est.total == D("4988.32")


def test_gpu_h200_full_card(calc):
    est = calc.estimate(
        cfg(
            gpu_vms=[
                {
                    "cluster": "h200",
                    "vcpu": 8,
                    "ram_gb": 64,
                    "h200_profile": "full",
                    "h200_cards": 1,
                    "disks": [{"type": "ssd", "size_gb": 100}],
                }
            ]
        )
    )
    assert est.subtotal == D("471093.34")


def test_gpu_l4_by_vram(calc):
    est = calc.estimate(
        cfg(
            gpu_vms=[
                {"cluster": "l4", "vcpu": 4, "ram_gb": 16, "vram_gb": 24, "disks": [{"type": "ssd", "size_gb": 100}]}
            ]
        )
    )
    assert est.subtotal == D("43200.00")


def test_object_storage_standard_with_requests(calc):
    est = calc.estimate(
        cfg(
            object_storage=[
                {
                    "tier": "standard",
                    "storage_gb": 1000,
                    "egress_gb_per_month": 100,
                    "put_requests_per_month": 2_000_000,
                    "get_requests_per_month": 50_000_000,
                }
            ]
        )
    )
    assert est.subtotal == D("4900.00")


def test_object_storage_fixed_tier(calc):
    est = calc.estimate(cfg(object_storage=[{"tier": "fixed", "storage_gb": 100}]))
    assert est.subtotal == D("190.00")
    assert len(est.sections[0].lines) == 1


def test_kubernetes_ha_with_managed_nodes(calc):
    est = calc.estimate(
        cfg(
            kubernetes=[
                {
                    "nodes": 3,
                    "node_vcpu": 4,
                    "node_ram_gb": 16,
                    "node_disk_gb": 50,
                    "pv_ssd_gb": 100,
                    "public_ips": 1,
                    "managed_nodes": True,
                }
            ]
        )
    )
    assert est.subtotal == D("42631.20")


def test_kubernetes_single_control_plane(calc):
    est = calc.estimate(
        cfg(
            kubernetes=[
                {
                    "ha_control_plane": False,
                    "nodes": 1,
                    "node_vcpu": 1,
                    "node_ram_gb": 1,
                    "node_disk_gb": 1,
                    "public_ips": 0,
                }
            ]
        )
    )
    assert est.sections[0].lines[0].sku == "k8s.cp_single"
    assert est.subtotal == D("4646.40") + D("531") + D("250") + D("16")


def test_managed_postgresql_with_backup(calc):
    est = calc.estimate(
        cfg(databases=[{"engine": "postgresql", "vcpu": 2, "ram_gb": 8, "disk_gb": 100, "backup_copies_gb": 200}])
    )
    assert est.subtotal == D("13110.00")


def test_db_backup_not_available_for_engine(calc):
    with pytest.raises(ValueError, match="не тарифицируется"):
        calc.estimate(
            cfg(databases=[{"engine": "kafka", "vcpu": 2, "ram_gb": 8, "disk_gb": 100, "backup_copies_gb": 10}])
        )


def test_backup_section(calc):
    est = calc.estimate(cfg(backup={"protected_gb": 100, "stored_copies_gb": 300}))
    assert est.subtotal == D("900.00")


def test_inference_hourly(calc):
    est = calc.estimate(cfg(inference=[{"vram_gb": 141, "ssd_gb": 300, "hours_per_month": 720}]))
    assert est.subtotal == D("765720.00")
    assert est.sections[0].lines[0].period == "hour"


def test_network_only(calc):
    est = calc.estimate(cfg(network={"public_ips": 2, "bandwidth_mbps": 100}))
    assert est.subtotal == D("17277.97")
    assert est.sections[0].title == "Сетевые сервисы"


def test_zero_quantities_do_not_create_lines(calc):
    est = calc.estimate(cfg(vms=[{"vcpu": 1, "ram_gb": 1, "disks": SSD_50}]))
    assert all(line.quantity > 0 for line in est.sections[0].lines)
    assert "net.ip" not in {line.sku for line in est.sections[0].lines}


def test_totals_equal_sum_of_sections(calc):
    est = calc.estimate(
        cfg(
            vms=[{"vcpu": 3, "ram_gb": 7, "disks": SSD_50}],
            backup={"protected_gb": 33},
            network={"public_ips": 1},
        )
    )
    assert est.subtotal == sum(s.subtotal for s in est.sections)
    assert est.total == est.total_ex_vat + est.vat_amount


# ------------------------------------------------------------ проверка входных данных


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"vms": [{"vcpu": 0, "ram_gb": 1, "disks": SSD_50}]},
        {"vms": [{"vcpu": 1, "ram_gb": 1, "disks": []}]},
        {"vms": [{"vcpu": 1, "ram_gb": 1, "disks": SSD_50, "os": "windows"}]},
        {"vms": [{"vcpu": 1, "ram_gb": 1, "disks": SSD_50, "unknown": 1}]},
        {"months": 0, "vms": [{"vcpu": 1, "ram_gb": 1, "disks": SSD_50}]},
        {"discount_percent": 51, "vms": [{"vcpu": 1, "ram_gb": 1, "disks": SSD_50}]},
        {"gpu_vms": [{"cluster": "h200", "vcpu": 1, "ram_gb": 1, "disks": SSD_50}]},
        {"gpu_vms": [{"cluster": "l4", "vcpu": 1, "ram_gb": 1, "disks": SSD_50}]},
        {"gpu_vms": [{"cluster": "l4", "vcpu": 1, "ram_gb": 1, "vram_gb": 1, "h200_cards": 1, "disks": SSD_50}]},
        {
            "gpu_vms": [
                {"cluster": "l4", "vcpu": 1, "ram_gb": 1, "vram_gb": 1, "disks": [{"type": "sas", "size_gb": 1}]}
            ]
        },
        {"object_storage": [{"tier": "fixed", "storage_gb": 1, "egress_gb_per_month": 1}]},
        {"network": {"bandwidth_mbps": 150}},
    ],
)
def test_invalid_configurations_rejected(payload):
    with pytest.raises(ValidationError):
        Configuration.model_validate(payload)
