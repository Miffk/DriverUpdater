import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from driverupdater import ids, names, updater, vendors
from driverupdater.models import Device, SystemInfo
from driverupdater.providers import nvidia

NV_XML = """<?xml version="1.0" encoding="utf-8"?>
<LookupValueSearch><LookupValues>
  <LookupValue ParentID="131"><Name>GeForce RTX 5060 Ti</Name><Value>1066</Value></LookupValue>
  <LookupValue ParentID="131"><Name>GeForce RTX 5060</Name><Value>1067</Value></LookupValue>
  <LookupValue ParentID="129"><Name>GeForce RTX 4060 Laptop GPU</Name><Value>1004</Value></LookupValue>
</LookupValues></LookupValueSearch>"""

NV_JSON = ('{"Success":"1","IDS":[{"downloadInfo":{"Success":"1","Version":"581.80",'
           '"Name":"GeForce%20Game%20Ready%20Driver","ReleaseDateTime":"Tue%20Nov%2004%2C%202025",'
           '"DownloadURL":"https%3A%2F%2Fus.download.nvidia.com%2FWindows%2F581.80%2F581.80-desktop-win10-win11-64bit-international-dch-whql.exe",'
           '"DownloadURLFileSize":"868.71%20MB"}}]}')


def gpu(version="32.0.15.7680", provider="NVIDIA"):
    return Device(instance_id="PCI\\VEN_10DE&DEV_2D04\\1", name="NVIDIA GeForce RTX 5060 Ti",
                  device_class="Display", hardware_ids=["PCI\\VEN_10DE&DEV_2D04&SUBSYS_51161462"],
                  driver_version=version, driver_date="2025-08-01", driver_provider=provider, inf_name="oem5.inf")


class NvidiaTests(unittest.TestCase):
    def setUp(self):
        nvidia.products.cache_clear()

    def test_version_conversion(self):
        self.assertEqual(nvidia.windows_to_nvidia("32.0.15.8180"), "581.80")
        self.assertEqual(nvidia.windows_to_nvidia("31.0.15.5222"), "552.22")

    def test_products_and_match(self):
        items = nvidia.parse_products(NV_XML)
        self.assertEqual(nvidia.match_product("NVIDIA GeForce RTX 5060 Ti", items), (131, 1066, "GeForce RTX 5060 Ti"))
        self.assertEqual(nvidia.match_product("NVIDIA GeForce RTX 5060", items)[1], 1067)

    def _fake_get(self, url):
        return NV_XML if "lookupValueSearch" in url else NV_JSON

    def test_update_found_when_newer(self):
        with mock.patch.object(nvidia, "_get", side_effect=self._fake_get):
            off = nvidia.find_update(gpu("32.0.15.7680"), SystemInfo(os_build=26200, arch="x64"),
                                     "NVIDIA GeForce RTX 5060 Ti")
        self.assertIsNotNone(off)
        self.assertEqual((off.source, off.version, off.known_newer), ("nvidia", "581.80", True))
        self.assertTrue(off.download_url.startswith("https://us.download.nvidia.com/"))

    def test_no_update_when_same(self):
        with mock.patch.object(nvidia, "_get", side_effect=self._fake_get):
            off = nvidia.find_update(gpu("32.0.15.8180"), SystemInfo(os_build=26200, arch="x64"),
                                     "NVIDIA GeForce RTX 5060 Ti")
        self.assertIsNone(off)

    def test_network_error_is_quiet(self):
        with mock.patch.object(nvidia, "_get", side_effect=OSError("offline")):
            self.assertIsNone(nvidia.find_update(gpu(), SystemInfo(arch="x64"), "NVIDIA GeForce RTX 5060 Ti"))


class VendorToolsTests(unittest.TestCase):
    def test_amd_prefers_stable_over_beta(self):
        from driverupdater.providers import vendor_tools as vt
        page = ('<a href="https://drivers.amd.com/drivers/installer/26.20/beta/amd-software-adrenalin-edition-26.11.1-minimalsetup-261111_web.exe">'
                '<a href="https://drivers.amd.com/drivers/installer/25.20/whql/amd-software-adrenalin-edition-25.10.2-minimalsetup-251030_web.exe">')

        class Resp:
            def read(self):
                return page.encode()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=Resp()):
            link = vt.find_link(vt.TOOLS["amd"])
        self.assertIn("/whql/", link)


class NamesTests(unittest.TestCase):
    def test_brands(self):
        self.assertEqual(names.brand("Micro-Star International Co., Ltd."), "MSI")
        self.assertEqual(names.brand("ASUSTeK COMPUTER INC."), "ASUS")
        self.assertEqual(names.brand("To Be Filled By O.E.M."), "")
        self.assertEqual(names.pretty_model("PRO B650M-B (MS-7E28)"), "PRO B650M-B")

    def test_cpu_os(self):
        self.assertEqual(names.pretty_cpu("AMD Ryzen 7 7800X3D 8-Core Processor"), "AMD Ryzen 7 7800X3D (8 ядер)")
        self.assertEqual(names.pretty_cpu("Intel(R) Core(TM) i7-10700K CPU @ 3.80GHz"), "Intel Core i7-10700K")
        self.assertEqual(names.pretty_os("Майкрософт Windows 11 Pro", 26200, "x64"), "Windows 11 Pro 25H2 · 64-бит")


class IdsTests(unittest.TestCase):
    def test_parse_ids_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "pci.ids").write_text(
                "# comment\n10de  NVIDIA Corporation\n\t2d04  GB206 [GeForce RTX 5060 Ti]\n"
                "\t\t1462 5116  Some subsystem\nC 00  Unclassified device\n", "utf-8")
            with mock.patch.object(ids, "_data_dir", return_value=Path(tmp)):
                ids._load.cache_clear()
                self.assertEqual(ids.device_name("pci", "10DE", "2D04"), "GeForce RTX 5060 Ti")
                self.assertEqual(ids.vendor_name("pci", "10de"), "NVIDIA Corporation")
                self.assertEqual(ids.vendor_name("usb", "10de"), "")
            ids._load.cache_clear()

    def test_vendor_search_url_official_site(self):
        url = vendors.search_url(gpu())
        self.assertIn("site%3Anvidia.com", url)


class UpdaterTests(unittest.TestCase):
    RELEASE = {
        "tag_name": "v9.9.9", "draft": False, "prerelease": False, "body": "- новое",
        "html_url": "https://github.com/Miffk/DriverUpdater/releases/tag/v9.9.9",
        "assets": [
            {"name": "DriverUpdater.exe", "size": 10, "digest": "sha256:" + "ab" * 32,
             "browser_download_url": "https://github.com/Miffk/DriverUpdater/releases/download/v9.9.9/DriverUpdater.exe"},
            {"name": "SHA256SUMS.txt", "browser_download_url": "https://github.com/x/SHA256SUMS.txt"},
        ],
    }

    def test_parse_release(self):
        info = updater.parse_release(self.RELEASE, "DriverUpdater.exe")
        self.assertTrue(info["available"])
        self.assertEqual(info["version"], "9.9.9")
        self.assertEqual(info["asset"]["sha256"], "ab" * 32)
        self.assertFalse(info["canAutoUpdate"])  # запущено не из exe

    def test_old_release_not_offered(self):
        info = updater.parse_release(dict(self.RELEASE, tag_name="v0.0.1"), "DriverUpdater.exe")
        self.assertFalse(info["available"])

    def test_hash_from_sums_file(self):
        rel = dict(self.RELEASE)
        rel["assets"] = [dict(rel["assets"][0], digest=None), rel["assets"][1]]
        info = updater.parse_release(rel, "DriverUpdater.exe")
        good = hashlib.sha256(b"x").hexdigest()
        with mock.patch.object(updater, "_get", return_value=f"{good}  DriverUpdater.exe\n".encode()):
            self.assertEqual(updater.expected_hash(info), good)

    def test_apply_replaces_exe_and_keeps_old(self):
        payload = b"new exe"
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp, "DriverUpdater.exe")
            exe.write_bytes(b"old exe")
            info = updater.parse_release(self.RELEASE, "DriverUpdater.exe")
            info["asset"]["sha256"] = hashlib.sha256(payload).hexdigest()

            class Resp:
                def __init__(self):
                    self.data = [payload, b""]
                def read(self, n=-1):
                    return self.data.pop(0)
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    return False

            with mock.patch.object(updater, "current_exe", return_value=exe), \
                    mock.patch("urllib.request.urlopen", return_value=Resp()):
                updater.apply(info)
            self.assertEqual(exe.read_bytes(), payload)
            self.assertEqual(Path(tmp, "DriverUpdater.exe.old").read_bytes(), b"old exe")

    def test_apply_rejects_bad_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp, "DriverUpdater.exe")
            exe.write_bytes(b"old exe")
            info = updater.parse_release(self.RELEASE, "DriverUpdater.exe")

            class Resp:
                def __init__(self):
                    self.data = [b"evil", b""]
                def read(self, n=-1):
                    return self.data.pop(0)
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    return False

            with mock.patch.object(updater, "current_exe", return_value=exe), \
                    mock.patch("urllib.request.urlopen", return_value=Resp()):
                with self.assertRaises(RuntimeError):
                    updater.apply(info)
            self.assertEqual(exe.read_bytes(), b"old exe")  # старая версия не тронута


if __name__ == "__main__":
    unittest.main()
