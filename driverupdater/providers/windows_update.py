"""Источник №1: Windows Update (официальный API Windows Update Agent).

Через Windows Update производители (NVIDIA, AMD, Intel, Realtek и др.) публикуют
драйверы, прошедшие сертификацию Microsoft (WHQL). Windows сама подбирает
драйверы, подходящие именно к этому компьютеру.
"""

from __future__ import annotations

import re

from .. import powershell
from ..models import DriverOffer
from ..versions import normalize_date

VERSION_RE = re.compile(r"(?<![\d.])(\d+\.\d+(?:\.\d+){1,2})(?![\d.])")

SEARCH_SCRIPT = r"""
$session  = New-Object -ComObject Microsoft.Update.Session
$session.ClientApplicationID = 'DriverUpdater'
$searcher = $session.CreateUpdateSearcher()
$searcher.Online = $true
$res = $searcher.Search("IsInstalled=0 and Type='Driver' and IsHidden=0")
$out = foreach ($u in $res.Updates) {
  [ordered]@{
    update_id       = [string]$u.Identity.UpdateID
    title           = [string]$u.Title
    hardware_id     = [string]$u.DriverHardwareID
    provider        = [string]$u.DriverProvider
    manufacturer    = [string]$u.DriverManufacturer
    driver_class    = [string]$u.DriverClass
    date            = if ($u.DriverVerDate) { ([datetime]$u.DriverVerDate).ToString('yyyy-MM-dd') } else { '' }
    size_bytes      = [int64]$u.MaxDownloadSize
    reboot_behavior = [int]$u.InstallationBehavior.RebootBehavior
    browse_only     = [bool]$u.BrowseOnly
  }
}
ConvertTo-Json -InputObject @($out) -Depth 3 -Compress
"""

# Ставим по одному обновлению, чтобы показывать этап каждого: скачивание → установка → итог.
# Строки «@@{json}» читает powershell.run_stream().
INSTALL_SCRIPT = r"""
function Say($o) { [Console]::Out.WriteLine('@@' + (ConvertTo-Json -InputObject $o -Compress)); [Console]::Out.Flush() }
$ids = @(__IDS__)
$session  = New-Object -ComObject Microsoft.Update.Session
$session.ClientApplicationID = 'DriverUpdater'
$searcher = $session.CreateUpdateSearcher()
$res = $searcher.Search("IsInstalled=0 and Type='Driver'")
foreach ($u in $res.Updates) {
  $id = [string]$u.Identity.UpdateID
  if (-not ($ids -contains $id)) { continue }
  if (-not $u.EulaAccepted) { $u.AcceptEula() }
  $one = New-Object -ComObject Microsoft.Update.UpdateColl
  [void]$one.Add($u)
  Say ([ordered]@{ update_id = $id; stage = 'download' })
  $dl = $session.CreateUpdateDownloader(); $dl.Updates = $one; [void]$dl.Download()
  Say ([ordered]@{ update_id = $id; stage = 'install' })
  $inst = $session.CreateUpdateInstaller(); $inst.Updates = $one
  $r = $inst.Install()
  $ur = $r.GetUpdateResult(0)
  Say ([ordered]@{
    update_id = $id; stage = 'result'; title = [string]$u.Title
    result_code = [int]$ur.ResultCode; hresult = [int64]$ur.HResult; reboot_required = [bool]$ur.RebootRequired
  })
}
"""

# Удаляет из кэша Windows Update только то, что было скачано во время нашей сессии.
CLEANUP_SCRIPT = r"""
$since = [datetime]::Parse(__SINCE__, [Globalization.CultureInfo]::InvariantCulture)
$dir = Join-Path $env:SystemRoot 'SoftwareDistribution\Download'
$removed = 0; $bytes = 0
Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.CreationTime -ge $since } | ForEach-Object {
    $size = (Get-ChildItem -LiteralPath $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue |
             Measure-Object Length -Sum).Sum
    try { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop; $removed++; $bytes += $size } catch {}
  }
ConvertTo-Json -InputObject ([ordered]@{ removed = $removed; bytes = [int64]$bytes }) -Compress
"""


def parse_search(items: list[dict] | None) -> list[DriverOffer]:
    offers = []
    for it in items or []:
        title = it.get("title", "")
        cls = it.get("driver_class", "")
        offers.append(DriverOffer(
            source="windows_update",
            title=title,
            version=_version_from_title(title),
            date=normalize_date(it.get("date", "")),
            hardware_id=it.get("hardware_id", ""),
            provider=it.get("provider") or it.get("manufacturer", ""),
            driver_class=cls,
            update_id=it.get("update_id", ""),
            size_bytes=int(it.get("size_bytes") or 0),
            is_firmware=cls.lower() == "firmware" or "firmware" in title.lower(),
            reboot_required=int(it.get("reboot_behavior") or 0) > 0,
        ))
    return offers


def _version_from_title(title: str) -> str:
    """WUA не отдаёт версию драйвера отдельно, но пишет её в заголовке. Встречаются оба формата:
    'NVIDIA - Display - 31.0.15.5222' и 'Intel net Driver Update (24.20.0.4)'."""
    found = VERSION_RE.findall(title)
    return found[-1] if found else ""


def search() -> list[DriverOffer]:
    return parse_search(powershell.run_json(SEARCH_SCRIPT, timeout=900))


def install(update_ids: list[str], on_event=lambda ev: None) -> list[dict]:
    """Ставит обновления по одному; on_event получает {update_id, stage: download|install|result, …}."""
    ids = ", ".join(powershell.ps_quote(i) for i in update_ids)
    results: list[dict] = []

    def collect(ev: dict) -> None:
        if ev.get("stage") == "result":
            results.append(ev)
        on_event(ev)

    powershell.run_stream(INSTALL_SCRIPT.replace("__IDS__", ids), collect, timeout=3 * 3600)
    return results


def cleanup_cache(since_iso: str) -> dict:
    script = CLEANUP_SCRIPT.replace("__SINCE__", powershell.ps_quote(since_iso))
    return powershell.run_json(script, timeout=300) or {"removed": 0, "bytes": 0}
