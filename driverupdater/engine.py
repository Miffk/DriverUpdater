"""Общая логика для консольной и графической версии: сканирование → поиск → оценка → план."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import classify, hardware, powershell
from .models import Action, Assessment, Device, DriverOffer, Necessity, SystemInfo
from .providers import catalog, windows_update

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
        targets = []
        for d in devices:
            if d.instance_id in by_device or d.is_virtual:
                continue
            a = classify.assess(d, None)
            wants = a.action != Action.NONE and a.necessity in (Necessity.REQUIRED, Necessity.RECOMMENDED)
            is_deep = deep and classify.effective_class(d) in classify.RULES and d.hardware_ids
            if wants or is_deep:
                targets.append(d)
        if targets:
            log(f"Поиск в Microsoft Update Catalog для {len(targets)} устройств(а)…")
        for d in targets:
            log(f"  {d.name}")
            off = catalog.find_for_device(d, system)
            if off:
                by_device[d.instance_id] = off
                log(f"    найдено: {off.title}")
    return by_device, unmatched


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
