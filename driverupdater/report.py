"""Вывод результатов в консоль."""

from __future__ import annotations

from . import classify
from .models import Action, Assessment, Necessity, SystemInfo

SOURCE_NAMES = {"windows_update": "Windows Update", "catalog": "Microsoft Update Catalog"}


def fmt_size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def print_system(s: SystemInfo) -> None:
    print("=" * 72)
    print(f" Компьютер : {s.manufacturer} {s.model}".rstrip())
    print(f" Плата     : {s.board}")
    print(f" BIOS      : {s.bios}")
    print(f" Процессор : {s.cpu}")
    print(f" Память    : {s.ram_gb:g} ГБ")
    for g in s.gpus:
        print(f" Видео     : {g}")
    print(f" Система   : {s.os_name} (сборка {s.os_build}, {s.arch})")
    print("=" * 72)


def print_assessments(items: list[Assessment], show_all: bool = False) -> None:
    groups: dict[Necessity, list[Assessment]] = {n: [] for n in Necessity}
    for a in items:
        if not show_all and a.device.is_virtual and a.action == Action.NONE:
            continue
        groups[a.necessity].append(a)

    for nec, group in groups.items():
        if not group:
            continue
        print(f"\n■ {nec.label} — {len(group)}")
        if nec == Necessity.NOT_NEEDED and not show_all:
            print("  (драйверы в порядке; подробный список: --all)")
            continue
        for a in group:
            d = a.device
            cls = classify.effective_class(d, a.offer) or "?"
            print(f"  • {d.name or d.instance_id}  [{cls}]")
            if d.driver_version:
                print(f"      сейчас    : {d.driver_version} от {d.driver_date or '?'} ({d.driver_provider})")
            if a.offer:
                o = a.offer
                size = f", {fmt_size(o.size_bytes)}" if o.size_bytes else ""
                print(f"      {a.action.label:<10}: {o.title} — {SOURCE_NAMES.get(o.source, o.source)}{size}")
            elif a.action != Action.NONE:
                print(f"      {a.action.label:<10}: в официальных каталогах Microsoft не найден")
            print(f"      почему    : {a.reason}")
            if not a.auto_install:
                print("      ⚠ автоматически не устанавливается (только вручную или с --allow-firmware)")
            if a.manual_hint and not a.offer:
                print(f"      вручную   : {a.manual_hint}")
            elif a.manual_hint and d.device_class == "Display":
                print(f"      самая свежая версия — на сайте производителя: {a.manual_hint}")


def print_plan(plan: list[Assessment]) -> None:
    if not plan:
        print("\nУстанавливать нечего.")
        return
    total = sum(a.offer.size_bytes for a in plan if a.offer)
    print(f"\nБудет установлено драйверов: {len(plan)} (примерно {fmt_size(total)})")
    for i, a in enumerate(plan, 1):
        print(f"  {i}. [{a.necessity.label}] {a.device.name} → {a.offer.title}")  # type: ignore[union-attr]
