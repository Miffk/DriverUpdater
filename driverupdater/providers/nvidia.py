"""Источник №3: официальный сайт NVIDIA (тот же сервис, которым пользуется nvidia.com/drivers).

В Windows Update новые драйверы NVIDIA появляются с опозданием, а на сайте NVIDIA — в день
выхода. Поэтому для видеокарт NVIDIA проверяем свежую версию Game Ready напрямую у NVIDIA.

1. По названию видеокарты («GeForce RTX 5060 Ti») находим её коды в справочнике NVIDIA.
2. Спрашиваем у NVIDIA последний драйвер для этой карты и версии Windows.
3. Сравниваем с установленным: 32.0.15.8180 в Windows = 581.80 у NVIDIA.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from functools import lru_cache

from ..models import Device, DriverOffer, SystemInfo

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DriverUpdater"
LOOKUP_URL = "https://www.nvidia.com/Download/API/lookupValueSearch.aspx?TypeID=3"
DRIVER_URL = ("https://gfwsl.geforce.com/services_toolkit/services/com/nvidia/services/"
              "AjaxDriverService.php?func=DriverManualLookup&psid={psid}&pfid={pfid}&osID={os}"
              "&languageCode=1033&beta=0&isWHQL=1&dltype=-1&dch=1&upCRD=0&qnf=0&sort1=0"
              "&numberOfResults=1")
OS_WIN11, OS_WIN10_64 = 135, 57
DOWNLOAD_HOSTS = ("us.download.nvidia.com", "international.download.nvidia.com",
                  "download.nvidia.com", "uk.download.nvidia.com")
SIGNER = "NVIDIA Corporation"
TIMEOUT = 30


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def windows_to_nvidia(version: str) -> str:
    """32.0.15.8180 → 581.80 (последние 5 цифр двух последних частей)."""
    parts = version.split(".")
    if len(parts) != 4:
        return ""
    digits = (parts[2] + parts[3].zfill(4))[-5:]
    return f"{int(digits[:3])}.{digits[3:]}" if digits.isdigit() else ""


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)) or (0,)


def normalize_gpu(name: str) -> str:
    n = re.sub(r"\(r\)|\(tm\)|®|™", "", name, flags=re.I)
    n = re.sub(r"^\s*nvidia\s+", "", n, flags=re.I)
    return " ".join(n.lower().split())


def parse_products(xml_text: str) -> list[tuple[int, int, str]]:
    """[(psid, pfid, название)] из справочника NVIDIA."""
    out = []
    root = ET.fromstring(xml_text.strip().lstrip("﻿"))
    for lv in root.iter("LookupValue"):
        name = (lv.findtext("Name") or "").strip()
        value = (lv.findtext("Value") or "").strip()
        parent = lv.get("ParentID") or ""
        if name and value.isdigit() and parent.isdigit():
            out.append((int(parent), int(value), name))
    return out


@lru_cache(maxsize=1)
def products() -> tuple[tuple[int, int, str], ...]:
    return tuple(parse_products(_get(LOOKUP_URL)))


def match_product(gpu_name: str, items) -> tuple[int, int, str] | None:
    want = normalize_gpu(gpu_name)
    if not want:
        return None
    exact = [p for p in items if normalize_gpu(p[2]) == want]
    if exact:
        return exact[0]
    # «GeForce RTX 4060 Laptop GPU» ↔ «GeForce RTX 4060 Laptop GPU», «GeForce RTX 3060 Lite Hash Rate» ↔ «GeForce RTX 3060»
    close = [p for p in items if want.startswith(normalize_gpu(p[2]) + " ")]
    return max(close, key=lambda p: len(p[2])) if close else None


def parse_driver(json_text: str) -> dict | None:
    data = json.loads(json_text)
    ids = data.get("IDS") or []
    if str(data.get("Success")) != "1" or not ids:
        return None
    info = ids[0].get("downloadInfo") or {}
    url = urllib.parse.unquote(info.get("DownloadURL", ""))
    version = info.get("Version", "")
    if not url or not version:
        return None
    date = ""
    raw = urllib.parse.unquote(info.get("ReleaseDateTime", ""))
    for fmt in ("%a %b %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            date = datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
            break
        except ValueError:
            continue
    return {
        "version": version,
        "name": urllib.parse.unquote(info.get("Name", "")).replace("+", " ") or "GeForce Game Ready Driver",
        "url": url,
        "date": date,
        "size": _size(urllib.parse.unquote(info.get("DownloadURLFileSize", ""))),
    }


def _size(text: str) -> int:
    m = re.match(r"([\d.,]+)\s*(KB|MB|GB)", text, re.I)
    if not m:
        return 0
    return int(float(m.group(1).replace(",", "")) * {"KB": 1 << 10, "MB": 1 << 20, "GB": 1 << 30}[m.group(2).upper()])


def latest_for(gpu_name: str, win11: bool) -> dict | None:
    prod = match_product(gpu_name, products())
    if not prod:
        return None
    psid, pfid, _ = prod
    return parse_driver(_get(DRIVER_URL.format(psid=psid, pfid=pfid, os=OS_WIN11 if win11 else OS_WIN10_64)))


def find_update(device: Device, system: SystemInfo, gpu_name: str) -> DriverOffer | None:
    """Свежий драйвер с сайта NVIDIA, если он новее установленного."""
    if system.arch != "x64":
        return None
    try:
        info = latest_for(gpu_name, system.is_windows11)
    except (OSError, ValueError, ET.ParseError):
        return None
    if not info or urllib.parse.urlparse(info["url"]).hostname not in DOWNLOAD_HOSTS:
        return None
    installed = windows_to_nvidia(device.driver_version) if device.driver_provider.upper().startswith("NVIDIA") else ""
    if installed and _ver(info["version"]) <= _ver(installed):
        return None
    hwid = device.hardware_ids[0] if device.hardware_ids else ""
    return DriverOffer(
        source="nvidia", title=f"NVIDIA {info['name']} {info['version']}",
        version=info["version"], date=info["date"], hardware_id=hwid, provider="NVIDIA",
        driver_class="Display", update_id=info["version"], size_bytes=info["size"],
        reboot_required=False, download_url=info["url"], known_newer=True,
    )
