# Сборка: pyinstaller packaging/DriverUpdater.spec
# Результат: dist/DriverUpdater.exe (окно) и dist/DriverUpdater-cli.exe (консоль).
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "assets", "icon.ico")
VERSION = os.path.join(SPECPATH, "version_info.txt")
# Модули Qt, которые программе не нужны, — не тащим в exe (меньше размер).
QT_EXCLUDES = ["PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetwork", "PySide6.QtPdf",
               "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtOpenGL", "PySide6.QtSvg",
               "PySide6.QtDBus", "PySide6.QtConcurrent", "PySide6.QtXml", "tkinter"]

gui = Analysis([os.path.join(SPECPATH, "gui_entry.py")], pathex=[ROOT],
               datas=[(ICON, "assets")], excludes=QT_EXCLUDES)
gui_exe = EXE(PYZ(gui.pure), gui.scripts, gui.binaries, gui.datas,
              name="DriverUpdater", icon=ICON, version=VERSION,
              console=False, uac_admin=True, upx=False)

cli = Analysis([os.path.join(SPECPATH, "cli_entry.py")], pathex=[ROOT],
               excludes=QT_EXCLUDES + ["PySide6"])
cli_exe = EXE(PYZ(cli.pure), cli.scripts, cli.binaries, cli.datas,
              name="DriverUpdater-cli", icon=ICON, version=VERSION,
              console=True, uac_admin=False, upx=False)
