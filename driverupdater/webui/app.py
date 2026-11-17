"""Запуск графической версии DriverUpdater (pywebview + HTML/CSS)."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path

from .. import powershell
from . import webview2
from .bridge import Bridge

WEB_DIR = Path(__file__).resolve().parent / "web"


def system_dark_mode() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except (ImportError, OSError):
        return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="DriverUpdater")
    p.add_argument("--from-file", help=argparse.SUPPRESS)
    p.add_argument("--offers-file", help=argparse.SUPPRESS)
    p.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--debug", action="store_true", help=argparse.SUPPRESS)
    args, _ = p.parse_known_args(argv)

    if powershell.is_windows() and not webview2.ensure():
        return 4

    import webview  # импорт здесь: на машине без WebView2 мы до него не дойдём

    bridge = Bridge(from_file=args.from_file, offers_file=args.offers_file)
    dark = system_dark_mode()
    window = webview.create_window(
        "DriverUpdater",
        url=(WEB_DIR / "index.html").as_uri(),
        js_api=bridge,
        width=1240, height=820, min_size=(940, 640),
        background_color="#0d1117" if dark else "#f4f6fb",
        text_select=False,
    )

    def emit(event: str, data: dict) -> None:
        payload = json.dumps({"type": event, "data": data}, ensure_ascii=True)
        window.evaluate_js(f"window.__du && window.__du.onEvent({payload})")
        if event == "quit":
            window.destroy()

    bridge._bind(emit)

    def on_closing() -> bool:
        if bridge.can_close():
            return True
        # Обработчик идёт в потоке окна — JS вызываем из другого потока, иначе зависнем.
        threading.Thread(target=emit, args=("close_blocked", {}), daemon=True).start()
        return False  # во время установки окно не закрываем

    window.events.closing += on_closing

    result = {"ok": False}

    def selftest() -> None:
        if window.events.loaded.wait(60):
            result["ok"] = window.evaluate_js("document.title") == "DriverUpdater"
        window.destroy()

    if args.selftest:
        webview.start(selftest, debug=False, private_mode=True)
        return 0 if result["ok"] else 1

    webview.start(debug=args.debug, private_mode=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
