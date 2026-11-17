"""Точка входа для сборки DriverUpdater-cli.exe (консольная версия)."""
import sys

from driverupdater.cli import main

if __name__ == "__main__":
    sys.exit(main())
