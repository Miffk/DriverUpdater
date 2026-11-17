"""Оценка: какие драйверы необходимы, какие рекомендуются, какие необязательны — и почему."""

from __future__ import annotations

from dataclasses import dataclass

from . import vendors
from .models import Action, Assessment, Device, DriverOffer, Necessity
from .versions import is_newer

# Ошибки Диспетчера устройств — простыми словами.
DRIVER_PROBLEMS = {
    1: "Windows неправильно настроила это устройство.",
    3: "Драйвер устройства повреждён.",
    10: "Устройство не смогло запуститься.",
    18: "Драйвер устройства нужно переустановить.",
    19: "Настройки драйвера в Windows повреждены.",
    28: "Для этого устройства не установлен драйвер.",
    31: "Windows не смогла загрузить драйвер этого устройства.",
    32: "Драйвер устройства отключён.",
    37: "Драйвер устройства не смог запуститься.",
    39: "Драйвер устройства повреждён или отсутствует.",
    41: "Драйвер загружен, но Windows не видит само устройство.",
    43: "Устройство сообщило о сбое, и Windows его остановила.",
    48: "Драйвер заблокирован: он не подходит для этой версии Windows.",
    52: "Windows не смогла проверить подлинность драйвера.",
}
IGNORED_PROBLEMS = {
    22: "Вы отключили это устройство вручную — проверять его не нужно.",
    24: "Устройство сейчас отсутствует или не подключено.",
    45: "Устройство сейчас не подключено к компьютеру.",
}
# Сбои, при которых драйвер обычно ни при чём и помогает перезапуск устройства.
RESTART_PROBLEMS = {1, 3, 10, 31, 37, 41, 43}

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


_STORAGE = ("Диски работают. Менять этот драйвер без причины не стоит — от него зависит "
            "запуск Windows.")
_AUDIO = "Звук уже работает. Обновление даст только мелкие исправления."

RULES: dict[str, ClassRule] = {
    "Display": ClassRule("Видеокарта", Necessity.REQUIRED, Necessity.RECOMMENDED,
                         "В новых версиях исправлены ошибки, игры и видео работают быстрее и стабильнее."),
    "Net": ClassRule("Сеть и интернет", Necessity.REQUIRED, Necessity.RECOMMENDED,
                     "Обновление делает интернет стабильнее и закрывает уязвимости."),
    "Bluetooth": ClassRule("Bluetooth", Necessity.REQUIRED, Necessity.RECOMMENDED,
                           "Обновление помогает, если отключаются беспроводные наушники или геймпад."),
    "System": ClassRule("Материнская плата (чипсет)", Necessity.REQUIRED, Necessity.RECOMMENDED,
                        "Этот драйвер отвечает за стабильную работу материнской платы, "
                        "USB-разъёмов и энергосбережение."),
    "MEDIA": ClassRule("Звук", Necessity.REQUIRED, Necessity.OPTIONAL, _AUDIO),
    "Media": ClassRule("Звук", Necessity.REQUIRED, Necessity.OPTIONAL, _AUDIO),
    "HDC": ClassRule("Контроллер дисков", Necessity.REQUIRED, Necessity.OPTIONAL, _STORAGE),
    "SCSIAdapter": ClassRule("Контроллер дисков", Necessity.REQUIRED, Necessity.OPTIONAL, _STORAGE),
    "Camera": ClassRule("Веб-камера", Necessity.REQUIRED, Necessity.OPTIONAL,
                        "Камера уже работает. Обновление обычно ничего заметного не меняет."),
    "Biometric": ClassRule("Сканер отпечатков пальцев", Necessity.REQUIRED, Necessity.OPTIONAL,
                           "Сканер работает. Обновлять стоит, только если он плохо узнаёт палец."),
    "Sensor": ClassRule("Датчики (поворот экрана, яркость)", Necessity.RECOMMENDED, Necessity.OPTIONAL,
                        "Датчики работают, обновление по желанию."),
    "Battery": ClassRule("Батарея", Necessity.REQUIRED, Necessity.OPTIONAL,
                         "Заряд показывается правильно, обновление по желанию."),
    "Extension": ClassRule("Дополнение от производителя", Necessity.OPTIONAL, Necessity.OPTIONAL,
                           "Это дополнение от производителя компьютера (фирменные настройки), "
                           "а не основной драйвер."),
    "SoftwareComponent": ClassRule("Служебная программа драйвера", Necessity.OPTIONAL, Necessity.OPTIONAL,
                                   "Это служебная программа к драйверу (например, панель настроек). "
                                   "На работу устройства она не влияет."),
    "Firmware": ClassRule("Прошивка (BIOS)", Necessity.OPTIONAL, Necessity.OPTIONAL,
                          "Это обновление прошивки (BIOS). Ставьте его, только если есть конкретная "
                          "проблема: если во время обновления пропадёт питание, компьютер может "
                          "перестать включаться."),
}

INBOX_TITLES = {
    "USB": "USB-разъёмы", "HIDClass": "Устройство ввода", "Keyboard": "Клавиатура",
    "Mouse": "Мышь или тачпад", "Monitor": "Монитор", "DiskDrive": "Диск", "Volume": "Раздел диска",
    "VolumeSnapshot": "Резервная копия диска", "CDROM": "Дисковод", "Processor": "Процессор",
    "Computer": "Компьютер", "SoftwareDevice": "Служебное устройство Windows",
    "LegacyDriver": "Служебный драйвер Windows", "PrintQueue": "Принтер", "Printer": "Принтер",
    "WPD": "Телефон или флешка", "AudioEndpoint": "Динамики и микрофоны",
    "SmartCardReader": "Считыватель карт", "Ports": "Порты", "Image": "Камера или сканер",
    "UCM": "USB Type-C", "SecurityDevices": "Модуль безопасности",
}


# Совместимость: эти функции раньше жили здесь.
vendor_id = vendors.vendor_id
vendor_name = vendors.vendor_name


def vendor_hint(device: Device) -> str:
    v = vendors.lookup(device)
    return f"{v.name}: {v.drivers_url}" if v and v.drivers_url else ""


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
        "Неизвестное устройство" if not cls else cls, Necessity.RECOMMENDED, Necessity.OPTIONAL,
        "Устройство работает, обновление по желанию."))


OTHER_TITLES = {
    "AudioProcessingObject": "Звуковые эффекты", "OtherHardware": "Другое устройство",
    "SDHost": "Кардридер", "MTD": "Карта памяти", "Infrared": "ИК-порт", "Modem": "Модем",
    "MultiFunction": "Многофункциональное устройство", "MediumChanger": "Устройство хранения",
    "TapeDrive": "Ленточный накопитель", "1394": "Порт FireWire", "PCMCIA": "Слот PCMCIA",
    "SmartCard": "Смарт-карта", "Holographic": "Шлем смешанной реальности", "XboxComposite": "Геймпад Xbox",
    "WSDPrintDevice": "Сетевой принтер", "NetService": "Сетевая служба", "NetClient": "Сетевой клиент",
    "NetTrans": "Сетевой протокол", "SecurityAccelerator": "Ускоритель шифрования",
    "Proximity": "NFC", "SoftwareComponent": "Служебная программа драйвера",
    "ComputeAccelerator": "Ускоритель вычислений", "Endpoint": "Аудиоустройство",
}


def class_title(cls: str) -> str:
    """Понятное название класса устройства для интерфейса."""
    if cls in INBOX_TITLES:
        return INBOX_TITLES[cls]
    if cls in RULES:
        return RULES[cls].title
    if cls in OTHER_TITLES:
        return OTHER_TITLES[cls]
    return "Другое устройство" if cls else "Неизвестное устройство"


def assess(device: Device, offer: DriverOffer | None, searched: bool = True) -> Assessment:
    cls = effective_class(device, offer)
    rule = _rule(cls)
    hint = vendor_hint(device)

    def result(nec, act, reason, use_offer=True, auto=True, repairable=False):
        return Assessment(device, nec, act, reason, offer if use_offer else None,
                          manual_hint=hint if nec.rank <= 1 and act != Action.NONE else "",
                          auto_install=auto, repairable=repairable)

    code = device.problem_code
    if code in IGNORED_PROBLEMS:
        return result(Necessity.NOT_NEEDED, Action.NONE, IGNORED_PROBLEMS[code], use_offer=False)

    firmware = cls == "Firmware" or (offer is not None and offer.is_firmware)

    # 1. Устройство не работает.
    if code in DRIVER_PROBLEMS or (not device.has_driver and code):
        problem = DRIVER_PROBLEMS.get(code, "С устройством что-то не так.")
        right_driver = device.has_driver and (cls in INBOX_CLASSES or is_microsoft_driver(device))
        if offer is None and right_driver and code in RESTART_PROBLEMS:
            # Драйвер подходящий — дело не в нём. Так бывает у USB-устройств, подсветки и т.п.
            usb = vendors.bus(device) == "usb"
            tips = ("Обычно помогает перезапустить устройство (кнопка ниже), вставить его в другой "
                    "USB-разъём или перезагрузить компьютер. Если не поможет — возможно, неисправно "
                    "само устройство или кабель." if usb else
                    "Попробуйте перезапустить устройство (кнопка ниже) или перезагрузить компьютер. "
                    "Если не поможет — поищите драйвер на сайте производителя.")
            return result(Necessity.REQUIRED, Action.REPAIR,
                          f"{problem} Драйвер тут, скорее всего, ни при чём: для такого устройства "
                          f"подходит стандартный драйвер Windows, и он уже установлен. {tips}",
                          use_offer=False, repairable=True)
        nec = Necessity.REQUIRED if rule.missing != Necessity.OPTIONAL else Necessity.OPTIONAL
        return result(nec, Action.INSTALL, f"{problem} Без подходящего драйвера оно не работает.",
                      auto=not firmware, repairable=device.has_driver)

    # 2. Видеокарта на временном драйвере Windows.
    if is_basic_display(device):
        return result(Necessity.REQUIRED, Action.INSTALL,
                      "Сейчас вместо драйвера видеокарты работает временный драйвер Windows. "
                      "Из-за этого не работают игры и ускорение видео, а экран может показывать "
                      "не в полном разрешении.")

    # 3. Есть более новая версия.
    if offer and (offer.known_newer or is_newer(offer.version, offer.date,
                                                device.driver_version, device.driver_date)):
        if firmware:
            return result(Necessity.OPTIONAL, Action.UPDATE, RULES["Firmware"].update_reason, auto=False)
        nec, reason = rule.update, rule.update_reason
        if is_generic_audio(device):
            nec = Necessity.RECOMMENDED
            reason = ("Сейчас стоит универсальный драйвер звука от Windows. Драйвер производителя "
                      "добавит фирменные настройки звука и микрофона.")
        elif cls in INBOX_CLASSES:
            nec = Necessity.OPTIONAL
            reason = ("Стандартный драйвер Windows для такого устройства тоже работает хорошо — "
                      "обновлять не обязательно.")
        return result(nec, Action.UPDATE, f"Есть более новая версия драйвера. {reason}")

    # 4. Всё в порядке.
    if cls in INBOX_CLASSES or device.is_virtual:
        why = "Стоит стандартный драйвер Windows — для этого устройства он подходит лучше всего."
    elif not searched:
        why = "Драйвер установлен и работает. Обновления ещё не проверялись."
    elif is_microsoft_driver(device):
        why = "Работает на драйвере из состава Windows. Более новой официальной версии нет."
    else:
        why = "Драйвер установлен и работает. Более новой версии нет."
    return result(Necessity.NOT_NEEDED, Action.NONE, why, use_offer=False)


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
