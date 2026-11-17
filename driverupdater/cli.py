"""Командная строка DriverUpdater."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, engine, installer, powershell, report, updater


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

    sub.add_parser("self-update", help="обновить саму программу до последней версии с GitHub")
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
    if sys.stderr:
        print(msg, file=sys.stderr, flush=True)


def self_update() -> int:
    try:
        info = updater.check()
    except OSError as e:
        log(f"Не удалось связаться с GitHub: {e}")
        return 2
    if not info["available"]:
        print(f"У вас последняя версия ({__version__}).")
        return 0
    print(f"Доступна версия {info['version']} (у вас {__version__}).")
    if not info["canAutoUpdate"]:
        print(f"Скачайте её здесь: {info['page']}")
        return 0
    try:
        updater.apply(info, log)
    except (OSError, RuntimeError) as e:
        log(f"Обновить не удалось: {e}. Скачайте вручную: {info['page']}")
        return 1
    print("Готово. Запустите программу снова.")
    return 0


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
    updater.cleanup_old()
    if args.command == "self-update":
        return self_update()

    try:
        if args.command == "scan":
            res = engine.scan(args.from_file, args.save)
        else:
            res = engine.check(args.from_file, args.save, offers_file=args.offers_file,
                               use_catalog=not args.no_catalog, deep=args.deep, log=log)
    except (powershell.PowerShellError, OSError, ValueError) as e:
        log(f"Ошибка сканирования: {e}")
        return 2
    system, items = res.system, res.items

    if args.json:
        print(json.dumps({"system": system.__dict__, "devices": [a.to_dict() for a in items]},
                         ensure_ascii=False, indent=2))
    else:
        report.print_system(system, res.devices)
        report.print_assessments(items, show_all=args.all)

    if args.command != "install":
        return 0

    plan = engine.select_plan(items, args.include_optional, args.allow_firmware)
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
