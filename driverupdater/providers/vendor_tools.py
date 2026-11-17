"""Официальные программы производителей для подбора драйверов.

Своего открытого сервиса версий у AMD и Intel нет, зато есть официальные бесплатные
программы, которые сами определяют оборудование и ставят свежие драйверы:
- AMD Software (Auto-Detect) — видеокарты Radeon и чипсеты AMD;
- Intel Driver & Support Assistant — всё оборудование Intel.

Мы скачиваем такую программу только с сайта производителя, проверяем цифровую подпись,
запускаем её и после закрытия удаляем установщик.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import installer, powershell

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


@dataclass(frozen=True)
class Tool:
    key: str
    title: str
    page: str              # страница, где лежит ссылка (или прямая ссылка)
    signer: str
    domain: str            # скачивать разрешено только с этого домена и его поддоменов
    referer: str = ""
    link_re: str = ""      # как найти ссылку на странице; пусто — page уже прямая ссылка


TOOLS = {
    "amd": Tool("amd", "AMD Software (автоподбор драйверов AMD)",
                "https://www.amd.com/en/support/download/drivers.html",
                "Advanced Micro Devices", "amd.com", referer="https://www.amd.com/",
                link_re=r"https://drivers\.amd\.com/drivers/installer/[^\"'\s<>]+?minimalsetup[^\"'\s<>]*?\.exe"),
    "intel": Tool("intel", "Intel Driver & Support Assistant",
                  "https://dsadata.intel.com/installer", "Intel Corporation", "intel.com"),
}


def _request(url: str, referer: str = "") -> urllib.request.Request:
    headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.8"}
    if referer:
        headers["Referer"] = referer
    return urllib.request.Request(url, headers=headers)


def _host_ok(url: str, domain: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return urllib.parse.urlparse(url).scheme == "https" and (host == domain or host.endswith("." + domain))


def find_link(tool: Tool) -> str:
    if not tool.link_re:
        return tool.page
    with urllib.request.urlopen(_request(tool.page, tool.referer), timeout=30) as resp:
        page = resp.read().decode("utf-8", errors="replace")
    m = re.search(tool.link_re, page)
    if not m:
        raise RuntimeError("на сайте производителя не нашлась ссылка на программу")
    return m.group(0)


def download(tool: Tool, dest: Path) -> Path:
    url = find_link(tool)
    if not _host_ok(url, tool.domain):
        raise RuntimeError(f"ссылка ведёт не на официальный сайт: {url}")
    with urllib.request.urlopen(_request(url, tool.referer), timeout=300) as resp:
        final = resp.geturl()
        if not _host_ok(final, tool.domain):
            raise RuntimeError(f"загрузка перенаправлена не на официальный сайт: {final}")
        name = Path(urllib.parse.urlparse(final).path).name or f"{tool.key}_setup.exe"
        if not name.lower().endswith(".exe"):
            name += ".exe"
        path = dest / name
        with open(path, "wb") as fh:
            shutil.copyfileobj(resp, fh, 1 << 20)
    return path


def run(key: str, log: Callable[[str], None]) -> tuple[bool, str]:
    tool = TOOLS[key]
    tmp = Path(tempfile.mkdtemp(prefix=f"DriverUpdater_{key}_"))
    try:
        log(f"Скачиваю {tool.title} с официального сайта…")
        exe = download(tool, tmp)
        signer = installer.verify_signature(exe, (tool.signer,))
        log(f"  подпись в порядке: {signer.split(',')[0]}")
        log("  запускаю — дальше следуйте подсказкам программы производителя")
        subprocess.run([str(exe)], timeout=6 * 3600)
        return True, f"Программа «{tool.title}» закрыта. Установочный файл удалён."
    except (OSError, RuntimeError, subprocess.SubprocessError, powershell.PowerShellError) as e:
        return False, f"Не удалось запустить «{tool.title}»: {e}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
