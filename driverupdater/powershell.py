"""Запуск PowerShell-скриптов и получение JSON-ответа."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys

PREAMBLE = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
"""


class PowerShellError(RuntimeError):
    pass


def is_windows() -> bool:
    return sys.platform == "win32"


def _exe() -> str:
    for name in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
        path = shutil.which(name)
        if path:
            return path
    raise PowerShellError("PowerShell не найден. Программа работает только в Windows 10/11.")


def run(script: str, timeout: int = 600) -> str:
    """Выполняет скрипт и возвращает stdout. Скрипт передаётся через -EncodedCommand,
    поэтому кавычки и спецсимволы не ломают командную строку."""
    encoded = base64.b64encode((PREAMBLE + script).encode("utf-16-le")).decode("ascii")
    proc = subprocess.run(
        [_exe(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", encoded],
        capture_output=True, timeout=timeout,
    )
    out = proc.stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace") or out
        raise PowerShellError(err.strip()[-2000:])
    return out


def run_json(script: str, timeout: int = 600):
    out = run(script, timeout=timeout).strip()
    if not out:
        return None
    # PowerShell иногда печатает предупреждения до JSON — берём с первой скобки.
    start = min((i for i in (out.find("{"), out.find("[")) if i >= 0), default=0)
    return json.loads(out[start:])


def ps_quote(s: str) -> str:
    """Безопасная строка-литерал для PowerShell."""
    return "'" + s.replace("'", "''") + "'"
