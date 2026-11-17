"""Скачивание, проверка подписи, установка драйверов и удаление установочных файлов."""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import powershell
from .models import Assessment
from .providers import catalog, windows_update

# Скачиваем только с официальных серверов Microsoft.
ALLOWED_HOSTS = (
    "download.windowsupdate.com",
    ".download.windowsupdate.com",
    "download.microsoft.com",
    ".delivery.mp.microsoft.com",
)
TRUSTED_SIGNERS = ("Microsoft Corporation", "Microsoft Windows")

# Коды возврата pnputil.
PNP_OK, PNP_REBOOT, PNP_NOT_NEWER = 0, 3010, 259

Log = Callable[[str], None]


@dataclass
class InstallResult:
    name: str
    ok: bool
    message: str
    reboot: bool = False
    key: str = ""  # источник:идентификатор пакета — по нему интерфейс находит строку


def offer_key(a: Assessment) -> str:
    return f"{a.offer.source}:{a.offer.update_id}" if a.offer else ""


# progress(key, state, message): state — "running" | "ok" | "error" | "cleanup"
Progress = Callable[[str, str, str], None]


def _no_progress(key: str, state: str, message: str) -> None:
    pass


@dataclass
class Report:
    results: list[InstallResult] = field(default_factory=list)
    cleaned_bytes: int = 0
    cleaned_paths: list[str] = field(default_factory=list)

    @property
    def reboot_required(self) -> bool:
        return any(r.reboot for r in self.results)


def _console(b: bytes) -> str:
    """Вывод консольных утилит Windows идёт в OEM-кодировке (cp866 для русской Windows)."""
    try:
        enc = f"cp{ctypes.windll.kernel32.GetOEMCP()}"  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        enc = "utf-8"
    return b.decode(enc, errors="replace")


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def host_allowed(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return any(host == h or (h.startswith(".") and host.endswith(h)) for h in ALLOWED_HOSTS)


def create_restore_point() -> None:
    powershell.run(
        "Enable-ComputerRestore -Drive \"$env:SystemDrive\\\" -ErrorAction SilentlyContinue\n"
        "Checkpoint-Computer -Description 'DriverUpdater: перед установкой драйверов' "
        "-RestorePointType MODIFY_SETTINGS", timeout=600)


def backup_drivers(target: str) -> None:
    Path(target).mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["pnputil", "/export-driver", "*", target], capture_output=True, **powershell.NO_WINDOW)
    if proc.returncode not in (0, PNP_REBOOT):
        raise RuntimeError(_console(proc.stdout)[-1000:])


def verify_signature(path: Path) -> str:
    """Проверяет цифровую подпись Authenticode. Возвращает имя подписавшего или бросает ошибку."""
    info = powershell.run_json(
        f"$s = Get-AuthenticodeSignature -LiteralPath {powershell.ps_quote(str(path))}\n"
        "ConvertTo-Json -Compress -InputObject ([ordered]@{status=[string]$s.Status; "
        "signer=[string]$s.SignerCertificate.Subject})")
    if info.get("status") != "Valid":
        raise RuntimeError(f"подпись файла недействительна ({info.get('status')})")
    signer = info.get("signer", "")
    if not any(t in signer for t in TRUSTED_SIGNERS):
        raise RuntimeError(f"файл подписан не Microsoft: {signer}")
    return signer


def download(url: str, dest_dir: Path) -> Path:
    if not host_allowed(url):
        raise RuntimeError(f"адрес не из официального источника: {url}")
    https = url.replace("http://", "https://", 1)
    name = Path(urllib.parse.urlparse(url).path).name or "driver.cab"
    dest = dest_dir / name
    last_err: Exception | None = None
    # HTTPS в приоритете; HTTP — запасной вариант (так работает и сам Windows Update),
    # целостность всё равно гарантирует проверка подписи после скачивания.
    for candidate in dict.fromkeys([https, url]):
        try:
            req = urllib.request.Request(candidate, headers={"User-Agent": catalog.UA})
            with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
                shutil.copyfileobj(resp, fh, 1 << 20)
            return dest
        except OSError as e:
            last_err = e
    raise RuntimeError(f"не удалось скачать {name}: {last_err}")


def expand_cab(cab: Path, dest: Path, depth: int = 0) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["expand.exe", str(cab), "-F:*", str(dest)], capture_output=True, **powershell.NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(f"не удалось распаковать {cab.name}")
    if depth < 2:  # в каталоге встречаются вложенные .cab
        for inner in list(dest.rglob("*.cab")):
            expand_cab(inner, inner.with_suffix(""), depth + 1)
            inner.unlink(missing_ok=True)


def pnputil_install(folder: Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["pnputil", "/add-driver", str(folder / "*.inf"), "/subdirs", "/install"],
        capture_output=True, **powershell.NO_WINDOW)
    return proc.returncode, _console(proc.stdout)


def install_from_catalog(a: Assessment, workspace: Path, log: Log) -> InstallResult:
    off = a.offer
    assert off is not None
    name = a.device.name
    urls = catalog.download_urls(off.update_id)
    if not urls:
        return InstallResult(name, False, "каталог не выдал ссылку на скачивание")
    pkg_dir = workspace / off.update_id
    pkg_dir.mkdir(parents=True, exist_ok=True)
    files = pkg_dir / "files"
    for url in urls:
        log(f"    скачивание: {url}")
        f = download(url, pkg_dir)
        try:
            signer = verify_signature(f)
            log(f"    подпись архива в порядке: {signer.split(',')[0]}")
        except RuntimeError as e:
            if "NotSigned" not in str(e):
                raise
            signer = ""  # старые архивы не подписаны — проверим .cat внутри
        if f.suffix.lower() == ".cab":
            expand_cab(f, files)
        f.unlink(missing_ok=True)
        if not signer:
            cats = list(files.rglob("*.cat"))
            if not cats:
                raise RuntimeError("архив не подписан и не содержит подписанного каталога .cat")
            for c in cats:
                verify_signature(c)
            log(f"    подпись драйвера (WHQL) в порядке: {len(cats)} файл(ов) .cat")
    if not list(files.rglob("*.inf")):
        return InstallResult(name, False, "в пакете нет .inf — это не драйвер, пропущено")
    code, out = pnputil_install(pkg_dir / "files")
    if code in (PNP_OK, PNP_REBOOT):
        return InstallResult(name, True, f"установлен {off.version or off.title}", code == PNP_REBOOT)
    if code == PNP_NOT_NEWER:
        return InstallResult(name, True, "Windows оставила текущий драйвер (он не хуже)")
    return InstallResult(name, False, f"pnputil вернул {code}: {out.strip()[-300:]}")


def remove_workspace(workspace: Path, report: Report) -> None:
    if not workspace.exists():
        return
    size = sum(f.stat().st_size for f in workspace.rglob("*") if f.is_file())
    shutil.rmtree(workspace, ignore_errors=True)
    if not workspace.exists():
        report.cleaned_bytes += size
        report.cleaned_paths.append(str(workspace))


def install(plan: list[Assessment], log: Log = print, progress: Progress = _no_progress) -> Report:
    """Устанавливает драйверы из плана. Временные файлы удаляются в любом случае,
    даже если установка прервалась с ошибкой."""
    report = Report()

    def done(a: Assessment | None, res: InstallResult) -> None:
        res.key = offer_key(a) if a else res.key
        report.results.append(res)
        progress(res.key, "ok" if res.ok else "error", res.message)

    started = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    workspace = Path(tempfile.mkdtemp(prefix="DriverUpdater_"))
    try:
        wu = [a for a in plan if a.offer and a.offer.source == "windows_update"]
        cat = [a for a in plan if a.offer and a.offer.source == "catalog"]

        if wu:
            log(f"\n[Windows Update] установка {len(wu)} драйвер(ов)…")
            by_id = {a.offer.update_id: a for a in wu}  # type: ignore[union-attr]
            for a in wu:  # Windows Update ставит пакеты одной пачкой
                progress(offer_key(a), "running", "скачивание и установка через Windows Update")
            try:
                results = windows_update.install(list(by_id))
                for r in results:
                    a = by_id.pop(r["update_id"], None)
                    ok = r["result_code"] in (2, 3)
                    msg = "установлен" if ok else f"ошибка 0x{r['hresult'] & 0xFFFFFFFF:08X}"
                    done(a, InstallResult(a.device.name if a else r["title"], ok, msg,
                                          r["reboot_required"], key=f"windows_update:{r['update_id']}"))
                    log(f"  {'✔' if ok else '✘'} {r['title']}: {msg}")
                for a in by_id.values():  # Windows Update уже не предлагает этот пакет
                    done(a, InstallResult(a.device.name, False,
                                          "пакет больше не предлагается Windows Update — повторите поиск"))
            except powershell.PowerShellError as e:
                for a in by_id.values():
                    done(a, InstallResult(a.device.name, False, str(e)[:300]))
                log(f"  ✘ Windows Update: {e}")

        for a in cat:
            log(f"\n[Update Catalog] {a.device.name}")
            progress(offer_key(a), "running", "скачивание из каталога Microsoft")
            try:
                res = install_from_catalog(a, workspace, log)
            except (RuntimeError, OSError, powershell.PowerShellError) as e:
                res = InstallResult(a.device.name, False, str(e)[:300])
            done(a, res)
            log(f"  {'✔' if res.ok else '✘'} {res.message}")
    finally:
        log("\nУдаление установочных файлов…")
        progress("", "cleanup", "удаление установочных файлов")
        remove_workspace(workspace, report)
        if any(a.offer and a.offer.source == "windows_update" for a in plan):
            try:
                info = windows_update.cleanup_cache(started)
                report.cleaned_bytes += int(info.get("bytes") or 0)
                if info.get("removed"):
                    report.cleaned_paths.append(
                        f"%SystemRoot%\\SoftwareDistribution\\Download ({info['removed']} пакет(ов))")
            except powershell.PowerShellError as e:
                log(f"  не удалось очистить кэш Windows Update: {e}")
    return report
