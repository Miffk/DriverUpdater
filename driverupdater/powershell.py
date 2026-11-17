"""Запуск PowerShell-скриптов и получение JSON-ответа."""

from __future__ import annotations

import base64
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Callable

PREAMBLE = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
"""


# В графической версии не даём дочерним процессам открывать чёрные окна консоли.
NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}


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
        capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, **NO_WINDOW,
    )
    out = proc.stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        err = _clean_error(proc.stderr.decode("utf-8", errors="replace")) or out
        raise PowerShellError(err.strip()[-2000:])
    return out


def _clean_error(text: str) -> str:
    """При -EncodedCommand ошибки приходят в XML-обёртке CLIXML — достаём из неё текст."""
    if "#< CLIXML" not in text:
        return text
    parts = re.findall(r'<S S="Error">(.*?)</S>', text, re.S)
    msg = "".join(parts).replace("_x000D_", "").replace("_x000A_", "\n")
    return html.unescape(msg)


def run_stream(script: str, on_event: Callable[[dict], None], timeout: int = 3600) -> str:
    """Как run(), но строки вида «@@{json}» передаются в on_event сразу, пока скрипт работает.
    Так длинные операции (Windows Update) сообщают о ходе работы."""
    encoded = base64.b64encode((PREAMBLE + script).encode("utf-16-le")).decode("ascii")
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(
            [_exe(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL, **NO_WINDOW)
        rest = []
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if line.startswith("@@"):
                try:
                    on_event(json.loads(line[2:]))
                except ValueError:
                    pass
            elif line:
                rest.append(line)
        code = proc.wait(timeout=timeout)
        if code != 0:
            err.seek(0)
            raise PowerShellError(_clean_error(err.read().decode("utf-8", errors="replace")).strip()[-2000:]
                                  or "\n".join(rest)[-2000:])
    return "\n".join(rest)


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
