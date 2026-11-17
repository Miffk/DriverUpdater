"""Общая логика для консольной и графической версии: сканирование → поиск → оценка → план."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import classify, hardware, powershell
from .versions import is_newer
from .models import Action, Assessment, Device, DriverOffer, Necessity, SystemInfo
from . import names, vendors
from .providers import catalog, nvidia, windows_update

Log = Callable[[str], None]


def _noop(_: str) -> None:
    pass


@dataclass
class ScanResult:
    system: SystemInfo
    devices: list[Device]
    items: list[Assessment] = field(default_factory=list)
    searched: bool = False


def scan(from_file: str | None = None, save_to: str | None = None) -> ScanResult:
    system, devices = hardware.scan(from_file, save_to)
    return ScanResult(system, devices, classify.assess_all(devices, {}, searched=False))


def find_offers(system: SystemInfo, devices: list[Device], *, offers_file: str | None = None,
                use_catalog: bool = True, deep: bool = False, log: Log = _noop
                ) -> tuple[dict[str, DriverOffer], list[DriverOffer]]:
    if offers_file:
        raw = json.loads(Path(offers_file).read_text(encoding="utf-8-sig"))
        offers = windows_update.parse_search(raw)
    else:
        log("Поиск драйверов в Windows Update (может занять пару минут)…")
        try:
            offers = windows_update.search()
            log(f"  Windows Update: найдено предложений — {len(offers)}")
        except powershell.PowerShellError as e:
            log(f"  Windows Update недоступен: {e}")
            offers = []
    by_device, unmatched = classify.match_offers(devices, offers)

    if use_catalog and not offers_file:
        _check_catalog(system, devices, by_device, deep, log)
    if not offers_file:
        _check_nvidia(system, devices, by_device, log)
    return by_device, unmatched


def catalog_targets(devices: list[Device], by_device: dict[str, DriverOffer], deep: bool) -> list[Device]:
    """Для каких устройств искать в каталоге Microsoft.

    Каталог содержит гораздо больше драйверов, чем Windows Update предлагает сам, поэтому
    проверяем все настоящие устройства, кроме тех, где правильный — стандартный драйвер Windows
    (USB-разъёмы, клавиатуры, мыши, диски…) и всё работает."""
    out = []
    for d in devices:
        if d.instance_id in by_device or d.is_virtual or not d.hardware_ids:
            continue
        if d.problem_code in classify.IGNORED_PROBLEMS:
            continue
        cls = classify.effective_class(d)
        broken = d.problem_code != 0 or not d.has_driver or classify.is_basic_display(d)
        if not broken and cls in classify.INBOX_CLASSES and classify.is_microsoft_driver(d):
            continue
        if not broken and not deep and not vendors.bus(d) and cls not in classify.RULES:
            continue  # служебные устройства ACPI/ROOT без производителя
        out.append(d)
    return out


def _check_catalog(system: SystemInfo, devices: list[Device], by_device: dict[str, DriverOffer],
                   deep: bool, log: Log) -> None:
    targets = catalog_targets(devices, by_device, deep)
    if not targets:
        return
    log(f"Поиск в каталоге Microsoft для {len(targets)} устройств(а)…")
    # Одинаковые устройства (например, несколько одинаковых USB-портов) ищем один раз.
    groups: dict[tuple[str, ...], list[Device]] = {}
    for d in targets:
        groups.setdefault(tuple(h.upper() for h in d.hardware_ids[:3]), []).append(d)

    def work(group: list[Device]):
        try:
            return group, catalog.find_for_device(group[0], system)
        except Exception:  # noqa: BLE001 — сбой сети по одному устройству не должен ронять поиск
            return group, None

    found = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for group, off in pool.map(work, groups.values()):
            if not off:
                continue
            for d in group:
                if is_newer(off.version, off.date, d.driver_version, d.driver_date) or not d.has_driver \
                        or d.problem_code or classify.is_basic_display(d):
                    by_device[d.instance_id] = off
                    found += 1
            log(f"  {group[0].name}: {off.title}")
    log(f"  каталог Microsoft: подходящих драйверов — {found}")


def _check_nvidia(system: SystemInfo, devices: list[Device], by_device: dict[str, DriverOffer],
                  log: Log) -> None:
    """Видеокарты NVIDIA: свежий драйвер с сайта NVIDIA (в Windows Update он появляется позже)."""
    gpus = [d for d in devices if classify.effective_class(d) == "Display"
            and vendors.vendor_id(d) == "10DE" and d.problem_code not in classify.IGNORED_PROBLEMS]
    for d in gpus:
        name = d.name if not classify.is_basic_display(d) else vendors.model_name(d)
        if not name:
            continue
        log(f"Проверяю сайт NVIDIA для {name}…")
        off = nvidia.find_update(d, system, name)
        if not off:
            log("  на сайте NVIDIA новее нет")
            continue
        ms = by_device.get(d.instance_id)
        ms_ver = nvidia.windows_to_nvidia(ms.version) if ms else ""
        if ms and ms_ver and nvidia._ver(ms_ver) >= nvidia._ver(off.version):
            continue  # в Windows Update не хуже
        by_device[d.instance_id] = off
        log(f"  найдено: {off.title}")


def unmatched_assessments(offers: list[DriverOffer]) -> list[Assessment]:
    out = []
    for o in offers:
        dev = Device(instance_id=o.hardware_id or o.update_id, name=o.title,
                     device_class=o.driver_class, hardware_ids=[o.hardware_id])
        out.append(Assessment(
            dev, Necessity.OPTIONAL, Action.UPDATE,
            "Windows Update предлагает этот драйвер, но соответствующее устройство сейчас не "
            "активно (отключено или не подключено) — ставить не обязательно.",
            offer=o, auto_install=not o.is_firmware))
    return out


def check(from_file: str | None = None, save_to: str | None = None, *,
          offers_file: str | None = None, use_catalog: bool = True, deep: bool = False,
          log: Log = _noop) -> ScanResult:
    log("Определение оборудования…")
    system, devices = hardware.scan(from_file, save_to)
    log(f"  устройств: {len(devices)}")
    offers, unmatched = find_offers(system, devices, offers_file=offers_file,
                                    use_catalog=use_catalog, deep=deep, log=log)
    items = classify.assess_all(devices, offers) + unmatched_assessments(unmatched)
    return ScanResult(system, devices, items, searched=True)


def is_installable(a: Assessment, allow_firmware: bool = False) -> bool:
    return bool(a.offer) and a.action != Action.NONE and (a.auto_install or allow_firmware)


def default_selected(a: Assessment) -> bool:
    """Что отмечается галочкой по умолчанию: необходимое и рекомендуемое."""
    return is_installable(a) and a.necessity in (Necessity.REQUIRED, Necessity.RECOMMENDED)


def order_plan(plan: list[Assessment]) -> list[Assessment]:
    # Сначала чипсет, потом контроллеры дисков, видеокарта, сеть — так советуют производители.
    order = {"System": 0, "HDC": 1, "SCSIAdapter": 1, "Display": 2, "Net": 3}
    plan = sorted(plan, key=lambda a: (order.get(classify.effective_class(a.device, a.offer), 9),
                                       a.necessity.rank))
    # Один пакет может подходить к нескольким устройствам — ставим один раз.
    seen, unique = set(), []
    for a in plan:
        key = (a.offer.source, a.offer.update_id)  # type: ignore[union-attr]
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique


def select_plan(items: list[Assessment], include_optional: bool, allow_firmware: bool) -> list[Assessment]:
    allowed = {Necessity.REQUIRED, Necessity.RECOMMENDED}
    if include_optional:
        allowed.add(Necessity.OPTIONAL)
    return order_plan([a for a in items
                       if is_installable(a, allow_firmware) and a.necessity in allowed])


def gpu_names(devices: list[Device]) -> list[str]:
    """Понятные названия видеокарт. Если драйвера нет — название берём из базы по коду устройства."""
    out = []
    for d in devices:
        if classify.effective_class(d) != "Display" or d.is_virtual:
            continue
        if d.problem_code in classify.IGNORED_PROBLEMS:
            continue
        if classify.is_basic_display(d) or not d.has_driver:
            model = vendors.model_name(d)
            vendor = vendors.vendor_name(d)
            if model and vendor and not model.lower().startswith(vendor.lower()):
                model = f"{vendor} {model}"
            out.append(f"{model or vendor or 'Видеокарта'} — драйвер не установлен")
        else:
            out.append(names.pretty_cpu(d.name))  # та же чистка: убирает (TM), (R)
    return out


def describe_system(s: SystemInfo, devices: list[Device] | None = None) -> dict[str, str]:
    """Сводка о компьютере простыми словами — для окна и консоли."""
    maker = names.brand(s.manufacturer)
    model = names.pretty_model(s.model, s.manufacturer)
    board_maker = names.brand(s.board_maker) if s.board_maker else maker
    board_model = names.pretty_model(s.board_product) if s.board_product else names.pretty_model(
        s.board[len(s.manufacturer):].strip() if s.manufacturer and s.board.startswith(s.manufacturer) else s.board,
        s.board_maker or s.manufacturer)
    if names.is_board_code(s.model) or (model and board_model and model.lower() == board_model.lower()):
        model = ""
    if s.pc_type == 2:
        computer = " ".join(x for x in ("Ноутбук", maker, model) if x)
    elif model:
        computer = f"{maker} {model}".strip()
    else:
        computer = " ".join(x for x in ("Настольный ПК", maker) if x)
    gpus = gpu_names(devices) if devices else []
    if not gpus:
        gpus = [names.pretty_cpu(g) for g in s.gpus]
    return {
        "computer": computer,
        "cpu": names.pretty_cpu(s.cpu),
        "gpus": ", ".join(gpus),
        "gpuCount": str(len(gpus)),
        "ram": names.pretty_ram(s.ram_gb),
        "board": " ".join(x for x in (board_maker, board_model) if x),
        "os": names.pretty_os(s.os_name, s.os_build, s.arch),
    }
