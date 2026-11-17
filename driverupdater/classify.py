"""Оценка: какие драйверы необходимы, какие рекомендуются, какие необязательны — и почему."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Action, Assessment, Device, DriverOffer, Necessity
from .versions import is_newer

# Коды ошибок Диспетчера устройств, которые лечатся установкой драйвера.
DRIVER_PROBLEMS = {
    1: "устройство настроено неправильно (код 1)",
    3: "драйвер повреждён или не хватает памяти (код 3)",
    10: "устройство не может запуститься (код 10)",
    18: "драйвер нужно переустановить (код 18)",
    19: "ошибка в реестре драйвера (код 19)",
    28: "драйвер не установлен (код 28)",
    31: "Windows не смогла загрузить драйвер (код 31)",
    32: "служба драйвера отключена (код 32)",
    37: "драйвер вернул ошибку при инициализации (код 37)",
    39: "драйвер повреждён или отсутствует (код 39)",
    41: "драйвер загружен, но устройство не найдено (код 41)",
    43: "устройство сообщило о сбое (код 43)",
    48: "драйвер заблокирован из-за проблем совместимости (код 48)",
    52: "не удалось проверить цифровую подпись драйвера (код 52)",
}
IGNORED_PROBLEMS = {
    22: "устройство отключено вами в Диспетчере устройств",
    24: "устройство отсутствует или не подключено",
    45: "устройство сейчас не подключено к компьютеру",
}

# Классы устройств, где «родной» драйвер Microsoft — правильный выбор.
INBOX_CLASSES = {
    "USB", "HIDClass", "Keyboard", "Mouse", "Monitor", "DiskDrive", "Volume",
    "VolumeSnapshot", "CDROM", "Processor", "Computer", "SoftwareDevice",
    "LegacyDriver", "PrintQueue", "WPD", "AudioEndpoint", "SmartCardReader",
    "Ports", "Image", "Printer", "UCM", "SecurityDevices",
}


@dataclass(frozen=True)
class ClassRule:
    title: str
    missing: Necessity   # если драйвера нет
    update: Necessity    # если вышла новая версия
    update_reason: str


RULES: dict[str, ClassRule] = {
    "Display": ClassRule(
        "Видеокарта", Necessity.REQUIRED, Necessity.RECOMMENDED,
        "новые версии исправляют ошибки, повышают производительность и совместимость с играми"),
    "Net": ClassRule(
        "Сеть (Ethernet/Wi-Fi)", Necessity.REQUIRED, Necessity.RECOMMENDED,
        "сетевой драйвер напрямую связан с безопасностью и стабильностью подключения"),
    "Bluetooth": ClassRule(
        "Bluetooth", Necessity.REQUIRED, Necessity.RECOMMENDED,
        "обновления исправляют обрывы связи и проблемы с наушниками/геймпадами"),
    "System": ClassRule(
        "Системные устройства (чипсет)", Necessity.REQUIRED, Necessity.RECOMMENDED,
        "драйверы чипсета отвечают за энергосбережение, шины PCIe/USB и стабильность системы"),
    "MEDIA": ClassRule(
        "Звук", Necessity.REQUIRED, Necessity.OPTIONAL,
        "звук уже работает; новая версия даёт мелкие исправления и фирменные функции"),
    "Media": ClassRule(
        "Звук", Necessity.REQUIRED, Necessity.OPTIONAL,
        "звук уже работает; новая версия даёт мелкие исправления и фирменные функции"),
    "HDC": ClassRule(
        "Контроллер дисков (SATA/NVMe)", Necessity.REQUIRED, Necessity.OPTIONAL,
        "работающий драйвер контроллера дисков лучше не менять без причины — "
        "от него зависит загрузка Windows"),
    "SCSIAdapter": ClassRule(
        "Контроллер хранения (RAID/NVMe)", Necessity.REQUIRED, Necessity.OPTIONAL,
        "работающий драйвер контроллера дисков лучше не менять без причины — "
        "от него зависит загрузка Windows"),
    "Camera": ClassRule(
        "Веб-камера", Necessity.REQUIRED, Necessity.OPTIONAL,
        "камера уже работает; обновление обычно не меняет ничего заметного"),
    "Biometric": ClassRule(
        "Сканер отпечатков/Windows Hello", Necessity.REQUIRED, Necessity.OPTIONAL,
        "сканер работает; обновление нужно только при проблемах с распознаванием"),
    "Sensor": ClassRule(
        "Датчики (поворот экрана, освещённость)", Necessity.RECOMMENDED, Necessity.OPTIONAL,
        "датчики работают; обновление по желанию"),
    "Battery": ClassRule(
        "Батарея/питание", Necessity.REQUIRED, Necessity.OPTIONAL,
        "индикация заряда работает; обновление по желанию"),
    "Extension": ClassRule(
        "Расширение драйвера производителя", Necessity.OPTIONAL, Necessity.OPTIONAL,
        "это надстройка производителя ПК (настройки, фирменные функции), а не основной драйвер"),
    "SoftwareComponent": ClassRule(
        "Программный компонент драйвера", Necessity.OPTIONAL, Necessity.OPTIONAL,
        "вспомогательное ПО к драйверу (панель управления, служба), не влияет на работу устройства"),
    "Firmware": ClassRule(
        "Прошивка (BIOS/UEFI/контроллеры)", Necessity.OPTIONAL, Necessity.OPTIONAL,
        "обновление прошивки нужно только при известных проблемах; сбой питания во время "
        "прошивки может вывести ПК из строя — ставьте вручную и осознанно"),
}

VENDOR_PAGES = {
    "10DE": ("NVIDIA", "https://www.nvidia.com/Download/index.aspx"),
    "1002": ("AMD", "https://www.amd.com/en/support/download/drivers.html"),
    "1022": ("AMD", "https://www.amd.com/en/support/download/drivers.html"),
    "8086": ("Intel", "https://www.intel.com/content/www/us/en/support/detect.html"),
    "10EC": ("Realtek", "https://www.realtek.com/Download/List?cate_id=584"),
    "14E4": ("Broadcom", "https://www.broadcom.com/support/download-search"),
    "168C": ("Qualcomm Atheros", "https://www.qualcomm.com/support"),
    "17CB": ("Qualcomm", "https://www.qualcomm.com/support"),
    "14C3": ("MediaTek", "https://www.mediatek.com/products/connectivity-and-networking"),
}


def vendor_id(device: Device) -> str:
    for hid in device.hardware_ids:
        u = hid.upper()
        for key in ("VEN_", "VID_"):
            if key in u:
                return u.split(key, 1)[1][:4]
    return ""


# Производители по PCI/USB Vendor ID — чтобы показать понятное имя вместо безликого
# «Сетевой контроллер» или «Microsoft Basic Display Adapter».
VENDOR_NAMES = {
    "10DE": "NVIDIA", "1002": "AMD", "1022": "AMD", "8086": "Intel", "10EC": "Realtek",
    "14E4": "Broadcom", "168C": "Qualcomm Atheros", "17CB": "Qualcomm", "14C3": "MediaTek",
    "1B21": "ASMedia", "1969": "Qualcomm Atheros", "11AB": "Marvell", "144D": "Samsung",
    "15B7": "SanDisk/WD", "1C5C": "SK hynix", "126F": "Silicon Motion", "1987": "Phison",
    "1179": "Toshiba/Kioxia", "1E0F": "Kioxia", "8087": "Intel", "0BDA": "Realtek",
    "046D": "Logitech", "045E": "Microsoft", "05AC": "Apple", "1532": "Razer", "1038": "SteelSeries",
    "0B05": "ASUS", "1462": "MSI", "1458": "Gigabyte", "13D3": "IMC Networks", "04F2": "Chicony",
    "0C45": "Microdia", "27C6": "Goodix", "06CB": "Synaptics", "138A": "Validity", "1D6B": "Linux Foundation",
    "1106": "VIA", "1217": "O2 Micro", "5143": "Qualcomm", "1D17": "Zhaoxin",
    "1B4B": "Marvell", "8564": "Transcend", "0781": "SanDisk", "0951": "Kingston",
    "111D": "IDT", "14F1": "Conexant", "1102": "Creative", "1095": "Silicon Image",
}


def vendor_name(device: Device) -> str:
    vid = vendor_id(device)
    return VENDOR_NAMES.get(vid) or (VENDOR_PAGES.get(vid, ("",))[0])


def vendor_hint(device: Device) -> str:
    info = VENDOR_PAGES.get(vendor_id(device))
    return f"{info[0]}: {info[1]}" if info else ""


def is_basic_display(device: Device) -> bool:
    return device.device_class == "Display" and (
        device.inf_name.lower() in ("display.inf", "basicdisplay.inf")
        or "basic display" in device.name.lower()
        or "базовый видеоадаптер" in device.name.lower())


def is_generic_audio(device: Device) -> bool:
    return device.device_class.upper() == "MEDIA" and device.inf_name.lower() == "hdaudio.inf"


def is_microsoft_driver(device: Device) -> bool:
    return device.driver_provider.strip().lower() in ("microsoft", "майкрософт") or (
        device.inf_name and not device.inf_name.lower().startswith("oem"))


# Базовый класс PCI-устройства (CC_xx) → класс Windows. Нужен для устройств без драйвера,
# у которых Windows ещё не знает класс («Неизвестное устройство», «Сетевой контроллер»).
PCI_CLASS_CODES = {"01": "HDC", "02": "Net", "03": "Display", "04": "MEDIA",
                   "08": "System", "0C": "System", "0D": "Bluetooth"}


def effective_class(device: Device, offer: DriverOffer | None = None) -> str:
    if device.device_class:
        return device.device_class
    if offer and offer.driver_class in RULES:
        return offer.driver_class
    for cid in device.all_ids:
        u = cid.upper()
        if "CC_" in u:
            return PCI_CLASS_CODES.get(u.split("CC_", 1)[1][:2], "")
    return ""


def _rule(cls: str) -> ClassRule:
    return RULES.get(cls, ClassRule(
        cls or "Неизвестное устройство", Necessity.RECOMMENDED, Necessity.OPTIONAL,
        "устройство работает; обновление по желанию"))


INBOX_TITLES = {
    "USB": "USB-контроллеры", "HIDClass": "Устройства ввода", "Keyboard": "Клавиатура",
    "Mouse": "Мышь и тачпад", "Monitor": "Монитор", "DiskDrive": "Диск", "Volume": "Том диска",
    "VolumeSnapshot": "Теневая копия тома", "CDROM": "Оптический привод", "Processor": "Процессор",
    "Computer": "Компьютер", "SoftwareDevice": "Программное устройство",
    "LegacyDriver": "Системный драйвер", "PrintQueue": "Очередь печати", "Printer": "Принтер",
    "WPD": "Портативное устройство", "AudioEndpoint": "Аудиовыход/вход",
    "SmartCardReader": "Считыватель смарт-карт", "Ports": "Порты COM/LPT",
    "Image": "Камера/сканер", "UCM": "USB Type-C", "SecurityDevices": "Модуль безопасности (TPM)",
}


def class_title(cls: str) -> str:
    """Понятное название класса устройства для интерфейса."""
    return INBOX_TITLES.get(cls) or _rule(cls).title


def assess(device: Device, offer: DriverOffer | None, searched: bool = True) -> Assessment:
    cls = effective_class(device, offer)
    rule = _rule(cls)
    title = class_title(cls)
    hint = vendor_hint(device)

    def result(nec, act, reason, use_offer=True, auto=True):
        return Assessment(device, nec, act, reason, offer if use_offer else None,
                          manual_hint=hint if nec.rank <= 1 and act != Action.NONE else "",
                          auto_install=auto)

    if device.problem_code in IGNORED_PROBLEMS:
        return result(Necessity.NOT_NEEDED, Action.NONE,
                      IGNORED_PROBLEMS[device.problem_code].capitalize() + ".", use_offer=False)

    firmware = cls == "Firmware" or (offer is not None and offer.is_firmware)

    # 1. Устройство не работает из-за драйвера.
    if device.problem_code in DRIVER_PROBLEMS or (not device.has_driver and device.problem_code):
        why = DRIVER_PROBLEMS.get(device.problem_code, f"ошибка устройства (код {device.problem_code})")
        nec = Necessity.REQUIRED if rule.missing != Necessity.OPTIONAL else Necessity.OPTIONAL
        return result(nec, Action.INSTALL,
                      f"{title}: {why} — без драйвера устройство не работает.",
                      auto=not firmware)

    # 2. Видеокарта на базовом драйвере Microsoft.
    if is_basic_display(device):
        return result(Necessity.REQUIRED, Action.INSTALL,
                      "Видеокарта работает на «Базовом видеоадаптере Microsoft»: нет аппаратного "
                      "ускорения, игр, нормальной частоты обновления и выбора разрешения.")

    # 3. Есть более новая версия в официальном источнике.
    if offer and is_newer(offer.version, offer.date, device.driver_version, device.driver_date):
        if firmware:
            return result(Necessity.OPTIONAL, Action.UPDATE,
                          f"{RULES['Firmware'].title}: {RULES['Firmware'].update_reason}.", auto=False)
        nec, reason = rule.update, rule.update_reason
        if is_generic_audio(device):
            nec = Necessity.RECOMMENDED
            reason = ("сейчас стоит универсальный драйвер Microsoft; драйвер производителя "
                      "включает определение разъёмов, микрофонные эффекты и фирменные настройки")
        elif cls in INBOX_CLASSES:
            nec = Necessity.OPTIONAL
            reason = "стандартный драйвер Windows для этого класса устройств работает корректно"
        new = " от ".join(x for x in (offer.version, offer.date) if x)
        cur = " от ".join(x for x in (device.driver_version, device.driver_date) if x) or "нет"
        return result(nec, Action.UPDATE,
                      f"{title}: доступна версия {new} (сейчас {cur}) — {reason}.")

    # 4. Всё в порядке.
    if cls in INBOX_CLASSES or device.is_virtual:
        why = "используется стандартный драйвер Windows — это правильный выбор для такого устройства."
    elif not searched:
        why = "драйвер установлен и работает (наличие обновлений проверяет команда check)."
    elif is_microsoft_driver(device):
        why = "работает на драйвере Microsoft из состава Windows, более нового официального не найдено."
    else:
        why = "драйвер установлен и работает; более новой версии в официальных источниках нет."
    return result(Necessity.NOT_NEEDED, Action.NONE, f"{title}: {why}", use_offer=False)


def match_offers(devices: list[Device], offers: list[DriverOffer]
                 ) -> tuple[dict[str, DriverOffer], list[DriverOffer]]:
    """Сопоставляет найденные драйверы с устройствами по Hardware ID.
    Возвращает (instance_id -> лучшее предложение, несопоставленные предложения)."""
    by_device: dict[str, DriverOffer] = {}
    unmatched: list[DriverOffer] = []
    for off in offers:
        hits = [d for d in devices if off.hardware_id and d.matches_hwid(off.hardware_id)]
        if not hits:
            unmatched.append(off)
            continue
        for d in hits:
            cur = by_device.get(d.instance_id)
            if cur is None or is_newer(off.version, off.date, cur.version, cur.date):
                by_device[d.instance_id] = off
    return by_device, unmatched


def assess_all(devices: list[Device], offers: dict[str, DriverOffer],
               searched: bool = True) -> list[Assessment]:
    items = [assess(d, offers.get(d.instance_id), searched) for d in devices]
    items.sort(key=lambda a: (a.necessity.rank, a.device.device_class, a.device.name))
    return items
