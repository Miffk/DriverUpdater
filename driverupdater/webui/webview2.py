"""Проверка и установка Microsoft Edge WebView2 Runtime — движка, которым рисуется интерфейс.

WebView2 встроен в Windows 11 и в обновлённую Windows 10. На «голой» Windows 10 со старого
образа его может не быть — тогда предлагаем скачать официальный установщик Microsoft (~2 МБ).
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from .. import installer, powershell

RUNTIME_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
BOOTSTRAPPER_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"

MB_YESNO, MB_OK, MB_ICONQUESTION, MB_ICONERROR, IDYES = 0x4, 0x0, 0x20, 0x10, 6


def runtime_version() -> str:
    """Версия установленного WebView2 Runtime или пустая строка."""
    try:
        import winreg
    except ImportError:
        return ""
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{RUNTIME_GUID}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{RUNTIME_GUID}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{RUNTIME_GUID}"),
    ]
    for root, path in keys:
        try:
            with winreg.OpenKey(root, path) as k:
                ver, _ = winreg.QueryValueEx(k, "pv")
                if ver and ver != "0.0.0.0":
                    return str(ver)
        except OSError:
            continue
    return ""


def message_box(text: str, flags: int) -> int:
    try:
        return ctypes.windll.user32.MessageBoxW(None, text, "DriverUpdater", flags)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return 0


def install_runtime() -> bool:
    """Скачивает официальный установщик WebView2 от Microsoft, проверяет подпись,
    устанавливает и удаляет установщик."""
    tmp = Path(tempfile.mkdtemp(prefix="DriverUpdater_wv2_"))
    try:
        exe = tmp / "MicrosoftEdgeWebview2Setup.exe"
        req = urllib.request.Request(BOOTSTRAPPER_URL, headers={"User-Agent": "DriverUpdater"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(exe, "wb") as fh:
            shutil.copyfileobj(resp, fh)
        installer.verify_signature(exe)  # бросит ошибку, если подписан не Microsoft
        subprocess.run([str(exe), "/silent", "/install"], timeout=900, **powershell.NO_WINDOW)
        return bool(runtime_version())
    except (OSError, RuntimeError, subprocess.SubprocessError, powershell.PowerShellError):
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def ensure() -> bool:
    if runtime_version():
        return True
    answer = message_box(
        "Для окна программы нужен компонент Microsoft Edge WebView2.\n"
        "Он входит в Windows 11 и обновлённую Windows 10, но на этом компьютере его нет.\n\n"
        "Скачать и установить его с сайта Microsoft (около 2 МБ, затем ~150 МБ)?",
        MB_YESNO | MB_ICONQUESTION)
    if answer != IDYES:
        message_box("Без WebView2 окно программы не откроется.\n"
                    "Можно пользоваться консольной версией: DriverUpdater-cli.exe.", MB_OK)
        return False
    if install_runtime():
        return True
    message_box("Не удалось установить WebView2. Проверьте подключение к интернету "
                "или установите его вручную:\nhttps://developer.microsoft.com/microsoft-edge/webview2/",
                MB_OK | MB_ICONERROR)
    return False
