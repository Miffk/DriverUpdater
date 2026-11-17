"""Определение конфигурации ПК и установленных драйверов (через WMI/CIM)."""

from __future__ import annotations

import json
from pathlib import Path

from . import powershell
from .models import Device, SystemInfo
from .versions import normalize_date

COLLECT_SCRIPT = r"""
function D($v) { if ($v) { $v.ToString('yyyy-MM-dd') } else { '' } }

$cs   = Get-CimInstance Win32_ComputerSystem
$os   = Get-CimInstance Win32_OperatingSystem
$bb   = Get-CimInstance Win32_BaseBoard
$bios = Get-CimInstance Win32_BIOS
$cpu  = Get-CimInstance Win32_Processor | Select-Object -First 1
$gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })
$ramInstalled = (Get-CimInstance Win32_PhysicalMemory -ErrorAction SilentlyContinue | Measure-Object Capacity -Sum).Sum

$arch = switch ($env:PROCESSOR_ARCHITECTURE) {
  'AMD64' { 'x64' } 'ARM64' { 'arm64' } 'x86' { if ($env:PROCESSOR_ARCHITEW6432) { 'x64' } else { 'x86' } }
  default { $env:PROCESSOR_ARCHITECTURE }
}

$drivers = @{}
Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DeviceID } | ForEach-Object {
  $drivers[$_.DeviceID.ToUpper()] = $_
}

$devices = foreach ($e in Get-CimInstance Win32_PnPEntity) {
  if (-not $e.DeviceID) { continue }
  $d = $drivers[$e.DeviceID.ToUpper()]
  $hw = @($e.HardwareID | Where-Object { $_ })
  if ($hw.Count -eq 0 -and $d -and $d.HardWareID) { $hw = @($d.HardWareID) }
  [ordered]@{
    instance_id     = $e.DeviceID
    name            = if ($e.Name) { $e.Name } elseif ($d) { $d.DeviceName } else { '' }
    device_class    = if ($e.PNPClass) { $e.PNPClass } elseif ($d) { $d.DeviceClass } else { '' }
    manufacturer    = [string]$e.Manufacturer
    hardware_ids    = $hw
    compatible_ids  = @($e.CompatibleID | Where-Object { $_ })
    problem_code    = [int]$e.ConfigManagerErrorCode
    status          = [string]$e.Status
    driver_version  = if ($d) { [string]$d.DriverVersion } else { '' }
    driver_date     = if ($d) { D $d.DriverDate } else { '' }
    driver_provider = if ($d) { [string]$d.DriverProviderName } else { '' }
    inf_name        = if ($d) { [string]$d.InfName } else { '' }
    is_signed       = if ($d) { [bool]$d.IsSigned } else { $null }
  }
}

$result = [ordered]@{
  system = [ordered]@{
    manufacturer = [string]$cs.Manufacturer
    model        = [string]$cs.Model
    board        = ("{0} {1}" -f $bb.Manufacturer, $bb.Product).Trim()
    board_maker  = [string]$bb.Manufacturer
    board_product = [string]$bb.Product
    bios         = ("{0} {1} ({2})" -f $bios.Manufacturer, $bios.SMBIOSBIOSVersion, (D $bios.ReleaseDate)).Trim()
    cpu          = ([string]$cpu.Name).Trim()
    ram_gb       = if ($ramInstalled) { [math]::Round($ramInstalled / 1GB, 1) } else { [math]::Round($cs.TotalPhysicalMemory / 1GB, 1) }
    pc_type      = [int]$cs.PCSystemType   # 1 — настольный, 2 — ноутбук/планшет
    gpus         = $gpus
    os_name      = [string]$os.Caption
    os_version   = [string]$os.Version
    os_build     = [int]$os.BuildNumber
    arch         = $arch
  }
  devices = @($devices)
}
ConvertTo-Json -InputObject $result -Depth 5 -Compress
"""


def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v else []
    return [str(x) for x in v if x]


def parse_snapshot(data: dict) -> tuple[SystemInfo, list[Device]]:
    s = data.get("system") or {}
    system = SystemInfo(
        manufacturer=s.get("manufacturer", ""), model=s.get("model", ""),
        board=s.get("board", ""), bios=s.get("bios", ""), cpu=s.get("cpu", ""),
        ram_gb=float(s.get("ram_gb") or 0), gpus=_as_list(s.get("gpus")),
        os_name=s.get("os_name", ""), os_version=s.get("os_version", ""),
        os_build=int(s.get("os_build") or 0), arch=s.get("arch", "x64"),
        pc_type=int(s.get("pc_type") or 0),
        board_maker=s.get("board_maker", ""), board_product=s.get("board_product", ""),
    )
    devices = []
    for d in data.get("devices") or []:
        devices.append(Device(
            instance_id=d.get("instance_id", ""),
            name=(d.get("name") or "").strip(),
            device_class=d.get("device_class") or "",
            manufacturer=d.get("manufacturer") or "",
            hardware_ids=_as_list(d.get("hardware_ids")),
            compatible_ids=_as_list(d.get("compatible_ids")),
            problem_code=int(d.get("problem_code") or 0),
            status=d.get("status") or "",
            driver_version=d.get("driver_version") or "",
            driver_date=normalize_date(d.get("driver_date") or ""),
            driver_provider=d.get("driver_provider") or "",
            inf_name=d.get("inf_name") or "",
            is_signed=d.get("is_signed"),
        ))
    return system, devices


def collect_raw() -> dict:
    if not powershell.is_windows():
        raise powershell.PowerShellError(
            "Сканирование оборудования доступно только в Windows. "
            "Для проверки на другой ОС используйте --from-file со снимком.")
    return powershell.run_json(COLLECT_SCRIPT, timeout=300)


def scan(from_file: str | None = None, save_to: str | None = None
         ) -> tuple[SystemInfo, list[Device]]:
    if from_file:
        raw = json.loads(Path(from_file).read_text(encoding="utf-8-sig"))
    else:
        raw = collect_raw()
    if save_to:
        Path(save_to).write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return parse_snapshot(raw)
