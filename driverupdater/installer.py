"""Скачивание, проверка подписи, установка драйверов и удаление установочных файлов."""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import tempfile
import time
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


# progress(key, state, message, stage=..., percent=..., done=..., total=...):
#   state — "waiting" | "running" | "ok" | "error" | "cleanup";
#   stage — "download" | "verify" | "extract" | "install" | "check" (что именно сейчас происходит);
#   percent — 0..100, если известен (скачивание); done/total — байты.
Progress = Callable[..., None]
# step(stage, message, percent=None, done=None, total=None) — то же для одного драйвера.
Step = Callable[..., None]


def _no_progress(key: str, state: str, message: str, **kw) -> None:
    pass


def _no_step(stage: str, message: str, **kw) -> None:
    pass


def mb(n: int) -> str:
    return f"{n / (1 << 20):.0f} МБ" if n >= (1 << 20) else f"{max(n, 0) / 1024:.0f} КБ"


def download_step(step: Step, what: str = "Скачивание"):
    """Колбэк для download(): превращает байты в «Скачивание · 45% · 390 из 870 МБ»."""
    def on_bytes(done: int, total: int) -> None:
        if total:
            pct = 100 * done / total
            step("download", f"{what} · {pct:.0f}% · {mb(done)} из {mb(total)}", percent=pct, done=done, total=total)
        else:
            step("download", f"{what} · {mb(done)}", done=done)
    return on_bytes


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


def verify_signature(path: Path, signers: tuple[str, ...] = TRUSTED_SIGNERS) -> str:
    """Проверяет цифровую подпись Authenticode. Возвращает имя подписавшего или бросает ошибку."""
    info = powershell.run_json(
        f"$s = Get-AuthenticodeSignature -LiteralPath {powershell.ps_quote(str(path))}\n"
        "ConvertTo-Json -Compress -InputObject ([ordered]@{status=[string]$s.Status; "
        "signer=[string]$s.SignerCertificate.Subject})")
    if info.get("status") != "Valid":
        raise RuntimeError(f"подпись файла недействительна ({info.get('status')})")
    signer = info.get("signer", "")
    if not any(t in signer for t in signers):
        raise RuntimeError(f"файл подписан не тем, кем должен: {signer}")
    return signer


def download(url: str, dest_dir: Path, hosts: tuple[str, ...] | None = None,
             on_bytes: Callable[[int, int], None] | None = None) -> Path:
    allowed = host_allowed(url) if hosts is None else (urllib.parse.urlparse(url).hostname or "") in hosts
    if not allowed:
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
            with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as fh:
                total = int(resp.headers.get("Content-Length") or 0)
                done, last = 0, 0.0
                while chunk := resp.read(1 << 18):
                    fh.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if on_bytes and (now - last > 0.25 or done == total):
                        on_bytes(done, total)
                        last = now
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


def install_from_catalog(a: Assessment, workspace: Path, log: Log, step: Step = _no_step) -> InstallResult:
    off = a.offer
    assert off is not None
    name = a.device.name
    step("download", "Получаю ссылку из каталога Microsoft…", percent=0)
    urls = catalog.download_urls(off.update_id)
    if not urls:
        return InstallResult(name, False, "каталог не выдал ссылку на скачивание")
    pkg_dir = workspace / off.update_id
    pkg_dir.mkdir(parents=True, exist_ok=True)
    files = pkg_dir / "files"
    for url in urls:
        log(f"    скачивание: {url}")
        f = download(url, pkg_dir, on_bytes=download_step(step))
        step("verify", "Проверка цифровой подписи")
        try:
            signer = verify_signature(f)
            log(f"    подпись архива в порядке: {signer.split(',')[0]}")
        except RuntimeError as e:
            if "NotSigned" not in str(e):
                raise
            signer = ""  # старые архивы не подписаны — проверим .cat внутри
        if f.suffix.lower() == ".cab":
            step("extract", "Распаковка")
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
    step("install", "Установка драйвера")
    code, out = pnputil_install(pkg_dir / "files")
    if code in (PNP_OK, PNP_REBOOT):
        return InstallResult(name, True, f"установлен {off.version or off.title}", code == PNP_REBOOT)
    if code == PNP_NOT_NEWER:
        return InstallResult(name, True, "Windows оставила текущий драйвер (он не хуже)")
    return InstallResult(name, False, f"pnputil вернул {code}: {out.strip()[-300:]}")


def installed_version(instance_id: str) -> str:
    out = powershell.run_json(
        "$d = Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DeviceID -eq "
        f"{powershell.ps_quote(instance_id)} }} | Select-Object -First 1\n"
        "ConvertTo-Json -Compress -InputObject ([ordered]@{v=[string]$d.DriverVersion})")
    return (out or {}).get("v", "")


def install_nvidia(a: Assessment, workspace: Path, log: Log, step: Step = _no_step) -> InstallResult:
    """Драйвер с официального сайта NVIDIA: скачать → проверить подпись NVIDIA →
    тихая установка → сверить установленную версию → удалить установщик."""
    from .providers import nvidia
    off = a.offer
    assert off is not None and off.download_url
    pkg = workspace / ("nvidia_" + off.version)
    pkg.mkdir(parents=True, exist_ok=True)
    log(f"    скачивание с сайта NVIDIA: {off.download_url}")
    exe = download(off.download_url, pkg, hosts=nvidia.DOWNLOAD_HOSTS,
                   on_bytes=download_step(step, "Скачивание с сайта NVIDIA"))
    step("verify", "Проверка цифровой подписи NVIDIA")
    signer = verify_signature(exe, (nvidia.SIGNER,))
    log(f"    подпись в порядке: {signer.split(',')[0]}")
    log("    установка (несколько минут, экран может мигать)…")
    step("install", "Установка — обычно 2–5 минут, экран может мигать")
    proc = subprocess.run([str(exe), "-s", "-noreboot", "-noeula"], capture_output=True,
                          timeout=3600, **powershell.NO_WINDOW)
    exe.unlink(missing_ok=True)
    step("check", "Проверяю, что новая версия встала")
    now = nvidia.windows_to_nvidia(installed_version(a.device.instance_id))
    if now == off.version:
        return InstallResult(a.device.name, True, f"установлен драйвер NVIDIA {off.version}", reboot=True)
    return InstallResult(a.device.name, False,
                         f"установщик NVIDIA завершился с кодом {proc.returncode}, "
                         f"сейчас стоит версия {now or 'неизвестно'}")


def restart_device(instance_id: str) -> tuple[bool, str]:
    """Перезапуск устройства — как «отключить и включить» в Диспетчере устройств.
    Если не помогло — удаляем устройство из системы и просим Windows найти его заново."""
    q = powershell.ps_quote(instance_id)
    script = (
        f"$id = {q}\n"
        "$null = & pnputil /restart-device \"$id\" 2>&1\n"
        "Start-Sleep -Seconds 3\n"
        "$d = Get-PnpDevice -InstanceId $id -ErrorAction SilentlyContinue\n"
        "if (-not $d -or $d.Status -ne 'OK') {\n"
        "  $null = & pnputil /remove-device \"$id\" 2>&1\n"
        "  $null = & pnputil /scan-devices 2>&1\n"
        "  Start-Sleep -Seconds 5\n"
        "  $d = Get-PnpDevice -InstanceId $id -ErrorAction SilentlyContinue\n"
        "}\n"
        "ConvertTo-Json -Compress -InputObject ([ordered]@{status=[string]$d.Status; present=[bool]$d})")
    try:
        res = powershell.run_json(script, timeout=180) or {}
    except powershell.PowerShellError as e:
        return False, f"не удалось перезапустить устройство: {e}"
    if res.get("status") == "OK":
        return True, "Устройство перезапущено и теперь работает."
    if not res.get("present"):
        return False, ("Устройство пропало из системы. Переподключите его или перезагрузите компьютер — "
                       "Windows найдёт его заново.")
    return False, ("Перезапуск не помог. Попробуйте вставить устройство в другой USB-разъём или "
                   "перезагрузить компьютер.")


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
        for a in plan:
            progress(offer_key(a), "waiting", "в очереди")
        wu = [a for a in plan if a.offer and a.offer.source == "windows_update"]
        cat = [a for a in plan if a.offer and a.offer.source in ("catalog", "nvidia")]

        if wu:
            log(f"\n[Windows Update] установка {len(wu)} драйвер(ов)…")
            by_id = {a.offer.update_id: a for a in wu}  # type: ignore[union-attr]
            def on_event(ev: dict) -> None:
                a = by_id.get(ev.get("update_id", ""))
                if not a:
                    return
                stage = ev.get("stage")
                if stage == "download":
                    progress(offer_key(a), "running", "Скачивание через Windows Update", stage="download")
                elif stage == "install":
                    progress(offer_key(a), "running", "Установка", stage="install", percent=None)
                elif stage == "result":
                    by_id.pop(ev["update_id"], None)
                    ok = ev["result_code"] in (2, 3)
                    msg = "установлен" if ok else f"ошибка 0x{ev['hresult'] & 0xFFFFFFFF:08X}"
                    done(a, InstallResult(a.device.name, ok, msg, ev["reboot_required"]))
                    log(f"  {'✔' if ok else '✘'} {ev.get('title', a.device.name)}: {msg}")

            try:
                windows_update.install(list(by_id), on_event)
                for a in list(by_id.values()):  # Windows Update уже не предлагает этот пакет
                    done(a, InstallResult(a.device.name, False,
                                          "пакет больше не предлагается Windows Update — повторите поиск"))
            except powershell.PowerShellError as e:
                for a in list(by_id.values()):
                    done(a, InstallResult(a.device.name, False, str(e)[:300]))
                log(f"  ✘ Windows Update: {e}")

        for a in cat:
            nv = a.offer.source == "nvidia"  # type: ignore[union-attr]
            log(f"\n[{'NVIDIA' if nv else 'Update Catalog'}] {a.device.name}")
            key = offer_key(a)

            def step(stage: str, message: str, _key: str = key, **kw) -> None:
                progress(_key, "running", message, stage=stage, **kw)

            try:
                res = (install_nvidia(a, workspace, log, step) if nv
                       else install_from_catalog(a, workspace, log, step))
            except (RuntimeError, OSError, powershell.PowerShellError) as e:
                res = InstallResult(a.device.name, False, str(e)[:300])
            done(a, res)
            log(f"  {'✔' if res.ok else '✘'} {res.message}")
    finally:
        log("\nУдаление установочных файлов…")
        progress("", "cleanup", "Удаление установочных файлов", stage="cleanup")
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
