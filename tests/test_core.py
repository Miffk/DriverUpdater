import contextlib
import io
import json
import unittest
from pathlib import Path

from driverupdater import classify, cli, engine, hardware, installer
from driverupdater.models import Action, Device, DriverOffer, Necessity, SystemInfo
from driverupdater.providers import catalog, windows_update
from driverupdater.versions import is_newer, normalize_date, parse_version

FIX = Path(__file__).parent / "fixtures"


def load():
    system, devices = hardware.scan(str(FIX / "snapshot.json"))
    offers = windows_update.parse_search(json.loads((FIX / "wu_offers.json").read_text("utf-8")))
    return system, devices, offers


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_version("31.0.15.5222"), (31, 0, 15, 5222))
        self.assertEqual(parse_version("5.12"), (5, 12, 0, 0))
        self.assertIsNone(parse_version("n/a"))

    def test_dates(self):
        self.assertEqual(normalize_date("8/14/2023"), "2023-08-14")
        self.assertEqual(normalize_date("2023-08-14"), "2023-08-14")
        self.assertEqual(normalize_date("20230814000000.000000-000"), "2023-08-14")

    def test_newer_prefers_date_like_windows(self):
        self.assertTrue(is_newer("1.0", "2024-01-01", "2.0", "2023-01-01"))
        self.assertTrue(is_newer("2.0", "2024-01-01", "1.0", "2024-01-01"))
        self.assertFalse(is_newer("1.0", "2024-01-01", "1.0", "2024-01-01"))
        self.assertFalse(is_newer("10.60", "2022-06-01", "10.68", "2023-08-15"))


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.system, self.devices, self.offers = load()
        self.by_dev, self.unmatched = classify.match_offers(self.devices, self.offers)
        self.items = {a.device.name: a for a in classify.assess_all(self.devices, self.by_dev)}

    def test_snapshot_parsed(self):
        self.assertEqual(self.system.os_build, 22631)
        self.assertTrue(self.system.is_windows11)
        self.assertEqual(len(self.devices), 10)

    def test_basic_display_is_required(self):
        a = self.items["Microsoft Basic Display Adapter"]
        self.assertEqual(a.necessity, Necessity.REQUIRED)
        self.assertEqual(a.action, Action.INSTALL)
        self.assertEqual(a.offer.version, "31.0.15.5222")
        self.assertIn("NVIDIA", a.manual_hint)

    def test_missing_driver_is_required(self):
        a = self.items["Сетевой контроллер"]
        self.assertEqual(a.necessity, Necessity.REQUIRED)
        self.assertIn("не установлен драйвер", a.reason)
        self.assertIsNotNone(a.offer)

    def test_chipset_update_recommended(self):
        a = self.items["AMD SMBus"]
        self.assertEqual((a.necessity, a.action), (Necessity.RECOMMENDED, Action.UPDATE))

    def test_generic_audio_upgrade_recommended(self):
        a = self.items["High Definition Audio Device"]
        self.assertEqual(a.necessity, Necessity.RECOMMENDED)
        self.assertIn("универсальный", a.reason)

    def test_older_offer_ignored(self):
        a = self.items["Realtek Gaming 2.5GbE Family Controller"]
        self.assertEqual(a.necessity, Necessity.NOT_NEEDED)
        self.assertIsNone(a.offer)

    def test_firmware_never_auto(self):
        a = self.items["System Firmware"]
        self.assertEqual(a.necessity, Necessity.OPTIONAL)
        self.assertFalse(a.auto_install)

    def test_disabled_device_skipped(self):
        a = self.items["Logitech HD Webcam C270"]
        self.assertEqual(a.necessity, Necessity.NOT_NEEDED)
        self.assertIn("отключили", a.reason)

    def test_usb_input_error_suggests_restart_not_driver(self):
        # Случай с реального ПК: USB-устройство ввода, код 10, стандартный драйвер Windows.
        a = self.items["USB-устройство ввода"]
        self.assertEqual((a.necessity, a.action), (Necessity.REQUIRED, Action.REPAIR))
        self.assertTrue(a.repairable)
        self.assertIn("ни при чём", a.reason)
        self.assertIsNone(a.offer)

    def test_inbox_usb_not_needed(self):
        a = next(v for k, v in self.items.items() if k.startswith("Расширяемый"))
        self.assertEqual(a.necessity, Necessity.NOT_NEEDED)
        self.assertIn("стандартный драйвер Windows", a.reason)

    def test_plan_selection(self):
        items = list(self.items.values())
        plan = engine.select_plan(items, include_optional=False, allow_firmware=False)
        names = [a.device.name for a in plan]
        self.assertEqual(names[0], "AMD SMBus")  # чипсет первым
        self.assertIn("Microsoft Basic Display Adapter", names)
        self.assertNotIn("System Firmware", names)
        with_fw = engine.select_plan(items, include_optional=True, allow_firmware=True)
        self.assertIn("System Firmware", [a.device.name for a in with_fw])


class CatalogTests(unittest.TestCase):
    def test_parse_and_filter(self):
        page = (FIX / "catalog_search.html").read_text("utf-8")
        offers = catalog.parse_search_html(page, "PCI\\VEN_8086&DEV_2723")
        self.assertEqual(len(offers), 3)
        self.assertEqual(offers[0].date, "2023-08-14")
        self.assertEqual(offers[1].size_bytes, int(20.1 * (1 << 20)))
        sys11 = SystemInfo(os_build=22631, arch="x64")
        ok = [o for o in offers if catalog.suitable(o, sys11)]
        self.assertEqual([o.version for o in ok], ["22.250.1.2", "23.20.0.4"])  # ARM64 отброшен
        sys10 = SystemInfo(os_build=19045, arch="x64")
        self.assertEqual([o.version for o in offers if catalog.suitable(o, sys10)], ["22.250.1.2"])

    def test_download_dialog(self):
        page = ("var downloadInformation = new Array();\n"
                "downloadInformation[0].files[0].url = "
                "'http://catalog.s.download.windowsupdate.com/c/msdownload/update/driver/drvs/2024/01/abc.cab';")
        self.assertEqual(catalog.parse_download_dialog(page),
                         ["http://catalog.s.download.windowsupdate.com/c/msdownload/update/driver/drvs/2024/01/abc.cab"])


class InstallerTests(unittest.TestCase):
    def test_host_allowlist(self):
        self.assertTrue(installer.host_allowed("https://catalog.s.download.windowsupdate.com/x.cab"))
        self.assertTrue(installer.host_allowed("http://download.windowsupdate.com/x.cab"))
        self.assertFalse(installer.host_allowed("https://download.windowsupdate.com.evil.ru/x.cab"))
        self.assertFalse(installer.host_allowed("https://drivers-free.example.com/x.exe"))

    def test_wu_title_version(self):
        self.assertEqual(windows_update._version_from_title("NVIDIA - Display - 31.0.15.5222"), "31.0.15.5222")
        self.assertEqual(windows_update._version_from_title("Some driver"), "")
        # Новый формат названий в Windows Update / каталоге Microsoft (проверено вживую)
        self.assertEqual(windows_update._version_from_title("Intel net Driver Update (24.20.0.4)"), "24.20.0.4")
        self.assertEqual(windows_update._version_from_title("Realtek - Extension - 10.0.22000.31270"),
                         "10.0.22000.31270")


class CliTests(unittest.TestCase):
    ARGS = ["--from-file", str(FIX / "snapshot.json"), "--offers-file", str(FIX / "wu_offers.json")]

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_check_offline(self):
        code, out = self.run_cli("check", *self.ARGS)
        self.assertEqual(code, 0)
        self.assertIn("НЕОБХОДИМО — 3", out)
        self.assertIn("[Net]", out)  # класс определён по PCI-коду, хотя драйвера нет

    def test_install_dry_run(self):
        code, out = self.run_cli("install", "--dry-run", *self.ARGS)
        self.assertEqual(code, 0)
        self.assertIn("Будет установлено драйверов: 4", out)

    def test_scan_does_not_claim_search(self):
        code, out = self.run_cli("scan", "--all", "--from-file", str(FIX / "snapshot.json"))
        self.assertEqual(code, 0)
        self.assertNotIn("в официальных источниках нет", out)
        self.assertIn("Обновления ещё не проверялись", out)

    def test_json_output(self):
        code, out = self.run_cli("check", "--json", *self.ARGS)
        data = json.loads(out)
        self.assertEqual(len(data["devices"]), 10)


if __name__ == "__main__":
    unittest.main()
