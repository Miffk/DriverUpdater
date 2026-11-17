"""Источник №2: Microsoft Update Catalog (catalog.update.microsoft.com).

Официальный каталог Microsoft, где лежат все драйверы, опубликованные через
Windows Update, включая те, что Windows не предлагает автоматически.
Поиск идёт по Hardware ID устройства, скачивается подписанный .cab-архив.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request

from ..models import Device, DriverOffer, SystemInfo
from ..versions import is_newer, normalize_date

BASE = "https://www.catalog.update.microsoft.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DriverUpdater/0.1"
TIMEOUT = 60

ROW_RE = re.compile(r'<tr[^>]+id="([0-9a-fA-F-]{36})_R\d+"[^>]*>(.*?)</tr>', re.S)
CELL_RE = re.compile(r'<td[^>]+id="[0-9a-fA-F-]{36}_C(\d)_R\d+"[^>]*>(.*?)</td>', re.S)
URL_RE = re.compile(r"\.url\s*=\s*'([^']+)'")
TAG_RE = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(TAG_RE.sub(" ", fragment)).split())


def _http(url: str, data: bytes | None = None) -> str:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _size(text: str) -> int:
    m = re.match(r"([\d.,]+)\s*(KB|MB|GB)", text, re.I)
    if not m:
        return 0
    mult = {"KB": 1 << 10, "MB": 1 << 20, "GB": 1 << 30}[m.group(2).upper()]
    return int(float(m.group(1).replace(",", "")) * mult)


def parse_search_html(page: str, hardware_id: str) -> list[DriverOffer]:
    """Колонки таблицы результатов: C1 — заголовок, C2 — продукты, C3 — классификация,
    C4 — дата, C5 — версия, C6 — размер."""
    offers = []
    for guid, row in ROW_RE.findall(page):
        cells = {int(n): _text(v) for n, v in CELL_RE.findall(row)}
        if not cells.get(1):
            continue
        version = cells.get(5, "")
        offers.append(DriverOffer(
            source="catalog", title=cells[1],
            version="" if version.lower() in ("n/a", "") else version,
            date=normalize_date(cells.get(4, "")),
            hardware_id=hardware_id, update_id=guid.lower(),
            size_bytes=_size(cells.get(6, "")),
            driver_class=cells.get(3, ""),
            products=cells.get(2, ""),
            is_firmware="firmware" in cells[1].lower(),
        ))
    return offers


def suitable(offer: DriverOffer, system: SystemInfo) -> bool:
    title, products = offer.title.lower(), offer.products.lower()
    if "driver" not in offer.driver_class.lower() and "драйвер" not in offer.driver_class.lower():
        return False
    if "server" in products and "windows 10" not in products and "windows 11" not in products:
        return False
    if not system.is_windows11 and "windows 11" in products and "windows 10" not in products:
        return False
    arch = (system.arch or "x64").lower()
    if arch == "x64" and re.search(r"\b(x86|arm64)\b", title) and "x64" not in title:
        return False
    if arch == "arm64" and "arm64" not in title and re.search(r"\b(x64|x86|amd64)\b", title):
        return False
    return True


def search_hwid(hwid: str) -> list[DriverOffer]:
    url = f"{BASE}/Search.aspx?q={urllib.parse.quote(hwid)}"
    return parse_search_html(_http(url), hwid)


def find_for_device(device: Device, system: SystemInfo, max_ids: int = 3) -> DriverOffer | None:
    """Ищет по самым точным Hardware ID устройства и выбирает самый новый подходящий драйвер."""
    best: DriverOffer | None = None
    for hwid in device.hardware_ids[:max_ids]:
        try:
            found = search_hwid(hwid)
        except OSError:
            continue
        for off in found:
            if not suitable(off, system):
                continue
            if best is None or is_newer(off.version, off.date, best.version, best.date):
                best = off
        if best:
            break  # нашли по более точному ID — менее точные не нужны
    return best


def parse_download_dialog(page: str) -> list[str]:
    return [html.unescape(u) for u in URL_RE.findall(page)]


def download_urls(update_id: str) -> list[str]:
    payload = json.dumps([{"size": 0, "languages": "", "uidInfo": update_id, "updateID": update_id}])
    body = urllib.parse.urlencode({"updateIDs": payload}).encode()
    return parse_download_dialog(_http(f"{BASE}/DownloadDialog.aspx", data=body))
