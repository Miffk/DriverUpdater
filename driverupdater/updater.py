"""Обновление самой программы из GitHub Releases.

1. Спрашиваем у GitHub последнюю версию (releases/latest).
2. Если она новее — скачиваем exe рядом с текущим, сверяем контрольную сумму SHA-256
   (её публикует GitHub для каждого файла релиза и наш файл SHA256SUMS.txt).
3. Запущенный exe в Windows нельзя перезаписать, но можно переименовать: текущий файл
   становится DriverUpdater.exe.old, новый занимает его место и запускается.
   Старый файл удаляется при следующем запуске.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from . import __version__, powershell

REPO = "Miffk/DriverUpdater"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
DOWNLOAD_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
UA = f"DriverUpdater/{__version__}"


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4]) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    return _ver(remote) > _ver(local)


def _get(url: str, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def current_exe() -> Path | None:
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None


def asset_name() -> str:
    exe = current_exe()
    return exe.name if exe and "cli" in exe.name.lower() else "DriverUpdater.exe"


def parse_release(data: dict, want: str) -> dict:
    tag = str(data.get("tag_name", ""))
    assets = {a.get("name", ""): a for a in data.get("assets") or []}
    asset = assets.get(want) or next((a for n, a in assets.items() if n.lower() == want.lower()), None)
    sums = assets.get("SHA256SUMS.txt")
    digest = (asset or {}).get("digest") or ""
    return {
        "version": tag.lstrip("vV"),
        "available": bool(tag) and is_newer(tag) and not data.get("draft") and not data.get("prerelease"),
        "notes": data.get("body") or "",
        "page": data.get("html_url") or RELEASES_PAGE,
        "asset": {
            "name": asset.get("name"), "url": asset.get("browser_download_url"),
            "size": asset.get("size", 0),
            "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else "",
            "sums_url": (sums or {}).get("browser_download_url", ""),
        } if asset else None,
        "canAutoUpdate": bool(asset) and current_exe() is not None,
        "current": __version__,
    }


def check() -> dict:
    return parse_release(json.loads(_get(API_LATEST)), asset_name())


def expected_hash(info: dict) -> str:
    a = info["asset"]
    if a.get("sha256"):
        return a["sha256"].lower()
    if a.get("sums_url"):
        for line in _get(a["sums_url"], "text/plain").decode("utf-8", "replace").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1].lstrip("*") == a["name"]:
                return parts[0].lower()
    return ""


def cleanup_old() -> None:
    """Удаляет файл прошлой версии, оставшийся после обновления."""
    exe = current_exe()
    if exe:
        old = exe.with_name(exe.name + ".old")
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass


def apply(info: dict, log: Callable[[str], None] = lambda _: None,
          on_bytes: Callable[[int, int], None] | None = None) -> Path:
    """Скачивает и подменяет exe. Возвращает путь к новому exe (его нужно запустить)."""
    exe = current_exe()
    a = info.get("asset")
    if not exe or not a:
        raise RuntimeError("автоматическое обновление доступно только для exe-версии")
    url = a["url"]
    if urllib.parse.urlparse(url).hostname not in DOWNLOAD_HOSTS:
        raise RuntimeError(f"ссылка не на GitHub: {url}")
    want = expected_hash(info)
    if not want:
        raise RuntimeError("у релиза нет контрольной суммы — обновление отменено")
    new = exe.with_name(exe.name + ".new")
    log(f"Скачиваю версию {info['version']}…")
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as resp, open(new, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0) if hasattr(resp, "headers") else 0
        total = total or int(a.get("size") or 0)
        done = 0
        while chunk := resp.read(1 << 18):
            h.update(chunk)
            fh.write(chunk)
            done += len(chunk)
            if on_bytes:
                on_bytes(done, total)
    if h.hexdigest().lower() != want:
        new.unlink(missing_ok=True)
        raise RuntimeError("контрольная сумма не совпала — файл повреждён, обновление отменено")
    log("Контрольная сумма совпала. Заменяю программу…")
    old = exe.with_name(exe.name + ".old")
    old.unlink(missing_ok=True)
    os.replace(exe, old)          # запущенный exe можно переименовать
    try:
        os.replace(new, exe)
    except OSError:
        os.replace(old, exe)      # откат
        raise
    return exe


def relaunch(exe: Path) -> None:
    subprocess.Popen([str(exe), *sys.argv[1:]], close_fds=True,
                     creationflags=0x00000008 if powershell.is_windows() else 0)  # DETACHED_PROCESS
