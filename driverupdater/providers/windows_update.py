"""Источник №1: Windows Update (официальный API Windows Update Agent).

Через Windows Update производители (NVIDIA, AMD, Intel, Realtek и др.) публикуют
драйверы, прошедшие сертификацию Microsoft (WHQL). Windows сама подбирает
драйверы, подходящие именно к этому компьютеру.
"""

from __future__ import annotations

from .. import powershell
from ..models import DriverOffer
from ..versions import normalize_date

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

INSTALL_SCRIPT = r"""
$ids = @(__IDS__)
$session  = New-Object -ComObject Microsoft.Update.Session
$session.ClientApplicationID = 'DriverUpdater'
$searcher = $session.CreateUpdateSearcher()
$res = $searcher.Search("IsInstalled=0 and Type='Driver'")
$coll = New-Object -ComObject Microsoft.Update.UpdateColl
foreach ($u in $res.Updates) {
  if ($ids -contains $u.Identity.UpdateID) {
    if (-not $u.EulaAccepted) { $u.AcceptEula() }
    [void]$coll.Add($u)
  }
}
$out = @()
if ($coll.Count -gt 0) {
  $dl = $session.CreateUpdateDownloader(); $dl.Updates = $coll; [void]$dl.Download()
  $inst = $session.CreateUpdateInstaller(); $inst.Updates = $coll
  $r = $inst.Install()
  for ($i = 0; $i -lt $coll.Count; $i++) {
    $ur = $r.GetUpdateResult($i)
    $out += [ordered]@{
      update_id       = [string]$coll.Item($i).Identity.UpdateID
      title           = [string]$coll.Item($i).Title
      result_code     = [int]$ur.ResultCode      # 2 = успешно, 3 = с ошибками, 4 = ошибка
      hresult         = [int64]$ur.HResult
      reboot_required = [bool]$ur.RebootRequired
    }
  }
}
ConvertTo-Json -InputObject @($out) -Depth 3 -Compress
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
    """WUA не отдаёт версию драйвера отдельно, но почти всегда пишет её в конце заголовка:
    'NVIDIA - Display - 31.0.15.5222'."""
    tail = title.rsplit(" - ", 1)[-1].strip()
    return tail if tail and tail[0].isdigit() and "." in tail else ""


def search() -> list[DriverOffer]:
    return parse_search(powershell.run_json(SEARCH_SCRIPT, timeout=900))


def install(update_ids: list[str]) -> list[dict]:
    ids = ", ".join(powershell.ps_quote(i) for i in update_ids)
    return powershell.run_json(INSTALL_SCRIPT.replace("__IDS__", ids), timeout=3600) or []


def cleanup_cache(since_iso: str) -> dict:
    script = CLEANUP_SCRIPT.replace("__SINCE__", powershell.ps_quote(since_iso))
    return powershell.run_json(script, timeout=300) or {"removed": 0, "bytes": 0}
