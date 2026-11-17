"""Модели данных: устройства, система, найденные драйверы, оценка необходимости."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class Necessity(str, Enum):
    REQUIRED = "required"        # без драйвера устройство не работает или работает плохо
    RECOMMENDED = "recommended"  # работает, но обновление заметно полезно
    OPTIONAL = "optional"        # работает нормально, обновление по желанию
    NOT_NEEDED = "not_needed"    # ничего делать не нужно

    @property
    def label(self) -> str:
        return {
            Necessity.REQUIRED: "НЕОБХОДИМО",
            Necessity.RECOMMENDED: "РЕКОМЕНДУЕТСЯ",
            Necessity.OPTIONAL: "НЕОБЯЗАТЕЛЬНО",
            Necessity.NOT_NEEDED: "НЕ ТРЕБУЕТСЯ",
        }[self]

    @property
    def rank(self) -> int:
        return [Necessity.REQUIRED, Necessity.RECOMMENDED,
                Necessity.OPTIONAL, Necessity.NOT_NEEDED].index(self)


class Action(str, Enum):
    INSTALL = "install"  # драйвера нет / стоит базовый — нужно поставить
    UPDATE = "update"    # есть более новая версия
    REPAIR = "repair"    # драйвер правильный, но устройство сбоит — помогает перезапуск
    NONE = "none"

    @property
    def label(self) -> str:
        return {Action.INSTALL: "установить", Action.UPDATE: "обновить",
                Action.REPAIR: "исправить", Action.NONE: "—"}[self]


@dataclass
class SystemInfo:
    manufacturer: str = ""
    model: str = ""
    board: str = ""
    bios: str = ""
    cpu: str = ""
    ram_gb: float = 0.0
    gpus: list[str] = field(default_factory=list)
    os_name: str = ""
    os_version: str = ""
    os_build: int = 0
    arch: str = ""  # x64 / x86 / arm64
    board_maker: str = ""
    board_product: str = ""
    pc_type: int = 0  # 1 — настольный, 2 — ноутбук (Win32_ComputerSystem.PCSystemType)

    @property
    def is_windows11(self) -> bool:
        return self.os_build >= 22000


@dataclass
class Device:
    instance_id: str
    name: str
    device_class: str = ""
    manufacturer: str = ""
    hardware_ids: list[str] = field(default_factory=list)
    compatible_ids: list[str] = field(default_factory=list)
    problem_code: int = 0
    status: str = ""
    driver_version: str = ""
    driver_date: str = ""      # YYYY-MM-DD
    driver_provider: str = ""
    inf_name: str = ""
    is_signed: bool | None = None

    @property
    def has_driver(self) -> bool:
        return bool(self.inf_name or self.driver_version)

    @property
    def all_ids(self) -> list[str]:
        return self.hardware_ids + self.compatible_ids

    @property
    def is_virtual(self) -> bool:
        iid = self.instance_id.upper()
        return iid.startswith(("SWD\\", "ROOT\\", "HTREE\\", "STORAGE\\VOLUME",
                               "UMB\\", "BTHLEDEVICE\\", "BTHENUM\\{"))

    def matches_hwid(self, hwid: str) -> bool:
        h = hwid.upper()
        return any(i.upper() == h for i in self.all_ids)


@dataclass
class DriverOffer:
    """Драйвер, найденный в официальном источнике."""
    source: str             # "windows_update" | "catalog"
    title: str
    version: str = ""
    date: str = ""          # YYYY-MM-DD
    hardware_id: str = ""
    provider: str = ""
    driver_class: str = ""
    products: str = ""      # для каталога: «Windows 10 and later drivers» и т.п.
    update_id: str = ""     # GUID в Windows Update / Update Catalog (или версия у производителя)
    download_url: str = ""  # прямая ссылка (для драйверов с сайта производителя)
    known_newer: bool = False  # источник уже сам сверил версии (сайт NVIDIA) — сравнивать не нужно
    size_bytes: int = 0
    is_firmware: bool = False
    reboot_required: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Assessment:
    device: Device
    necessity: Necessity
    action: Action
    reason: str
    offer: DriverOffer | None = None
    manual_hint: str = ""   # ссылка на официальный сайт, если автоматом не нашли
    auto_install: bool = True  # False — ставить только вручную (например, BIOS)
    repairable: bool = False   # можно попробовать перезапустить устройство

    def to_dict(self) -> dict:
        return {
            "device": asdict(self.device),
            "necessity": self.necessity.value,
            "action": self.action.value,
            "reason": self.reason,
            "offer": self.offer.to_dict() if self.offer else None,
            "manual_hint": self.manual_hint,
            "auto_install": self.auto_install,
            "repairable": self.repairable,
        }
