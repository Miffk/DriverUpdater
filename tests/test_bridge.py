import json
import unittest
from pathlib import Path
from unittest import mock

from driverupdater import installer
from driverupdater.webui import webview2
from driverupdater.webui.bridge import Bridge

FIX = Path(__file__).parent / "fixtures"
WEB = Path(__file__).parent.parent / "driverupdater" / "webui" / "web"


def make_bridge():
    b = Bridge(from_file=str(FIX / "snapshot.json"), offers_file=str(FIX / "wu_offers.json"))
    b._spawn = lambda fn: fn()  # синхронно
    events = []
    b._bind(lambda t, d: events.append((t, d)))
    return b, events


class BridgeTests(unittest.TestCase):
    def test_start_emits_full_cycle(self):
        b, events = make_bridge()
        self.assertTrue(b.start())
        types = [t for t, _ in events]
        self.assertEqual(types[0], "phase")
        self.assertIn("system", types)
        self.assertIn("items", types)
        self.assertEqual(types[-1], "idle")
        items = next(d for t, d in events if t == "items")["items"]
        json.dumps(items)  # всё сериализуется для JS
        gpu = next(i for i in items if i["cls"] == "Display")
        self.assertEqual(gpu["vendor"], "NVIDIA")
        self.assertEqual(gpu["necessity"], "required")
        self.assertTrue(gpu["selected"])
        self.assertTrue(gpu["offer"]["key"].startswith("windows_update:"))
        fw = next(i for i in items if i["cls"] == "Firmware")
        self.assertTrue(fw["firmware"])
        self.assertTrue(fw["installable"])
        self.assertFalse(fw["selected"])  # прошивка по умолчанию не отмечена
        net = next(i for i in items if i["problem"] == 28)
        self.assertEqual((net["vendor"], net["cls"]), ("Intel", "Net"))
        self.assertEqual(net["tool"], "")  # драйвер нашёлся в Windows Update — программа Intel не нужна
        chipset = next(i for i in items if i["cls"] == "System")
        self.assertEqual(chipset["tool"], "amd")  # для чипсета AMD — официальная программа AMD
        hid = next(i for i in items if i["problem"] == 10)
        self.assertEqual((hid["action"], hid["repairable"], hid["vendor"]), ("repair", True, "Winbond"))
        system = next(d for t, d in events if t == "system")["system"]["display"]
        self.assertEqual(system["computer"], "Настольный ПК MSI")
        self.assertEqual(system["board"], "MSI MAG B550 TOMAHAWK")

    def test_busy_guard(self):
        b, _ = make_bridge()
        b._spawn = lambda fn: None  # задача «висит»
        self.assertTrue(b.start())
        self.assertFalse(b.start())

    def test_error_is_reported(self):
        b = Bridge(from_file=str(FIX / "missing.json"))
        b._spawn = lambda fn: fn()
        events = []
        b._bind(lambda t, d: events.append((t, d)))
        b.start()
        self.assertIn("error", [t for t, _ in events])
        self.assertEqual(events[-1][0], "idle")
        self.assertFalse(b._busy)

    def test_install_requires_windows_and_admin(self):
        b, _ = make_bridge()
        b.start()
        with mock.patch("driverupdater.powershell.is_windows", return_value=False):
            self.assertFalse(b.install(["d0"])["ok"])
        with mock.patch("driverupdater.powershell.is_windows", return_value=True), \
                mock.patch.object(installer, "is_admin", return_value=False):
            self.assertEqual(b.install(["d0"])["error"], "admin")

    def test_install_flow_events(self):
        b, events = make_bridge()
        b.start()
        ids = [i for i, a in b._items.items() if a.offer and a.necessity.value == "required"]
        fake = installer.Report(results=[installer.InstallResult("x", True, "ok", key="k")], cleaned_bytes=10)

        def fake_install(plan, log, progress):
            for a in plan:
                progress(installer.offer_key(a), "running", "Скачивание · 50%", stage="download", percent=50.0)
                progress(installer.offer_key(a), "ok", "установлен")
            return fake

        with mock.patch("driverupdater.powershell.is_windows", return_value=True), \
                mock.patch.object(installer, "is_admin", return_value=True), \
                mock.patch.object(installer, "create_restore_point") as rp, \
                mock.patch.object(installer, "install", side_effect=fake_install):
            res = b.install(ids, True)
        self.assertTrue(res["ok"])
        rp.assert_called_once()
        types = [t for t, _ in events]
        self.assertIn("install_started", types)
        self.assertIn("install_done", types)
        prog = [d for t, d in events if t == "progress"]
        self.assertEqual(len(prog), 2 * len(ids))
        self.assertEqual((prog[0]["stage"], prog[0]["percent"]), ("download", 50.0))

    def test_update_works_while_search_is_running(self):
        # Случай с реального ПК: нажали «Обновить», пока шёл поиск драйверов.
        b, events = make_bridge()
        b._busy = True  # идёт поиск
        b._update_info = {"available": True, "canAutoUpdate": True, "version": "9.9.9", "page": "https://x"}
        with mock.patch("driverupdater.updater.apply", return_value="exe") as ap, \
                mock.patch("driverupdater.updater.relaunch") as rl:
            res = b.apply_update()
        self.assertTrue(res["ok"])
        ap.assert_called_once()
        rl.assert_called_once_with("exe")
        self.assertEqual([t for t, _ in events][-2:], ["update_ready", "quit"])

    def test_update_blocked_during_driver_install_with_reason(self):
        b, _ = make_bridge()
        b._installing = True
        b._update_info = {"available": True, "canAutoUpdate": True, "version": "9.9.9", "page": "https://x"}
        res = b.apply_update()
        self.assertFalse(res["ok"])
        self.assertIn("устанавливаются драйверы", res["error"])

    def test_update_failure_is_explained(self):
        b, events = make_bridge()
        b._update_info = {"available": True, "canAutoUpdate": True, "version": "9.9.9", "page": "https://x"}
        with mock.patch("driverupdater.updater.apply", side_effect=RuntimeError("контрольная сумма не совпала")):
            b.apply_update()
        failed = [d for t, d in events if t == "update_failed"]
        self.assertEqual(failed[0]["message"], "контрольная сумма не совпала")
        self.assertFalse(b._updating)

    def test_open_url_only_https(self):
        b, _ = make_bridge()
        with mock.patch("webbrowser.open") as op:
            self.assertFalse(b.open_url("file:///C:/Windows/System32/cmd.exe"))
            self.assertTrue(b.open_url("https://www.nvidia.com/"))
            op.assert_called_once()


class WebAssetsTests(unittest.TestCase):
    def test_assets_present_and_linked(self):
        html = (WEB / "index.html").read_text("utf-8")
        for name in ("styles.css", "icons.js", "app.js"):
            self.assertTrue((WEB / name).exists(), name)
            self.assertIn(name, html)
        self.assertIn("<title>DriverUpdater</title>", html)  # проверяется в --selftest

    def test_no_gpu_heavy_effects(self):
        # На встроенных видеокартах размытие и бесконечные анимации грузили GPU до 98% в простое.
        css = (WEB / "styles.css").read_text("utf-8")
        self.assertNotIn("backdrop-filter", css)
        self.assertNotIn("blur(", css)
        self.assertIn(".paused", css)  # анимации на паузе, когда окно свёрнуто

    def test_webview2_absent_off_windows(self):
        self.assertIsInstance(webview2.runtime_version(), str)


if __name__ == "__main__":
    unittest.main()
