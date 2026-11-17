# Сборка: pyinstaller packaging/DriverUpdater.spec
# Результат: dist/DriverUpdater.exe (окно) и dist/DriverUpdater-cli.exe (консоль).
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "assets", "icon.ico")
VERSION = os.path.join(SPECPATH, "version_info.txt")
WEB = os.path.join(ROOT, "driverupdater", "webui", "web")
# Лишнее не тащим в exe — меньше размер и быстрее запуск.
EXCLUDES = ["tkinter", "PySide6", "PyQt5", "PyQt6", "qtpy", "gi", "cefpython3", "numpy", "test"]

gui = Analysis([os.path.join(SPECPATH, "gui_entry.py")], pathex=[ROOT],
               datas=[(WEB, "driverupdater/webui/web"), (ICON, "assets")],
               hiddenimports=["clr"], excludes=EXCLUDES)
gui_exe = EXE(PYZ(gui.pure), gui.scripts, gui.binaries, gui.datas,
              name="DriverUpdater", icon=ICON, version=VERSION,
              console=False, uac_admin=True, upx=False)

cli = Analysis([os.path.join(SPECPATH, "cli_entry.py")], pathex=[ROOT], excludes=EXCLUDES + ["webview"])
cli_exe = EXE(PYZ(cli.pure), cli.scripts, cli.binaries, cli.datas,
              name="DriverUpdater-cli", icon=ICON, version=VERSION,
              console=True, uac_admin=False, upx=False)
