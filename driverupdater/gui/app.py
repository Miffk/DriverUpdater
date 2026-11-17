"""Графическая версия DriverUpdater (Qt 6 / PySide6)."""

from __future__ import annotations

import argparse
import ctypes
import html
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
    QStyleFactory, QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from .. import __version__, classify, engine, installer, powershell
from ..models import Action, Assessment, Necessity, SystemInfo
from ..report import SOURCE_NAMES, fmt_size

APP_NAME = "DriverUpdater"
ROLE = Qt.ItemDataRole.UserRole

GROUP_COLORS = {
    Necessity.REQUIRED: "#e5484d",
    Necessity.RECOMMENDED: "#f08c00",
    Necessity.OPTIONAL: "#3b82f6",
    Necessity.NOT_NEEDED: "#30a46c",
}
GROUP_HINTS = {
    Necessity.REQUIRED: "без них устройства не работают или работают плохо",
    Necessity.RECOMMENDED: "устройство работает, но обновление заметно полезно",
    Necessity.OPTIONAL: "по желанию — польза небольшая",
    Necessity.NOT_NEEDED: "всё в порядке",
}

STYLE = """
QMainWindow { background: palette(window); }
QFrame#card { background: palette(base); border: 1px solid palette(mid); border-radius: 10px; }
QLabel#title { font-size: 20px; font-weight: 600; }
QLabel#muted { color: palette(placeholder-text); }
QLabel#key { color: palette(placeholder-text); }
QPushButton { padding: 7px 16px; border-radius: 6px; background: palette(button);
              border: 1px solid palette(mid); }
QPushButton:hover { border-color: #2563eb; }
QPushButton:disabled { color: palette(placeholder-text); }
QPushButton#primary { background: #2563eb; color: white; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#primary:disabled { background: #93a8d8; color: #eef2fb; }
QTreeWidget { border: 1px solid palette(mid); border-radius: 8px; padding: 4px; }
QTreeWidget::item { padding: 4px 2px; }
QTabWidget::pane { border: 1px solid palette(mid); border-radius: 8px; top: -1px; }
QTextBrowser, QPlainTextEdit { border: none; }
QProgressBar { border: none; max-height: 6px; background: palette(mid); border-radius: 3px; }
QProgressBar::chunk { background: #2563eb; border-radius: 3px; }
"""


# ───────────────────────── фоновые задачи ─────────────────────────

class Worker(QObject):
    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[Callable[[str], None]], object]):
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn(self.log.emit))
        except Exception as e:  # noqa: BLE001 — любую ошибку показываем пользователю
            self.failed.emit(f"{type(e).__name__}: {e}")


# ───────────────────────── окно ─────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, args: argparse.Namespace):
        super().__init__()
        self.args = args
        self.items: list[Assessment] = []
        self.searched = False
        self.busy = False
        self.installing = False
        self._worker: Worker | None = None

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1180, 780)
        self.setMinimumSize(QSize(900, 600))
        self._build_ui()
        if args.selftest:  # проверка сборки: окно создаётся и сразу закрывается
            QTimer.singleShot(1500, QApplication.quit)
        else:
            QTimer.singleShot(0, self.start_scan)

    # ---------- интерфейс ----------

    def _build_ui(self) -> None:
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(16, 14, 16, 10)
        lay.setSpacing(12)

        # Заголовок
        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("DriverUpdater")
        title.setObjectName("title")
        self.subtitle = QLabel("Определяю оборудование…")
        self.subtitle.setObjectName("muted")
        title_box.addWidget(title)
        title_box.addWidget(self.subtitle)
        head.addLayout(title_box, 1)

        self.btn_search = QPushButton("Найти драйверы")
        self.btn_search.clicked.connect(self.start_check)
        self.btn_install = QPushButton("Установить выбранные")
        self.btn_install.setObjectName("primary")
        self.btn_install.setEnabled(False)
        self.btn_install.clicked.connect(self.start_install)
        head.addWidget(self.btn_search)
        head.addWidget(self.btn_install)
        lay.addLayout(head)

        # Карточка «Ваш компьютер»
        card = QFrame()
        card.setObjectName("card")
        self.sys_grid = QGridLayout(card)
        self.sys_grid.setContentsMargins(16, 12, 16, 12)
        self.sys_grid.setHorizontalSpacing(18)
        self.sys_grid.setVerticalSpacing(4)
        self.sys_labels: dict[str, QLabel] = {}
        fields = [("Компьютер", "pc"), ("Процессор", "cpu"), ("Видеокарта", "gpu"),
                  ("Плата", "board"), ("Память", "ram"), ("Система", "os")]
        for i, (caption, key) in enumerate(fields):
            k = QLabel(caption)
            k.setObjectName("key")
            v = QLabel("—")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v.setWordWrap(True)
            self.sys_labels[key] = v
            r, c = i % 3, (i // 3) * 2
            self.sys_grid.addWidget(k, r, c)
            self.sys_grid.addWidget(v, r, c + 1)
        self.sys_grid.setColumnStretch(1, 1)
        self.sys_grid.setColumnStretch(3, 1)
        lay.addWidget(card)

        # Опции
        opts = QHBoxLayout()
        self.chk_show_ok = QCheckBox("Показывать исправные устройства")
        self.chk_show_ok.toggled.connect(self.populate)
        self.chk_restore = QCheckBox("Создать точку восстановления перед установкой")
        self.chk_restore.setChecked(True)
        self.chk_deep = QCheckBox("Глубокий поиск в каталоге Microsoft (дольше)")
        opts.addWidget(self.chk_show_ok)
        opts.addStretch(1)
        opts.addWidget(self.chk_deep)
        opts.addWidget(self.chk_restore)
        lay.addLayout(opts)

        # Список драйверов + подробности/журнал
        split = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Устройство", "Установлено сейчас", "Будет установлено", "Источник", "Размер"])
        self.tree.setUniformRowHeights(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setIndentation(18)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setStretchLastSection(False)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.currentItemChanged.connect(self._on_current_changed)
        split.addWidget(self.tree)

        self.tabs = QTabWidget()
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(True)
        self.details.setHtml(self._placeholder())
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 9))
        self.tabs.addTab(self.details, "Почему")
        self.tabs.addTab(self.log_view, "Журнал")
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([400, 260])
        lay.addWidget(split, 1)

        # Статус
        status = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(220)
        self.progress.hide()
        status.addWidget(self.status_label, 1)
        status.addWidget(self.progress)
        lay.addLayout(status)

        self.setCentralWidget(root)

        about = QAction("О программе", self)
        about.triggered.connect(self._about)
        self.menuBar().addAction(about)

    @staticmethod
    def _placeholder() -> str:
        return ("<p style='color:gray'>Выберите устройство в списке — здесь появится объяснение, "
                "зачем нужен (или не нужен) драйвер.</p>")

    # ---------- фоновые задачи ----------

    def _run(self, fn, on_done, status: str) -> None:
        if self.busy:
            return
        self.busy = True
        self._set_controls()
        self.status_label.setText(status)
        self.progress.show()
        # Задача идёт в обычном фоновом потоке Python (daemon — не мешает закрыть окно
        # во время поиска). Сигналы Worker доставляются в поток интерфейса через очередь Qt.
        # Подключаем только методы окна, а не lambda: так Qt вызывает их в потоке интерфейса.
        self._on_done_cb = on_done
        worker = Worker(fn)
        worker.log.connect(self._log)
        worker.done.connect(self._worker_done)
        worker.failed.connect(self._worker_failed)
        self._worker = worker
        threading.Thread(target=worker.run, daemon=True, name="driverupdater-task").start()

    def _worker_done(self, payload) -> None:
        self._finish(self._on_done_cb, payload)

    def _worker_failed(self, err: str) -> None:
        self._finish(self._on_failed, err)

    def _finish(self, cb, payload) -> None:
        self.busy = False
        self.installing = False
        self.progress.hide()
        self.status_label.setText("")
        cb(payload)
        self._set_controls()

    def _on_failed(self, err: str) -> None:
        self._log(f"ОШИБКА: {err}")
        QMessageBox.critical(self, APP_NAME, err)

    def _log(self, msg: str) -> None:
        self.log_view.appendPlainText(msg)

    def _set_controls(self) -> None:
        self.btn_search.setEnabled(not self.busy)
        n = len(self.selected())
        self.btn_install.setEnabled(not self.busy and n > 0)
        self.btn_install.setText(f"Установить выбранные ({n})" if n else "Установить выбранные")
        self.chk_deep.setEnabled(not self.busy)

    # ---------- сканирование и поиск ----------

    def start_scan(self) -> None:
        a = self.args

        def job(log):
            log("Определение оборудования…")
            return engine.scan(a.from_file)

        self._run(job, self._on_scanned, "Определяю оборудование…")

    def _on_scanned(self, res: engine.ScanResult) -> None:
        self._show_system(res.system)
        self.items, self.searched = res.items, False
        self.populate()
        self._log(f"Найдено устройств: {len(res.devices)}")
        # Сразу ищем драйверы — пользователю не нужно ничего нажимать.
        QTimer.singleShot(0, self.start_check)

    def start_check(self) -> None:
        a, deep = self.args, self.chk_deep.isChecked()

        def job(log):
            return engine.check(a.from_file, offers_file=a.offers_file, deep=deep, log=log)

        self._run(job, self._on_checked,
                  "Ищу драйверы в Windows Update и каталоге Microsoft… это может занять несколько минут")

    def _on_checked(self, res: engine.ScanResult) -> None:
        self._show_system(res.system)
        self.items, self.searched = res.items, True
        self.populate()
        counts = {n: sum(1 for i in self.items if i.necessity == n and i.action != Action.NONE)
                  for n in Necessity}
        self.subtitle.setText(
            f"Необходимо: {counts[Necessity.REQUIRED]}   •   Рекомендуется: {counts[Necessity.RECOMMENDED]}"
            f"   •   Необязательно: {counts[Necessity.OPTIONAL]}")
        self._log("Поиск завершён.")

    def _show_system(self, s: SystemInfo) -> None:
        L = self.sys_labels
        L["pc"].setText(f"{s.manufacturer} {s.model}".strip() or "—")
        L["cpu"].setText(s.cpu or "—")
        L["gpu"].setText(", ".join(s.gpus) or "—")
        L["board"].setText(s.board or "—")
        L["ram"].setText(f"{s.ram_gb:g} ГБ" if s.ram_gb else "—")
        L["os"].setText(f"{s.os_name} (сборка {s.os_build}, {s.arch})" if s.os_name else "—")
        if not self.searched:
            self.subtitle.setText("Ищу драйверы…")

    # ---------- список ----------

    def populate(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        show_ok = self.chk_show_ok.isChecked()
        bold = QFont()
        bold.setBold(True)
        for nec in Necessity:
            group = [a for a in self.items if a.necessity == nec
                     and (show_ok or nec != Necessity.NOT_NEEDED)
                     and not (a.device.is_virtual and a.action == Action.NONE and not show_ok)]
            if not group:
                continue
            top = QTreeWidgetItem([f"{nec.label.capitalize()} — {len(group)}", "", "", "", ""])
            top.setFont(0, bold)
            top.setForeground(0, QColor(GROUP_COLORS[nec]))
            top.setToolTip(0, GROUP_HINTS[nec])
            top.setFirstColumnSpanned(True)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(top)
            for a in group:
                top.addChild(self._make_row(a))
            top.setExpanded(True)
            top.setFirstColumnSpanned(True)
        if not self.items:
            pass
        elif self.tree.topLevelItemCount() == 0:
            empty = QTreeWidgetItem(["Все драйверы в порядке — устанавливать ничего не нужно."])
            empty.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(empty)
        self.tree.blockSignals(False)
        self._set_controls()

    def _make_row(self, a: Assessment) -> QTreeWidgetItem:
        d, o = a.device, a.offer
        current = f"{d.driver_version}  ({d.driver_date})" if d.driver_version else "нет драйвера"
        if o:
            new = " от ".join(x for x in (o.version, o.date) if x) or o.title
            src = SOURCE_NAMES.get(o.source, o.source)
            size = fmt_size(o.size_bytes) if o.size_bytes else ""
        elif a.action != Action.NONE:
            new, src, size = "не найден автоматически", "сайт производителя", ""
        else:
            new, src, size = "—", "", ""
        row = QTreeWidgetItem([d.name or d.instance_id, current, new, src, size])
        row.setData(0, ROLE, a)
        row.setToolTip(0, a.reason)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if engine.is_installable(a, allow_firmware=True):
            flags |= Qt.ItemFlag.ItemIsUserCheckable
            row.setFlags(flags)
            row.setCheckState(0, Qt.CheckState.Checked if engine.default_selected(a)
                              else Qt.CheckState.Unchecked)
        else:
            row.setFlags(flags)
        if a.action != Action.NONE and not o:
            row.setForeground(2, QColor(GROUP_COLORS[Necessity.RECOMMENDED]))
        return row

    def _rows(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                yield top.child(j)

    def selected(self) -> list[Assessment]:
        return [r.data(0, ROLE) for r in self._rows()
                if r.flags() & Qt.ItemFlag.ItemIsUserCheckable
                and r.checkState(0) == Qt.CheckState.Checked]

    def _on_item_changed(self, item: QTreeWidgetItem, col: int) -> None:
        a: Assessment | None = item.data(0, ROLE)
        if a and col == 0 and item.checkState(0) == Qt.CheckState.Checked and not a.auto_install:
            ok = QMessageBox.warning(
                self, "Обновление прошивки",
                "Это обновление прошивки (BIOS/UEFI или контроллера).\n\n"
                "Если во время прошивки пропадёт питание, компьютер может перестать включаться. "
                "Ставьте его, только если знаете, зачем оно нужно.\n\nВсё равно установить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ok != QMessageBox.StandardButton.Yes:
                self.tree.blockSignals(True)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                self.tree.blockSignals(False)
        self._set_controls()

    def _on_current_changed(self, item: QTreeWidgetItem | None, _prev) -> None:
        a: Assessment | None = item.data(0, ROLE) if item else None
        if not a:
            self.details.setHtml(self._placeholder())
            return
        self.tabs.setCurrentWidget(self.details)
        self.details.setHtml(self._details_html(a))

    def _details_html(self, a: Assessment) -> str:
        e = html.escape
        d, o = a.device, a.offer
        color = GROUP_COLORS[a.necessity]
        rows = [
            ("Тип", classify.effective_class(d, o) or "неизвестно"),
            ("Установлено", f"{d.driver_version} от {d.driver_date} ({d.driver_provider})"
             if d.driver_version else "драйвер отсутствует"),
        ]
        if o:
            rows.append(("Найдено", f"{o.title} — {SOURCE_NAMES.get(o.source, o.source)}"
                         + (f", {fmt_size(o.size_bytes)}" if o.size_bytes else "")))
        if d.hardware_ids:
            rows.append(("ID оборудования", d.hardware_ids[0]))
        table = "".join(f"<tr><td style='color:gray;padding-right:14px'>{e(k)}</td><td>{e(v)}</td></tr>"
                        for k, v in rows)
        extra = ""
        if not a.auto_install:
            extra += ("<p style='color:#e5484d'>⚠ Прошивка не ставится автоматически. "
                      "Отметьте её вручную, только если уверены.</p>")
        if a.manual_hint:
            name, _, url = a.manual_hint.partition(": ")
            lead = ("Автоматически не найден. Скачайте с официального сайта"
                    if not o else "Самые свежие версии — на официальном сайте")
            extra += f"<p>{lead} {e(name)}: <a href='{e(url)}'>{e(url)}</a></p>"
        return (f"<h3 style='margin:0'>{e(d.name)}</h3>"
                f"<p style='margin:4px 0 8px 0'><b style='color:{color}'>{e(a.necessity.label)}</b>"
                f" &nbsp;·&nbsp; {e(a.action.label)}</p>"
                f"<p>{e(a.reason)}</p><table>{table}</table>{extra}")

    # ---------- установка ----------

    def start_install(self) -> None:
        plan = engine.order_plan(self.selected())
        if not plan:
            return
        if not installer.is_admin() and powershell.is_windows():
            if QMessageBox.question(
                    self, APP_NAME, "Для установки драйверов нужны права администратора.\n"
                    "Перезапустить программу от имени администратора?") == QMessageBox.StandardButton.Yes:
                relaunch_as_admin()
            return
        total = sum(a.offer.size_bytes for a in plan if a.offer)
        lst = "\n".join(f"•  {a.device.name}" for a in plan[:15])
        more = f"\n… и ещё {len(plan) - 15}" if len(plan) > 15 else ""
        if QMessageBox.question(
                self, "Установка драйверов",
                f"Будет установлено драйверов: {len(plan)} (~{fmt_size(total)}).\n\n{lst}{more}\n\n"
                "После установки скачанные файлы будут удалены. Продолжить?"
        ) != QMessageBox.StandardButton.Yes:
            return

        restore = self.chk_restore.isChecked()
        self.installing = True
        self.tabs.setCurrentWidget(self.log_view)

        def job(log):
            if restore:
                log("Создание точки восстановления системы…")
                try:
                    installer.create_restore_point()
                    log("  готово")
                except powershell.PowerShellError as e:
                    raise RuntimeError(
                        "Не удалось создать точку восстановления. Возможно, защита системы "
                        "отключена. Снимите галочку «Создать точку восстановления», если "
                        f"хотите продолжить без неё.\n\n{e}") from e
            return installer.install(plan, log=log)

        self._run(job, self._on_installed, "Устанавливаю драйверы… не выключайте компьютер")

    def _on_installed(self, rep: installer.Report) -> None:
        ok = sum(r.ok for r in rep.results)
        lines = "\n".join(f"{'✔' if r.ok else '✘'}  {r.name}: {r.message}" for r in rep.results)
        msg = (f"Успешно: {ok} из {len(rep.results)}\n\n{lines}\n\n"
               f"Удалено установочных файлов: {fmt_size(rep.cleaned_bytes)}")
        if rep.reboot_required:
            msg += "\n\nДля завершения установки нужно перезагрузить компьютер. Перезагрузить сейчас?"
            if QMessageBox.question(self, "Установка завершена", msg) == QMessageBox.StandardButton.Yes:
                subprocess.Popen(["shutdown", "/r", "/t", "5"], **powershell.NO_WINDOW)
                return
        else:
            QMessageBox.information(self, "Установка завершена", msg)
        QTimer.singleShot(0, self.start_check)

    # ---------- прочее ----------

    def _about(self) -> None:
        QMessageBox.about(
            self, "О программе",
            f"<b>{APP_NAME} {__version__}</b><br><br>"
            "Определяет оборудование компьютера, находит драйверы в официальных источниках "
            "Microsoft (Windows Update и Microsoft Update Catalog), устанавливает их и удаляет "
            "установочные файлы.<br><br>Перед установкой создаётся точка восстановления, "
            "у всех файлов проверяется цифровая подпись Microsoft.")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self.installing:
            QMessageBox.warning(self, APP_NAME, "Идёт установка драйверов. Дождитесь её завершения.")
            event.ignore()
            return
        event.accept()


def relaunch_as_admin() -> None:
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, " ".join(f'"{x}"' for x in sys.argv[1:])
    else:
        exe, params = sys.executable, "-m driverupdater.gui " + " ".join(f'"{x}"' for x in sys.argv[1:])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)  # type: ignore[attr-defined]
    if rc > 32:
        QApplication.quit()


def icon_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return base / "assets" / "icon.ico"


def create_app(argv: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    p = argparse.ArgumentParser(prog="DriverUpdater")
    p.add_argument("--from-file", help=argparse.SUPPRESS)
    p.add_argument("--offers-file", help=argparse.SUPPRESS)
    p.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    args, _ = p.parse_known_args(argv)

    if sys.platform == "win32":
        # Своя иконка на панели задач вместо иконки Python.
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DriverUpdater.App")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    if "Fusion" in QStyleFactory.keys():
        app.setStyle("Fusion")  # современный вид + автоматическая тёмная тема Windows 10/11
    app.setStyleSheet(STYLE)
    if icon_path().exists():
        app.setWindowIcon(QIcon(str(icon_path())))
    win = MainWindow(args)
    return app, win


def main(argv: list[str] | None = None) -> int:
    app, win = create_app(argv)
    win.show()
    return app.exec()
