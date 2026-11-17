"""Мост между веб-интерфейсом (HTML/JS) и логикой программы.

Публичные методы класса Bridge вызываются из JavaScript: `pywebview.api.<метод>()`.
Долгие операции идут в фоновом потоке, а о ходе работы мост сообщает интерфейсу
событиями: emit(тип, данные) → window.__du.onEvent({type, data}).
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
import traceback
import webbrowser
from dataclasses import asdict
from typing import Callable

from .. import __version__, classify, engine, installer, names, powershell, updater, vendors
from ..models import Action, Assessment, Device, Necessity, SystemInfo
from ..providers import vendor_tools

Emit = Callable[[str, dict], None]

SOURCE_NAMES = {"windows_update": "Windows Update", "catalog": "Каталог Microsoft", "nvidia": "Сайт NVIDIA"}

# Названия, по которым непонятно, что это за устройство, — заменяем на модель из базы.
GENERIC_NAMES = {"сетевой контроллер", "network controller", "неизвестное устройство", "unknown device",
                 "pci-устройство", "pci device", "видеоконтроллер", "video controller",
                 "видеоконтроллер (vga-совместимый)", "video controller (vga compatible)",
                 "мультимедиа контроллер", "multimedia controller", "контроллер sm bus", "sm bus controller",
                 "pci-контроллер simple communications", "pci simple communications controller",
                 "базовое системное устройство", "base system device"}


def display_name(d: Device) -> str:
    model = vendors.model_name(d)
    generic = d.name.strip().lower() in GENERIC_NAMES or classify.is_basic_display(d) or not d.name
    vendor = vendors.vendor_name(d)
    if generic and model:
        return model if not vendor or model.lower().startswith(vendor.lower()) else f"{vendor} {model}"
    if generic and vendor:
        what = "Видеокарта" if classify.is_basic_display(d) else (d.name or "Устройство")
        return f"{what} {vendor}"
    return d.name or d.instance_id


def serialize_item(item_id: str, a: Assessment) -> dict:
    d, o = a.device, a.offer
    cls = classify.effective_class(d, o)
    hint_name, _, hint_url = a.manual_hint.partition(": ")
    v = vendors.lookup(d)
    tool = v.tool if v and v.tool in vendor_tools.TOOLS else ""
    show_tool = tool and (cls in ("Display", "System") or (a.action != Action.NONE and not o))
    return {
        "id": item_id,
        "name": display_name(d),
        "winName": d.name,
        "model": vendors.model_name(d),
        "cls": cls,
        "clsTitle": classify.class_title(cls),
        "vendor": v.name if v else "",
        "site": {"name": v.name, "url": v.drivers_url} if v and v.drivers_url else None,
        "searchUrl": vendors.search_url(d) if d.hardware_ids else "",
        "tool": tool if show_tool else "",
        "toolTitle": vendor_tools.TOOLS[tool].title if show_tool else "",
        "repairable": a.repairable,
        "necessity": a.necessity.value,
        "action": a.action.value,
        "reason": a.reason,
        "current": {
            "version": d.driver_version, "date": d.driver_date,
            "provider": names.brand(d.driver_provider) or d.driver_provider,
        } if d.has_driver else None,
        "offer": {
            "key": installer.offer_key(a),
            "title": o.title, "version": o.version, "date": o.date,
            "source": SOURCE_NAMES.get(o.source, o.source), "size": o.size_bytes,
            "reboot": o.reboot_required,
        } if o else None,
        "installable": engine.is_installable(a, allow_firmware=True),
        "selected": engine.default_selected(a),
        "firmware": not a.auto_install,
        "hint": {"name": hint_name, "url": hint_url} if hint_url else None,
        "hwid": d.hardware_ids[0] if d.hardware_ids else "",
        "hidden": d.is_virtual and a.action == Action.NONE,
        "problem": d.problem_code,
    }


def serialize_system(s: SystemInfo, devices: list[Device] | None = None) -> dict:
    data = asdict(s)
    data["isWindows11"] = s.is_windows11
    data["display"] = engine.describe_system(s, devices)
    return data


class Bridge:
    def __init__(self, *, from_file: str | None = None, offers_file: str | None = None):
        self._emit_fn: Emit | None = None
        self._from_file = from_file
        self._offers_file = offers_file
        self._items: dict[str, Assessment] = {}
        self._system: SystemInfo | None = None
        self._busy = False
        self._installing = False
        self._lock = threading.Lock()
        # Тесты подменяют на синхронный запуск.
        self._spawn: Callable[[Callable[[], None]], None] = (
            lambda fn: threading.Thread(target=fn, daemon=True).start())

    # ---------- служебное ----------

    def _bind(self, emit: Emit) -> None:
        self._emit_fn = emit

    def _emit(self, event: str, data: dict | None = None) -> None:
        if self._emit_fn:
            try:
                self._emit_fn(event, data or {})
            except Exception:  # noqa: BLE001 — окно могли закрыть
                pass

    def _log(self, msg: str) -> None:
        for line in msg.strip("\n").splitlines():
            self._emit("log", {"text": line})

    def _task(self, name: str, fn: Callable[[], None]) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True

        def wrapper():
            try:
                fn()
            except Exception as e:  # noqa: BLE001 — показываем пользователю любую ошибку
                self._log(traceback.format_exc())
                self._emit("error", {"task": name, "message": str(e) or type(e).__name__})
            finally:
                with self._lock:
                    self._busy = False
                    self._installing = False
                self._emit("idle", {"task": name})

        self._spawn(wrapper)
        return True

    def _items_payload(self) -> list[dict]:
        return [serialize_item(i, a) for i, a in self._items.items()]

    def _set_items(self, items: list[Assessment]) -> None:
        self._items = {f"d{i}": a for i, a in enumerate(items)}

    # ---------- вызывается из JavaScript ----------

    def get_info(self) -> dict:
        return {
            "version": __version__,
            "isAdmin": installer.is_admin(),
            "isWindows": powershell.is_windows(),
            "demo": bool(self._from_file),
            "busy": self._busy,
        }

    def start(self, deep: bool = False) -> bool:
        """Полный цикл: определить железо → найти драйверы → оценить."""
        def job():
            self._emit("phase", {"phase": "scan", "text": "Определяю оборудование…"})
            res = engine.scan(self._from_file)
            self._system = res.system
            self._set_items(res.items)
            self._emit("system", {"system": serialize_system(res.system, res.devices),
                                  "count": len(res.devices)})
            self._log(f"Найдено устройств: {len(res.devices)}")

            self._emit("phase", {"phase": "search",
                                 "text": "Ищу драйверы в Windows Update и каталоге Microsoft…"})
            offers, unmatched = engine.find_offers(
                res.system, res.devices, offers_file=self._offers_file,
                use_catalog=True, deep=deep, log=self._log)
            items = classify.assess_all(res.devices, offers) + engine.unmatched_assessments(unmatched)
            self._set_items(items)
            self._emit("items", {"items": self._items_payload()})
            self._log("Поиск завершён.")

        return self._task("start", job)

    def install(self, ids: list[str], restore_point: bool = True) -> dict:
        if not powershell.is_windows():
            return {"ok": False, "error": "Установка драйверов возможна только в Windows."}
        if not installer.is_admin():
            return {"ok": False, "error": "admin"}
        chosen = [self._items[i] for i in ids if i in self._items]
        plan = engine.order_plan([a for a in chosen if engine.is_installable(a, allow_firmware=True)])
        if not plan:
            return {"ok": False, "error": "Не выбрано ни одного драйвера."}

        def job():
            self._installing = True
            self._emit("install_started", {"keys": [installer.offer_key(a) for a in plan]})
            if restore_point:
                self._emit("phase", {"phase": "restore", "text": "Создаю точку восстановления…"})
                self._log("Создание точки восстановления системы…")
                try:
                    installer.create_restore_point()
                except powershell.PowerShellError as e:
                    self._log(str(e))
                    self._emit("install_aborted", {
                        "message": "Не удалось создать точку восстановления — возможно, защита "
                                   "системы отключена. Выключите параметр «Точка восстановления», "
                                   "если хотите продолжить без неё."})
                    return
            self._emit("phase", {"phase": "install", "text": "Устанавливаю драйверы…"})
            rep = installer.install(
                plan, log=self._log,
                progress=lambda key, state, msg: self._emit("progress", {"key": key, "state": state,
                                                                          "message": msg}))
            self._emit("install_done", {
                "results": [{"key": r.key, "name": r.name, "ok": r.ok, "message": r.message}
                            for r in rep.results],
                "okCount": sum(r.ok for r in rep.results),
                "total": len(rep.results),
                "cleanedBytes": rep.cleaned_bytes,
                "reboot": rep.reboot_required,
            })

        return {"ok": self._task("install", job), "count": len(plan)}

    def repair(self, item_id: str) -> dict:
        """Перезапуск сбойного устройства (как «отключить и включить» в Диспетчере устройств)."""
        a = self._items.get(item_id)
        if not a:
            return {"ok": False, "error": "Устройство не найдено — обновите список."}
        if not powershell.is_windows():
            return {"ok": False, "error": "Это работает только в Windows."}
        if not installer.is_admin():
            return {"ok": False, "error": "admin"}

        def job():
            self._log(f"Перезапуск устройства: {a.device.name}")
            ok, msg = installer.restart_device(a.device.instance_id)
            self._log("  " + msg)
            self._emit("repair_done", {"id": item_id, "ok": ok, "message": msg})

        return {"ok": self._task("repair", job)}

    def run_tool(self, key: str) -> dict:
        """Скачать и запустить официальную программу AMD/Intel для подбора драйверов."""
        if key not in vendor_tools.TOOLS:
            return {"ok": False, "error": "Неизвестная программа."}
        if not powershell.is_windows():
            return {"ok": False, "error": "Это работает только в Windows."}

        def job():
            self._emit("phase", {"phase": "tool", "text": f"Запускаю {vendor_tools.TOOLS[key].title}…"})
            ok, msg = vendor_tools.run(key, self._log)
            self._emit("tool_done", {"key": key, "ok": ok, "message": msg})

        return {"ok": self._task("tool", job)}

    def check_update(self) -> dict:
        """Есть ли новая версия программы на GitHub. Ошибки сети — не повод беспокоить пользователя."""
        try:
            info = updater.check()
        except Exception:  # noqa: BLE001
            return {"available": False}
        self._update_info = info
        return {k: info[k] for k in ("available", "version", "notes", "page", "canAutoUpdate", "current")}

    def apply_update(self) -> dict:
        info = getattr(self, "_update_info", None)
        if not info or not info.get("available"):
            return {"ok": False, "error": "Обновление не найдено — проверьте ещё раз."}
        if not info.get("canAutoUpdate"):
            self.open_url(info["page"])
            return {"ok": True, "manual": True}

        def job():
            self._emit("phase", {"phase": "update", "text": f"Обновляю программу до версии {info['version']}…"})
            exe = updater.apply(info, self._log)
            self._emit("update_ready", {"version": info["version"]})
            updater.relaunch(exe)
            self._emit("quit", {})

        return {"ok": self._task("update", job)}

    def open_url(self, url: str) -> bool:
        if not url.startswith("https://"):
            return False
        webbrowser.open(url)
        return True

    def reboot(self) -> bool:
        if not powershell.is_windows():
            return False
        subprocess.Popen(["shutdown", "/r", "/t", "10", "/c", "DriverUpdater: завершение установки драйверов"],
                         **powershell.NO_WINDOW)
        return True

    def relaunch_as_admin(self) -> bool:
        if not powershell.is_windows():
            return False
        if getattr(sys, "frozen", False):
            exe, params = sys.executable, subprocess.list2cmdline(sys.argv[1:])
        else:
            exe, params = sys.executable, subprocess.list2cmdline(["-m", "driverupdater.webui", *sys.argv[1:]])
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)  # type: ignore[attr-defined]
        if rc > 32:
            self._emit("quit", {})
            return True
        return False

    def can_close(self) -> bool:
        return not self._installing
