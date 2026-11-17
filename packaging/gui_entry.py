"""Точка входа для сборки DriverUpdater.exe (графическая версия)."""
import sys

from driverupdater.webui.app import main

if __name__ == "__main__":
    sys.exit(main())
