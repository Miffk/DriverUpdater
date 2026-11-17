"""Производители устройств и их официальные сайты с драйверами.

Код производителя берётся из ID оборудования (PCI\\VEN_xxxx или USB\\VID_xxxx).
Для известных — короткое имя и официальная страница драйверов; для остальных имя
берётся из открытых баз pci.ids/usb.ids (если они есть в сборке, см. ids.py).
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from . import ids, names
from .models import Device


@dataclass(frozen=True)
class Vendor:
    name: str
    drivers_url: str = ""   # официальная страница драйверов/поддержки
    domain: str = ""        # официальный домен — для поиска только по нему
    tool: str = ""          # официальная программа автоподбора драйверов: "amd" | "intel" | "nvidia"


NVIDIA = Vendor("NVIDIA", "https://www.nvidia.com/ru-ru/drivers/", "nvidia.com", "nvidia")
AMD = Vendor("AMD", "https://www.amd.com/ru/support/download/drivers.html", "amd.com", "amd")
INTEL = Vendor("Intel", "https://www.intel.ru/content/www/ru/ru/support/detect.html", "intel.com", "intel")
REALTEK = Vendor("Realtek", "https://www.realtek.com/Download/Index", "realtek.com")

VENDORS: dict[str, Vendor] = {
    # PCI
    "10DE": NVIDIA, "1002": AMD, "1022": AMD, "8086": INTEL, "8087": INTEL, "10EC": REALTEK,
    "14E4": Vendor("Broadcom", "https://www.broadcom.com/support/download-search", "broadcom.com"),
    "168C": Vendor("Qualcomm Atheros", "https://www.qualcomm.com/support", "qualcomm.com"),
    "17CB": Vendor("Qualcomm", "https://www.qualcomm.com/support", "qualcomm.com"),
    "1969": Vendor("Qualcomm Atheros", "https://www.qualcomm.com/support", "qualcomm.com"),
    "14C3": Vendor("MediaTek", "https://www.mediatek.com/", "mediatek.com"),
    "1B21": Vendor("ASMedia", "https://www.asmedia.com.tw/", "asmedia.com.tw"),
    "11AB": Vendor("Marvell", "https://www.marvell.com/support.html", "marvell.com"),
    "1B4B": Vendor("Marvell", "https://www.marvell.com/support.html", "marvell.com"),
    "144D": Vendor("Samsung", "https://semiconductor.samsung.com/consumer-storage/support/tools/", "samsung.com"),
    "15B7": Vendor("WD", "https://support-en.wd.com/app/products/downloads", "wd.com"),
    "1C5C": Vendor("SK hynix", "https://ssd.skhynix.com/download/", "skhynix.com"),
    "1E0F": Vendor("Kioxia", "https://www.kioxia.com/", "kioxia.com"),
    "1179": Vendor("Toshiba", "https://www.toshiba.com/", "toshiba.com"),
    "126F": Vendor("Silicon Motion"), "1987": Vendor("Phison"),
    "1106": Vendor("VIA", "https://www.viatech.com/en/support/drivers/", "viatech.com"),
    "1217": Vendor("O2 Micro"), "1D17": Vendor("Zhaoxin"),
    "14F1": Vendor("Conexant"), "111D": Vendor("IDT"),
    "1102": Vendor("Creative", "https://support.creative.com/", "creative.com"),
    "1462": Vendor("MSI", "https://ru.msi.com/support/download", "msi.com"),
    "1458": Vendor("Gigabyte", "https://www.gigabyte.com/ru/Support", "gigabyte.com"),
    "1043": Vendor("ASUS", "https://www.asus.com/ru/support/download-center/", "asus.com"),
    "1849": Vendor("ASRock", "https://www.asrock.com/support/index.ru.asp", "asrock.com"),
    "1028": Vendor("Dell", "https://www.dell.com/support/home/ru-ru", "dell.com"),
    "103C": Vendor("HP", "https://support.hp.com/ru-ru/drivers", "hp.com"),
    "17AA": Vendor("Lenovo", "https://pcsupport.lenovo.com/ru/ru", "lenovo.com"),
    "1025": Vendor("Acer", "https://www.acer.com/ru-ru/support/drivers-and-manuals", "acer.com"),
    # USB
    "046D": Vendor("Logitech", "https://support.logi.com/hc/ru/sections/360004362813", "logitech.com"),
    "045E": Vendor("Microsoft", "https://support.microsoft.com/", "microsoft.com"),
    "05AC": Vendor("Apple", "https://support.apple.com/", "apple.com"),
    "1532": Vendor("Razer", "https://www.razer.com/synapse-4", "razer.com"),
    "1038": Vendor("SteelSeries", "https://steelseries.com/gg", "steelseries.com"),
    "1B1C": Vendor("Corsair", "https://www.corsair.com/ru/ru/s/downloads", "corsair.com"),
    "0951": Vendor("Kingston", "https://www.kingston.com/ru/support", "kingston.com"),
    "0781": Vendor("SanDisk", "https://www.westerndigital.com/support", "westerndigital.com"),
    "0B05": Vendor("ASUS", "https://www.asus.com/ru/support/download-center/", "asus.com"),
    "0BDA": REALTEK, "13D3": Vendor("Azurewave"), "04F2": Vendor("Chicony"), "0C45": Vendor("Microdia"),
    "27C6": Vendor("Goodix"), "06CB": Vendor("Synaptics", "https://www.synaptics.com/", "synaptics.com"),
    "138A": Vendor("Synaptics"), "04F3": Vendor("ELAN"),
    "0416": Vendor("Winbond"), "1A86": Vendor("WCH"), "0483": Vendor("STMicroelectronics"),
    "10C4": Vendor("Silicon Labs", "https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers", "silabs.com"),
    "0403": Vendor("FTDI", "https://ftdichip.com/drivers/", "ftdichip.com"),
    "067B": Vendor("Prolific", "https://www.prolific.com.tw/", "prolific.com.tw"),
    "2109": Vendor("VIA Labs"), "05E3": Vendor("Genesys Logic"),
    "1D6B": Vendor("Linux Foundation"), "8564": Vendor("Transcend"),
    "054C": Vendor("Sony", "https://www.playstation.com/ru-ru/support/", "playstation.com"),
    "057E": Vendor("Nintendo"),
    "28DE": Vendor("Valve", "https://store.steampowered.com/about/", "steampowered.com"),
    "3297": Vendor("ZSA"), "0D8C": Vendor("C-Media"), "1395": Vendor("EPOS/Sennheiser"),
    "04E8": Vendor("Samsung", "https://www.samsung.com/ru/support/", "samsung.com"),
    "22B8": Vendor("Motorola"), "18D1": Vendor("Google"), "2717": Vendor("Xiaomi"),
    "12D1": Vendor("Huawei"), "04B8": Vendor("Epson", "https://epson.ru/support/", "epson.ru"),
    "04A9": Vendor("Canon", "https://www.canon.ru/support/", "canon.ru"),
    "03F0": Vendor("HP", "https://support.hp.com/ru-ru/drivers", "hp.com"),
    "04F9": Vendor("Brother", "https://support.brother.com/", "brother.com"),
    "043D": Vendor("Lexmark"), "0924": Vendor("Xerox", "https://www.support.xerox.com/", "xerox.com"),
    "0A12": Vendor("Cambridge Silicon Radio"),
}

# Производители микросхем, которые сами драйверы для конечных устройств не выпускают:
# их чипы стоят в клавиатурах, подсветке, переходниках разных брендов.
CHIP_ONLY = {"0416", "1A86", "0483", "05E3", "2109", "0A12", "1D6B", "0C45", "13D3", "04F2"}


def vendor_id(device: Device) -> str:
    for hid in device.hardware_ids:
        u = hid.upper()
        for key in ("VEN_", "VID_"):
            if key in u:
                return u.split(key, 1)[1][:4]
    return ""


def product_id(device: Device) -> str:
    for hid in device.hardware_ids:
        u = hid.upper()
        for key in ("DEV_", "PID_"):
            if key in u:
                return u.split(key, 1)[1][:4]
    return ""


def bus(device: Device) -> str:
    first = (device.hardware_ids or [device.instance_id] or [""])[0].upper()
    return "usb" if first.startswith(("USB\\", "HID\\")) else "pci" if first.startswith("PCI\\") else ""


def lookup(device: Device) -> Vendor | None:
    vid = vendor_id(device)
    if not vid:
        return None
    if vid in VENDORS:
        return VENDORS[vid]
    name = ids.vendor_name(bus(device), vid)
    return Vendor(names.brand(name)) if name else None


def vendor_name(device: Device) -> str:
    v = lookup(device)
    return v.name if v else ""


def model_name(device: Device) -> str:
    """Название модели по открытой базе: «GeForce RTX 3060» для PCI\\VEN_10DE&DEV_2504."""
    return ids.device_name(bus(device), vendor_id(device), product_id(device))


def search_url(device: Device) -> str:
    """Поиск драйвера только по официальному сайту производителя (если он известен)."""
    v = lookup(device)
    model = model_name(device) or device.name
    hwid = device.hardware_ids[0] if device.hardware_ids else ""
    if v and v.domain and vendor_id(device) not in CHIP_ONLY:
        q = f"{model} драйвер site:{v.domain}"
    else:
        short = hwid.split("&REV_")[0].split("&MI_")[0]
        q = f"\"{short}\" драйвер"
    return "https://www.google.com/search?q=" + urllib.parse.quote(q)
