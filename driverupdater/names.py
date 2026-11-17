"""Понятные названия: «MSI» вместо «Micro-Star International Co., Ltd.», «Windows 11 Pro 24H2»
вместо «Microsoft Windows 11 Pro, сборка 26100» и т.п. Всё, что видит пользователь, —
коротко и без технических кодов."""

from __future__ import annotations

import re

# Официальное (юридическое) название → бренд, который знают покупатели.
BRANDS: list[tuple[str, str]] = [
    (r"micro[- ]?star|^msi\b", "MSI"),
    (r"asustek|^asus", "ASUS"),
    (r"gigabyte|giga-byte", "Gigabyte"),
    (r"asrock", "ASRock"),
    (r"biostar", "Biostar"),
    (r"hewlett[- ]?packard|^hp\b|hp inc", "HP"),
    (r"lenovo", "Lenovo"),
    (r"^dell", "Dell"),
    (r"^acer", "Acer"),
    (r"apple", "Apple"),
    (r"samsung", "Samsung"),
    (r"huawei", "Huawei"),
    (r"honor device|^honor", "Honor"),
    (r"xiaomi|redmi", "Xiaomi"),
    (r"microsoft|майкрософт", "Microsoft"),
    (r"advanced micro devices|^amd\b|ati technologies", "AMD"),
    (r"nvidia", "NVIDIA"),
    (r"intel", "Intel"),
    (r"realtek", "Realtek"),
    (r"qualcomm atheros|atheros", "Qualcomm Atheros"),
    (r"qualcomm", "Qualcomm"),
    (r"mediatek", "MediaTek"),
    (r"broadcom", "Broadcom"),
    (r"marvell", "Marvell"),
    (r"toshiba", "Toshiba"),
    (r"kioxia", "Kioxia"),
    (r"sony", "Sony"),
    (r"fujitsu", "Fujitsu"),
    (r"panasonic", "Panasonic"),
    (r"razer", "Razer"),
    (r"logitech", "Logitech"),
    (r"steelseries", "SteelSeries"),
    (r"corsair", "Corsair"),
    (r"hyperx", "HyperX"),
    (r"kingston", "Kingston"),
    (r"western digital|^wdc?\b", "WD"),
    (r"seagate", "Seagate"),
    (r"crucial", "Crucial"),
    (r"micron", "Micron"),
    (r"sk ?hynix|hynix", "SK hynix"),
    (r"sandisk", "SanDisk"),
    (r"winbond", "Winbond"),
    (r"nuvoton", "Nuvoton"),
    (r"american megatrends", "AMI"),
    (r"phoenix technologies", "Phoenix"),
    (r"insyde", "Insyde"),
    (r"supermicro|super micro", "Supermicro"),
    (r"evga", "EVGA"),
    (r"zotac", "Zotac"),
    (r"sapphire", "Sapphire"),
    (r"palit", "Palit"),
    (r"gainward", "Gainward"),
    (r"^pny", "PNY"),
    (r"medion", "Medion"),
    (r"chuwi", "Chuwi"),
    (r"maxsun", "Maxsun"),
    (r"colorful", "Colorful"),
    (r"synaptics", "Synaptics"),
    (r"elan microelectronics|^elan\b", "ELAN"),
    (r"goodix", "Goodix"),
    (r"creative", "Creative"),
    (r"asmedia", "ASMedia"),
    (r"via technologies|^via\b", "VIA"),
    (r"silicon motion", "Silicon Motion"),
    (r"phison", "Phison"),
]

# Заглушки, которые производители оставляют вместо названия.
PLACEHOLDERS = re.compile(
    r"^(to be filled by o\.?e\.?m\.?|system manufacturer|system product name|default string|"
    r"o\.?e\.?m\.?|not applicable|not specified|none|invalid|type1productconfigid|"
    r"system version|base board product name|x\.x|0+|123456789)$", re.I)

LEGAL_SUFFIX = re.compile(
    r"[,.]?\s*\b(co\.?,?\s*ltd\.?|ltd\.?|inc\.?|incorporated|corporation|corp\.?|llc|gmbh|"
    r"s\.?a\.?|b\.?v\.?|ag|plc|limited|company|technology|technologies|electronics|"
    r"international|computer)\b\.?", re.I)


def is_placeholder(text: str) -> bool:
    return not text or bool(PLACEHOLDERS.match(text.strip()))


def brand(text: str) -> str:
    """Короткое узнаваемое название производителя."""
    t = (text or "").strip()
    if is_placeholder(t):
        return ""
    t = re.sub(r"\(r\)|\(tm\)|®|™", "", t, flags=re.I).strip()
    for pattern, short in BRANDS:
        if re.search(pattern, t, re.I):
            return short
    # Неизвестный производитель: убираем «Co., Ltd.», «Inc.» и т.п.
    short = LEGAL_SUFFIX.sub("", t).strip(" ,.-")
    short = re.sub(r"\s+\[.*?\]$", "", short)  # «Foo Inc. [Bar]» из базы pci.ids
    if short.isupper() and len(short) > 5:
        short = short.title()
    return short or t


def pretty_model(model: str, maker: str = "") -> str:
    """Модель без внутренних кодов: «PRO B650M-B (MS-7E28)» → «PRO B650M-B»."""
    m = (model or "").strip()
    if is_placeholder(m):
        return ""
    m = re.sub(r"\s*\((ms|ms-)?-?[0-9a-f]{4,5}\)\s*$", "", m, flags=re.I)  # (MS-7E28)
    m = re.sub(r"\s*\(ms-\w+\)\s*$", "", m, flags=re.I)
    b = brand(maker)
    if b and m.lower().startswith(b.lower() + " "):
        m = m[len(b) + 1:]
    return m.strip()


def is_board_code(model: str) -> bool:
    """«MS-7C91», «MS-7E28» — внутренние коды плат MSI в поле «модель» у собранных ПК."""
    return bool(re.fullmatch(r"ms-?[0-9a-f]{4,5}", (model or "").strip(), re.I))


def pretty_cpu(cpu: str) -> str:
    c = re.sub(r"\(r\)|\(tm\)|®|™", "", cpu or "", flags=re.I)
    c = re.sub(r"\s+@\s*[\d.]+\s*[gm]hz", "", c, flags=re.I)
    c = re.sub(r"\bcpu\b|\bprocessor\b", "", c, flags=re.I)
    c = re.sub(r"\b\d+(st|nd|rd|th) gen\s+", "", c, flags=re.I)
    cores = re.search(r"\b(\d+)-core\b", c, re.I)
    c = re.sub(r"\b\w+-core\b", "", c, flags=re.I)
    c = " ".join(c.split())
    if cores:
        n = int(cores.group(1))
        word = "ядро" if n % 10 == 1 and n % 100 != 11 else (
            "ядра" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "ядер")
        c += f" ({n} {word})"
    return c


# Номер сборки → понятная версия Windows.
WINDOWS_RELEASES = {
    26200: "25H2", 26100: "24H2", 22631: "23H2", 22621: "22H2", 22000: "21H2",
    19045: "22H2", 19044: "21H2", 19043: "21H1", 19042: "20H2", 19041: "2004",
    18363: "1909", 18362: "1903", 17763: "1809", 17134: "1803",
}


def pretty_os(caption: str, build: int, arch: str) -> str:
    name = re.sub(r"^(microsoft|майкрософт)\s+", "", caption or "", flags=re.I).strip()
    if not name:
        return ""
    rel = WINDOWS_RELEASES.get(build, "")
    bits = {"x64": "64-бит", "x86": "32-бит", "arm64": "ARM"}.get(arch, arch)
    return " · ".join(x for x in (f"{name} {rel}".strip(), bits) if x)


def pretty_ram(gb: float) -> str:
    if not gb:
        return ""
    return f"{round(gb):g} ГБ" if abs(gb - round(gb)) < 0.3 or gb >= 8 else f"{gb:g} ГБ"
