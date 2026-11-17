"""Командная строка DriverUpdater."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, classify, hardware, installer, powershell, report
from .models import Action, Assessment, Device, DriverOffer, Necessity, SystemInfo
from .providers import catalog, windows_update


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="driverupdater",
        description="Определяет комплектующие ПК, находит драйверы в официальных источниках "
                    "Microsoft, устанавливает их и удаляет установочные файлы.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--from-file", metavar="FILE", help="взять данные о железе из снимка (для отладки)")
        sp.add_argument("--save", metavar="FILE", help="сохранить снимок железа в файл")
        sp.add_argument("--all", action="store_true", help="показать все устройства, включая исправные")
        sp.add_argument("--json", action="store_true", help="вывод в формате JSON")

    def online(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--offers-file", metavar="FILE",
                        help="взять результаты Windows Update из файла вместо онлайн-поиска (для отладки)")
        sp.add_argument("--no-catalog", action="store_true",
                        help="не искать в Microsoft Update Catalog")
        sp.add_argument("--deep", action="store_true",
                        help="искать в каталоге обновления для всех важных устройств (дольше)")

    common(sub.add_parser("scan", help="только определить железо и драйверы (без интернета)"))
    chk = sub.add_parser("check", help="найти, какие драйверы нужно установить или обновить")
    common(chk)
    online(chk)
    ins = sub.add_parser("install", help="скачать и установить драйверы, затем удалить файлы")
    common(ins)
    online(ins)
    ins.add_argument("--include-optional", action="store_true", help="ставить и необязательные")
    ins.add_argument("--allow-firmware", action="store_true", help="разрешить обновления прошивок (BIOS/UEFI)")
    ins.add_argument("-y", "--yes", action="store_true", help="не спрашивать подтверждения")
    ins.add_argument("--dry-run", action="store_true", help="показать план, ничего не устанавливая")
    ins.add_argument("--skip-restore-point", action="store_true", help="не создавать точку восстановления")
    ins.add_argument("--backup-dir", metavar="DIR", help="сохранить копию текущих драйверов в папку")
    return p


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def gather_offers(args, system: SystemInfo, devices: list[Device]
                  ) -> tuple[dict[str, DriverOffer], list[DriverOffer]]:
    if args.offers_file:
        raw = json.loads(Path(args.offers_file).read_text(encoding="utf-8-sig"))
        offers = windows_update.parse_search(raw)
    else:
        log("Поиск драйверов в Windows Update (может занять пару минут)…")
        try:
            offers = windows_update.search()
        except powershell.PowerShellError as e:
            log(f"  Windows Update недоступен: {e}")
            offers = []
    by_device, unmatched = classify.match_offers(devices, offers)

    if not args.no_catalog and not args.offers_file:
        targets = []
        for d in devices:
            if d.instance_id in by_device or d.is_virtual:
                continue
            a = classify.assess(d, None)
            wants = a.action != Action.NONE and a.necessity in (Necessity.REQUIRED, Necessity.RECOMMENDED)
            deep = args.deep and classify.effective_class(d) in classify.RULES and d.hardware_ids
            if wants or deep:
                targets.append(d)
        if targets:
            log(f"Поиск в Microsoft Update Catalog для {len(targets)} устройств(а)…")
        for d in targets:
            off = catalog.find_for_device(d, system)
            if off:
                by_device[d.instance_id] = off
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


def select_plan(items: list[Assessment], include_optional: bool, allow_firmware: bool) -> list[Assessment]:
    allowed = {Necessity.REQUIRED, Necessity.RECOMMENDED}
    if include_optional:
        allowed.add(Necessity.OPTIONAL)
    plan = [a for a in items
            if a.offer and a.action != Action.NONE and a.necessity in allowed
            and (a.auto_install or allow_firmware)]
    # Сначала чипсет и системные устройства, затем остальное — так советуют производители.
    order = {"System": 0, "HDC": 1, "SCSIAdapter": 1, "Display": 2, "Net": 3}
    plan.sort(key=lambda a: (order.get(classify.effective_class(a.device, a.offer), 9),
                             a.necessity.rank))
    # Один пакет может подходить к нескольким устройствам — ставим один раз.
    seen, unique = set(), []
    for a in plan:
        key = (a.offer.source, a.offer.update_id)  # type: ignore[union-attr]
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique


def confirm(question: str) -> bool:
    try:
        return input(f"{question} [y/N]: ").strip().lower() in ("y", "yes", "д", "да")
    except EOFError:
        return False


def main(argv: list[str] | None = None) -> int:
    if os.name == "nt":
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
            sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)

    try:
        system, devices = hardware.scan(args.from_file, args.save)
    except (powershell.PowerShellError, OSError, ValueError) as e:
        log(f"Ошибка сканирования: {e}")
        return 2

    offers: dict[str, DriverOffer] = {}
    extra: list[Assessment] = []
    if args.command in ("check", "install"):
        offers, unmatched = gather_offers(args, system, devices)
        extra = unmatched_assessments(unmatched)

    items = classify.assess_all(devices, offers, searched=args.command != "scan") + extra

    if args.json:
        print(json.dumps({"system": system.__dict__, "devices": [a.to_dict() for a in items]},
                         ensure_ascii=False, indent=2))
    else:
        report.print_system(system)
        report.print_assessments(items, show_all=args.all)

    if args.command != "install":
        return 0

    plan = select_plan(items, args.include_optional, args.allow_firmware)
    report.print_plan(plan)
    if not plan or args.dry_run:
        return 0
    if not installer.is_admin():
        log("\nДля установки драйверов запустите программу от имени администратора.")
        return 3
    if not args.yes and not confirm("\nУстановить?"):
        return 0

    if args.backup_dir:
        log(f"Резервная копия текущих драйверов → {args.backup_dir}")
        try:
            installer.backup_drivers(args.backup_dir)
        except RuntimeError as e:
            log(f"  не удалось: {e}")
            if not confirm("Продолжить без резервной копии?"):
                return 1
    if not args.skip_restore_point:
        log("Создание точки восстановления системы…")
        try:
            installer.create_restore_point()
        except powershell.PowerShellError as e:
            log(f"  не удалось создать точку восстановления: {e}")
            if args.yes or not confirm("Продолжить без точки восстановления?"):
                log("Отменено. Используйте --skip-restore-point, если защита системы отключена намеренно.")
                return 1

    result = installer.install(plan, log=log)
    ok = sum(r.ok for r in result.results)
    print(f"\nГотово: успешно {ok} из {len(result.results)}.")
    for r in result.results:
        print(f"  {'✔' if r.ok else '✘'} {r.name}: {r.message}")
    print(f"Удалено установочных файлов: {report.fmt_size(result.cleaned_bytes)}")
    if result.reboot_required:
        print("⚠ Для завершения установки перезагрузите компьютер.")
    return 0 if ok == len(result.results) else 1
