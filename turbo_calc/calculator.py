"""Расчёт стоимости конфигурации по прайс-листу.

Класс ``Calculator`` принимает ``Configuration`` и возвращает ``Estimate``.
Расчёт выполняется в ``Decimal``. Каждая строка округляется до копейки
по правилу ROUND_HALF_UP. Итоги считаются как сумма округлённых строк.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from turbo_calc.models import (
    Backup,
    Configuration,
    DiskSpec,
    Estimate,
    GpuVirtualMachine,
    InferenceWorkload,
    KubernetesCluster,
    LineItem,
    ManagedDatabase,
    Network,
    ObjectStorage,
    Section,
    VirtualMachine,
)
from turbo_calc.pricelist import PriceList, load_default

CENT = Decimal("0.01")
HUNDRED = Decimal(100)

_DB_ENGINES_WITH_BACKUP = frozenset({"postgresql", "mysql", "pangolin", "redis", "qdrant"})


def money(value: Decimal) -> Decimal:
    """Округляет сумму до копейки по правилу ROUND_HALF_UP."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class Calculator:
    """Калькулятор стоимости облачных ресурсов «Турбо Облака»."""

    def __init__(self, pricelist: PriceList | None = None) -> None:
        self.pricelist = pricelist or load_default()

    # ------------------------------------------------------------ публичный API

    def estimate(self, config: Configuration) -> Estimate:
        """Рассчитывает смету для конфигурации."""
        months = Decimal(config.months)
        sections: list[Section] = []

        for vm in config.vms:
            sections.append(self._vm_section(vm, months))
        for gpu in config.gpu_vms:
            sections.append(self._gpu_section(gpu, months))
        for k8s in config.kubernetes:
            sections.append(self._k8s_section(k8s, months))
        for db in config.databases:
            sections.append(self._db_section(db, months))
        for s3 in config.object_storage:
            sections.append(self._s3_section(s3, months))
        if config.backup:
            sections.append(self._backup_section(config.backup, months))
        for job in config.inference:
            sections.append(self._inference_section(job, months))
        network = self._network_section(config.network, months)
        if network.lines:
            sections.append(network)

        subtotal = money(sum((s.subtotal for s in sections), Decimal(0)))
        discount_amount = money(subtotal * config.discount_percent / HUNDRED)
        total_ex_vat = subtotal - discount_amount
        vat_amount = money(total_ex_vat * config.vat_percent / HUNDRED)
        total = total_ex_vat + vat_amount

        return Estimate(
            customer=config.customer,
            months=config.months,
            currency=self.pricelist.currency,
            pricelist_source=self.pricelist.source,
            pricelist_captured_at=self.pricelist.captured_at,
            sections=sections,
            subtotal=subtotal,
            discount_percent=config.discount_percent,
            discount_amount=discount_amount,
            total_ex_vat=total_ex_vat,
            vat_percent=config.vat_percent,
            vat_amount=vat_amount,
            total=total,
            monthly_ex_vat=money(total_ex_vat / months),
        )

    # ------------------------------------------------------------ строки

    def _line(self, sku: str, quantity: Decimal | int) -> LineItem | None:
        """Создаёт строку сметы. Возвращает None, если количество равно нулю."""
        qty = Decimal(quantity)
        if qty <= 0:
            return None
        item = self.pricelist.get(sku)
        return LineItem(
            sku=item.sku,
            name=item.name,
            unit=item.unit,
            period=item.period,
            quantity=qty,
            unit_price=item.unit_price,
            amount=money(item.unit_price * qty),
        )

    @staticmethod
    def _section(title: str, lines: list[LineItem | None]) -> Section:
        real = [line for line in lines if line is not None]
        return Section(title=title, lines=real, subtotal=money(sum((x.amount for x in real), Decimal(0))))

    # ------------------------------------------------------------ разделы

    def _vm_section(self, vm: VirtualMachine, months: Decimal) -> Section:
        n = Decimal(vm.count) * months
        suffix = "_hc" if vm.high_capacity else ""
        lines: list[LineItem | None] = [
            self._line(f"vm.vcpu{suffix}", vm.vcpu * n),
            self._line(f"vm.ram_gb{suffix}", vm.ram_gb * n),
        ]
        lines.extend(self._disk_lines("disk", vm.disks, n))
        if vm.os:
            lines.append(self._line(f"os.{vm.os}", n))
        lines.append(self._line("net.ip", vm.public_ips * n))
        title = f"ВМ «{vm.name}» × {vm.count}: {vm.vcpu} vCPU, {vm.ram_gb} ГБ RAM"
        return self._section(title, lines)

    def _gpu_section(self, gpu: GpuVirtualMachine, months: Decimal) -> Section:
        n = Decimal(gpu.count) * months
        c = gpu.cluster
        lines: list[LineItem | None] = [
            self._line(f"gpu.{c}.vcpu", gpu.vcpu * n),
            self._line(f"gpu.{c}.ram_gb", gpu.ram_gb * n),
        ]
        if c == "h200":
            lines.append(self._line(f"gpu.h200.{gpu.h200_profile}", gpu.h200_cards * n))
        else:
            lines.append(self._line(f"gpu.{c}.vram_gb", gpu.vram_gb * n))
        lines.extend(self._disk_lines("gpu.disk", gpu.disks, n))
        lines.append(self._line("net.ip", gpu.public_ips * n))
        title = f"GPU-ВМ «{gpu.name}» × {gpu.count}: кластер {c.upper()}"
        return self._section(title, lines)

    def _k8s_section(self, k8s: KubernetesCluster, months: Decimal) -> Section:
        nodes = Decimal(k8s.nodes) * months
        lines: list[LineItem | None] = [
            self._line("k8s.cp_ha" if k8s.ha_control_plane else "k8s.cp_single", months),
            self._line("k8s.vcpu", k8s.node_vcpu * nodes),
            self._line("k8s.ram_gb", k8s.node_ram_gb * nodes),
            self._line(f"k8s.disk.{k8s.node_disk_type}", k8s.node_disk_gb * nodes),
            self._line("k8s.pv.ssd", k8s.pv_ssd_gb * months),
            self._line("k8s.pv.sata", k8s.pv_sata_gb * months),
            self._line("k8s.ip", k8s.public_ips * months),
        ]
        if k8s.managed_nodes:
            lines.append(self._line("k8s.node_admin", nodes))
        title = f"Kubernetes «{k8s.name}»: {k8s.nodes} узлов × {k8s.node_vcpu} vCPU / {k8s.node_ram_gb} ГБ"
        return self._section(title, lines)

    def _db_section(self, db: ManagedDatabase, months: Decimal) -> Section:
        n = Decimal(db.count) * months
        lines: list[LineItem | None] = [
            self._line("db.vcpu", db.vcpu * n),
            self._line("db.ram_gb", db.ram_gb * n),
            self._line(f"db.disk.{db.disk_type}", db.disk_gb * n),
            self._line("db.ip", db.public_ips * n),
        ]
        if db.managed:
            lines.append(self._line("db.admin", n))
        if db.backup_copies_gb:
            if db.engine not in _DB_ENGINES_WITH_BACKUP:
                raise ValueError(f"Для СУБД {db.engine} хранение резервных копий не тарифицируется")
            lines.append(self._line("db.backup_copy_gb", db.backup_copies_gb * n))
        title = f"СУБД «{db.name}» ({db.engine}) × {db.count}: {db.vcpu} vCPU, {db.ram_gb} ГБ RAM"
        return self._section(title, lines)

    def _s3_section(self, s3: ObjectStorage, months: Decimal) -> Section:
        lines: list[LineItem | None]
        if s3.tier == "fixed":
            lines = [self._line("s3.fixed_gb", s3.storage_gb * months)]
        else:
            t = "std" if s3.tier == "standard" else "cold"
            lines = [
                self._line(f"s3.{t}_gb", s3.storage_gb * months),
                self._line(f"s3.{t}_egress_gb", s3.egress_gb_per_month * months),
                self._line(f"s3.{t}_put", s3.put_requests_per_month * months),
                self._line(f"s3.{t}_get", s3.get_requests_per_month * months),
            ]
        title = f"Объектное хранилище «{s3.name}» ({s3.tier}): {s3.storage_gb} ГБ"
        return self._section(title, lines)

    def _backup_section(self, backup: Backup, months: Decimal) -> Section:
        lines = [
            self._line("backup.protected_gb", backup.protected_gb * months),
            self._line("backup.stored_gb", backup.stored_copies_gb * months),
        ]
        return self._section(f"Резервное копирование: {backup.protected_gb} ГБ", lines)

    def _inference_section(self, job: InferenceWorkload, months: Decimal) -> Section:
        hours = Decimal(job.hours_per_month) * months
        lines = [
            self._line("inference.h200_vram_gb_hour", job.vram_gb * hours),
            self._line("inference.ssd_gb_hour", job.ssd_gb * hours),
        ]
        title = f"Inference Platform «{job.name}»: {job.vram_gb} ГБ VRAM, {job.hours_per_month} ч/мес"
        return self._section(title, lines)

    def _network_section(self, net: Network, months: Decimal) -> Section:
        lines: list[LineItem | None] = [self._line("net.ip", net.public_ips * months)]
        if net.bandwidth_mbps:
            lines.append(self._line(f"net.bw_{net.bandwidth_mbps}", months))
        return self._section("Сетевые сервисы", lines)

    def _disk_lines(self, prefix: str, disks: list[DiskSpec], n: Decimal) -> list[LineItem | None]:
        """Группирует диски по типу и создаёт по одной строке на тип."""
        totals: dict[str, int] = {}
        for disk in disks:
            totals[disk.type] = totals.get(disk.type, 0) + disk.size_gb
        return [self._line(f"{prefix}.{t}", size * n) for t, size in sorted(totals.items())]
