"""Сравнение версий и дат драйверов."""

from __future__ import annotations

import re
from datetime import datetime


def parse_version(v: str) -> tuple[int, ...] | None:
    if not v:
        return None
    parts = re.findall(r"\d+", v)
    if not parts:
        return None
    nums = [int(p) for p in parts[:4]]
    return tuple(nums + [0] * (4 - len(nums)))


def normalize_date(s: str) -> str:
    """Приводит дату к YYYY-MM-DD. Понимает 'YYYY-MM-DD', 'M/D/YYYY', 'YYYYMMDD…' (CIM)."""
    if not s:
        return ""
    s = s.strip()
    candidates = [(s[:10], "%Y-%m-%d"), (s.split()[0], "%m/%d/%Y"), (s[:8], "%Y%m%d")]
    for text, fmt in candidates:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def is_newer(offer_version: str, offer_date: str,
             installed_version: str, installed_date: str) -> bool:
    """True, если предлагаемый драйвер новее установленного.

    Повторяет логику Windows: сначала сравнивается дата драйвера,
    при равной (или неизвестной) дате — номер версии.
    """
    od, idt = normalize_date(offer_date), normalize_date(installed_date)
    if od and idt and od != idt:
        return od > idt
    ov, iv = parse_version(offer_version), parse_version(installed_version)
    if ov and iv:
        return ov > iv
    if od and not idt:
        return True
    return bool(ov) and not iv
