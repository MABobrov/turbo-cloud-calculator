"""Модели данных калькулятора.

Входные модели описывают конфигурацию облачных ресурсов клиента.
Выходные модели описывают смету: строки, разделы, итоги и НДС.
Все денежные значения — ``Decimal`` с двумя знаками после запятой.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DiskType = Literal["sata", "sas", "ssd"]
OsLicense = Literal["astra_voronezh", "astra_orel", "alt_server_10", "alt8_sp", "redos_std", "redos_fstec"]
GpuCluster = Literal["l40s", "l4", "h200"]
H200Profile = Literal["mig_1g_35gb", "mig_2g_35gb", "mig_3g_71gb", "mig_4g_71gb", "full"]
S3Tier = Literal["standard", "cold", "fixed"]
DbEngine = Literal[
    "postgresql",
    "mysql",
    "pangolin",
    "mongodb",
    "redis",
    "clickhouse",
    "qdrant",
    "rabbitmq",
    "kafka",
    "tarantool",
]
Bandwidth = Literal[
    5,
    10,
    20,
    50,
    100,
    200,
    300,
    400,
    500,
    600,
    700,
    800,
    900,
    1000,
    2000,
    3000,
    4000,
    5000,
    10000,
]

PositiveInt = Annotated[int, Field(ge=1)]
NonNegInt = Annotated[int, Field(ge=0)]
Name = Annotated[str, Field(min_length=1, max_length=80)]


class StrictModel(BaseModel):
    """Базовая модель: запрещает неизвестные поля."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- вход


class DiskSpec(StrictModel):
    """Диск виртуальной машины или узла."""

    type: DiskType = "ssd"
    size_gb: Annotated[int, Field(ge=1, le=65_536)]


class VirtualMachine(StrictModel):
    """Виртуальная машина в сегменте «Виртуальная инфраструктура»."""

    name: Name = "vm"
    count: Annotated[int, Field(ge=1, le=1_000)] = 1
    vcpu: Annotated[int, Field(ge=1, le=256)]
    ram_gb: Annotated[int, Field(ge=1, le=4_096)]
    high_capacity: bool = False
    disks: Annotated[list[DiskSpec], Field(min_length=1, max_length=32)]
    os: OsLicense | None = None
    public_ips: Annotated[int, Field(ge=0, le=64)] = 0


class GpuVirtualMachine(StrictModel):
    """Виртуальная машина с GPU.

    Для кластеров ``l40s`` и ``l4`` укажите ``vram_gb``.
    Для кластера ``h200`` укажите ``h200_profile`` и ``h200_cards``.
    """

    name: Name = "gpu-vm"
    count: Annotated[int, Field(ge=1, le=100)] = 1
    cluster: GpuCluster
    vcpu: Annotated[int, Field(ge=1, le=256)]
    ram_gb: Annotated[int, Field(ge=1, le=4_096)]
    vram_gb: Annotated[int, Field(ge=0, le=4_096)] = 0
    h200_profile: H200Profile | None = None
    h200_cards: Annotated[int, Field(ge=0, le=64)] = 0
    disks: Annotated[list[DiskSpec], Field(min_length=1, max_length=32)]
    public_ips: Annotated[int, Field(ge=0, le=64)] = 0

    @model_validator(mode="after")
    def _check_gpu_fields(self) -> GpuVirtualMachine:
        if self.cluster == "h200":
            if not self.h200_profile or self.h200_cards < 1:
                raise ValueError("Для кластера h200 укажите h200_profile и h200_cards >= 1")
            if self.vram_gb:
                raise ValueError("Для кластера h200 поле vram_gb не используется")
        else:
            if self.vram_gb < 1:
                raise ValueError(f"Для кластера {self.cluster} укажите vram_gb >= 1")
            if self.h200_profile or self.h200_cards:
                raise ValueError("Поля h200_* используются только для кластера h200")
        for disk in self.disks:
            if disk.type == "sas":
                raise ValueError("Для GPUaaS доступны только диски ssd и sata")
        return self


class ObjectStorage(StrictModel):
    """Объектное хранилище S3. Запросы и трафик указаны за один месяц."""

    name: Name = "s3"
    tier: S3Tier = "standard"
    storage_gb: Annotated[int, Field(ge=1, le=10_000_000)]
    egress_gb_per_month: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    put_requests_per_month: Annotated[int, Field(ge=0, le=10**12)] = 0
    get_requests_per_month: Annotated[int, Field(ge=0, le=10**12)] = 0

    @model_validator(mode="after")
    def _check_fixed_tier(self) -> ObjectStorage:
        if self.tier == "fixed" and (
            self.egress_gb_per_month or self.put_requests_per_month or self.get_requests_per_month
        ):
            raise ValueError("Для тарифа fixed запросы и трафик не тарифицируются отдельно")
        return self


class Backup(StrictModel):
    """Резервное копирование виртуальных машин."""

    protected_gb: Annotated[int, Field(ge=1, le=10_000_000)]
    stored_copies_gb: Annotated[int, Field(ge=0, le=100_000_000)] = 0


class KubernetesCluster(StrictModel):
    """Управляемый кластер Kubernetes."""

    name: Name = "k8s"
    ha_control_plane: bool = True
    nodes: Annotated[int, Field(ge=1, le=500)]
    node_vcpu: Annotated[int, Field(ge=1, le=128)]
    node_ram_gb: Annotated[int, Field(ge=1, le=1_024)]
    node_disk_type: Literal["ssd", "sas"] = "ssd"
    node_disk_gb: Annotated[int, Field(ge=1, le=16_384)] = 50
    pv_ssd_gb: Annotated[int, Field(ge=0, le=1_000_000)] = 0
    pv_sata_gb: Annotated[int, Field(ge=0, le=1_000_000)] = 0
    public_ips: Annotated[int, Field(ge=0, le=64)] = 1
    managed_nodes: bool = False


class ManagedDatabase(StrictModel):
    """Управляемая СУБД или брокер сообщений."""

    name: Name = "db"
    engine: DbEngine = "postgresql"
    count: Annotated[int, Field(ge=1, le=100)] = 1
    vcpu: Annotated[int, Field(ge=1, le=128)]
    ram_gb: Annotated[int, Field(ge=1, le=1_024)]
    disk_type: Literal["sas", "ssd"] = "ssd"
    disk_gb: Annotated[int, Field(ge=1, le=65_536)]
    public_ips: Annotated[int, Field(ge=0, le=16)] = 0
    managed: bool = True
    backup_copies_gb: Annotated[int, Field(ge=0, le=1_000_000)] = 0


class InferenceWorkload(StrictModel):
    """Нагрузка на Inference Platform с почасовой тарификацией."""

    name: Name = "inference"
    vram_gb: Annotated[int, Field(ge=1, le=4_096)]
    ssd_gb: Annotated[int, Field(ge=0, le=100_000)] = 0
    hours_per_month: Annotated[int, Field(ge=1, le=744)] = 720


class Network(StrictModel):
    """Сетевые сервисы, общие для конфигурации."""

    public_ips: Annotated[int, Field(ge=0, le=256)] = 0
    bandwidth_mbps: Bandwidth | None = None


class Configuration(StrictModel):
    """Конфигурация облачных ресурсов для расчёта стоимости."""

    customer: Annotated[str, Field(max_length=200)] | None = None
    months: Annotated[int, Field(ge=1, le=36)] = 1
    discount_percent: Annotated[Decimal, Field(ge=0, le=50, decimal_places=2)] = Decimal(0)
    vat_percent: Annotated[Decimal, Field(ge=0, le=30, decimal_places=2)] = Decimal(22)
    vms: list[VirtualMachine] = Field(default_factory=list, max_length=200)
    gpu_vms: list[GpuVirtualMachine] = Field(default_factory=list, max_length=50)
    object_storage: list[ObjectStorage] = Field(default_factory=list, max_length=20)
    backup: Backup | None = None
    kubernetes: list[KubernetesCluster] = Field(default_factory=list, max_length=20)
    databases: list[ManagedDatabase] = Field(default_factory=list, max_length=50)
    inference: list[InferenceWorkload] = Field(default_factory=list, max_length=20)
    network: Network = Field(default_factory=Network)

    @model_validator(mode="after")
    def _check_not_empty(self) -> Configuration:
        has_resources = any(
            (
                self.vms,
                self.gpu_vms,
                self.object_storage,
                self.backup,
                self.kubernetes,
                self.databases,
                self.inference,
                self.network.public_ips,
                self.network.bandwidth_mbps,
            )
        )
        if not has_resources:
            raise ValueError("Конфигурация не содержит ресурсов")
        return self


# ---------------------------------------------------------------- выход


class LineItem(BaseModel):
    """Строка сметы."""

    sku: str
    name: str
    unit: str
    period: Literal["month", "hour", "once"]
    quantity: Decimal = Field(description="Количество за весь срок")
    unit_price: Decimal = Field(description="Цена за единицу без НДС")
    amount: Decimal = Field(description="Сумма за весь срок без НДС")


class Section(BaseModel):
    """Раздел сметы: один ресурс конфигурации."""

    title: str
    lines: list[LineItem]
    subtotal: Decimal


class Estimate(BaseModel):
    """Смета: разделы, итоги, НДС и метаданные прайс-листа."""

    customer: str | None
    months: int
    currency: str
    pricelist_source: str
    pricelist_captured_at: str
    sections: list[Section]
    subtotal: Decimal = Field(description="Сумма разделов без НДС и скидки")
    discount_percent: Decimal
    discount_amount: Decimal
    total_ex_vat: Decimal
    vat_percent: Decimal
    vat_amount: Decimal
    total: Decimal = Field(description="Итого с НДС за весь срок")
    monthly_ex_vat: Decimal = Field(description="Среднемесячный платёж без НДС после скидки")
