"""Названия производителей и моделей по открытым базам pci.ids и usb.ids.

Базы (BSD-лицензия) скачиваются при сборке exe в папку driverupdater/data. Если их нет —
функции просто возвращают пустую строку, и программа работает со своим кратким списком.
"""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path


def _data_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    return (Path(base) / "driverupdater" / "data") if base else Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=2)
def _load(kind: str) -> dict[str, tuple[str, dict[str, str]]]:
    path = _data_dir() / f"{kind}.ids"
    db: dict[str, tuple[str, dict[str, str]]] = {}
    if not path.exists():
        return db
    vendor = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            if line[0] not in "\t" and not re.match(r"[0-9a-fA-F]{4}\s", line):
                if vendor is not None:
                    break  # начались разделы классов — производители кончились
                continue
            if not line.startswith("\t"):
                code, _, name = line.strip().partition("  ")
                vendor = code.upper()
                db[vendor] = (name.strip(), {})
            elif not line.startswith("\t\t") and vendor:
                code, _, name = line.strip().partition("  ")
                db[vendor][1][code.upper()] = name.strip()
    return db


def vendor_name(kind: str, vid: str) -> str:
    if kind not in ("pci", "usb") or not vid:
        return ""
    entry = _load(kind).get(vid.upper())
    return entry[0] if entry else ""


def device_name(kind: str, vid: str, pid: str) -> str:
    if kind not in ("pci", "usb") or not vid or not pid:
        return ""
    entry = _load(kind).get(vid.upper())
    if not entry:
        return ""
    name = entry[1].get(pid.upper(), "")
    # «GA106 [GeForce RTX 3060 Lite Hash Rate]» → «GeForce RTX 3060 Lite Hash Rate»
    m = re.search(r"\[([^\]]+)\]", name)
    return (m.group(1) if m else name).strip()
