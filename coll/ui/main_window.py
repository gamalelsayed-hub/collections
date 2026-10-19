"""Main window of the collections program."""
from datetime import date

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox, QStackedWidget, QToolBar,
                               QVBoxLayout, QWidget)

from ..db import DB
from ..updater import UpdateChecker
from ..version import BUILD
from .cycle_page import CyclePage
from .people_pages import CustomerDialog, CustomersPage, LogPage, RepsPage
from .settings_page import SettingsPage, mail_config
from .widgets import NAVY, error, info, month_label, warn


class MainWindow(QMainWindow):
    def __init__(self, folder, db, user, readonly):
        super().__init__()
        self.folder, self.db, self.user, self.readonly = folder, db, user, readonly
        self.resize(1400, 860)
        version = f"نسخة {BUILD}" if BUILD else "نسخة تطوير"
        self.setWindowTitle(f"برنامج المطابقة والتحصيل — {db.setting('company')}   [{user}]   [{version}]"
                            + ("   — للاطلاع فقط" if readonly else ""))
        tb = QToolBar()
        tb.setMovable(False)
        tb.setStyleSheet("QToolBar { spacing: 6px; padding: 4px; } QToolButton { padding: 5px 10px; font-weight:600; }")
        self.addToolBar(tb)
        self.banner = QLabel()
        self.banner.setStyleSheet("color:#b54708; font-weight:700; padding: 0 8px;")
        tb.addWidget(self.banner)
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding, spacer.sizePolicy().verticalPolicy())
        tb.addWidget(spacer)
        up = QAction("🔄 فحص التحديثات", self)
        up.triggered.connect(lambda: self.check_updates(True))
        tb.addAction(up)

        central = QWidget()
        h = QHBoxLayout(central)
        self.nav = QListWidget()
        self.nav.setFixedWidth(210)
        self.nav.setStyleSheet(
            f"QListWidget {{ background:{NAVY}; color:white; font-size:11pt; border:none; }}"
            "QListWidget::item { padding:13px 10px; } QListWidget::item:selected { background:#1d6fb8; }")
        self.stack = QStackedWidget()
        self.cycle_page = CyclePage(self)
        self.customers_page = CustomersPage(self)
        self.pages = [("🔄 الدورة الشهرية", self.cycle_page), ("👥 العملاء", self.customers_page),
                      ("🧑‍💼 المناديب", RepsPage(self)), ("📜 سجل العمليات", LogPage(self)),
                      ("⚙ الإعدادات", SettingsPage(self))]
        for title, page in self.pages:
            self.nav.addItem(title)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self._page)
        h.addWidget(self.nav)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        for _, p in self.pages:
            p.load()
        self.nav.setCurrentRow(0)
        self.update_banner()
        self.updater = UpdateChecker(self)
        self.updater.result.connect(self._update_result)
        self.updater.failed.connect(self._update_failed)
        self._manual = False
        self.check_updates(False)

    # ---------------------------------------------------------------- helpers
    def _page(self, i):
        self.stack.setCurrentIndex(i)
        page = self.pages[i][1]
        if page is not self.cycle_page:
            page.load()

    def can_edit(self, silent=False):
        if self.readonly and not silent:
            warn(self, "البرنامج مفتوح للاطلاع فقط لأنه مفتوح على جهاز آخر.")
        return not self.readonly

    def mail_config(self):
        return mail_config()

    def open_customer(self, code):
        CustomerDialog(self, code).exec()
        self.customers_page.load()

    def update_banner(self):
        """Remind the accountant of the stage due today."""
        today = date.today()
        month = f"{today.year:04d}-{today.month:02d}"
        cyc = self.db.cycle(month)
        stages = [("day_statements", "تجهيز الكشوف"), ("day_finance", "خطاب الإدارة المالية"),
                  ("day_legal", "خطاب الإدارة القانونية"), ("day_action", "الإجراء القانوني")]
        due = [name for key, name in stages if today.day >= int(self.db.setting_num(key))]
        if not cyc:
            self.banner.setText(f"⏰ دورة {month_label(month)} لم تبدأ — ارفع تقرير الأعمار (مرحلة {due[0] if due else 'تجهيز الكشوف'})")
        elif due:
            self.banner.setText(f"⏰ المرحلة الحالية لدورة {month_label(month)}: {due[-1]}")
        else:
            self.banner.setText("")

    def restore_backup(self, path):
        self.db.close()
        try:
            self.folder.restore(path)
        except Exception as e:  # noqa: BLE001
            error(self, f"تعذر الاسترجاع:\n{e}")
        self.db = DB(self.folder.db_path, self.user)
        self.db.log("استرجاع نسخة احتياطية", path)
        for _, p in self.pages:
            p.load()
        info(self, "تم الاسترجاع.")

    # ---------------------------------------------------------------- updates
    def check_updates(self, manual):
        self._manual = manual
        self.updater.check()

    def _update_result(self, newer, build, notes, url):
        if not newer:
            if self._manual:
                info(self, f"عندك أحدث نسخة (رقم {BUILD})." if BUILD else f"نسخة تطوير. آخر نسخة منشورة رقم {build}.")
            return
        box = QMessageBox(self)
        box.setWindowTitle("نسخة جديدة متاحة")
        box.setText(f"نسخة جديدة رقم {build} متاحة (عندك رقم {BUILD}).")
        box.setInformativeText("الجديد:\n" + (notes[:900] or "—") + "\n\nنزّل ملف التثبيت وشغّله؛ البيانات لا تتأثر.")
        dl = box.addButton("تنزيل الآن", QMessageBox.AcceptRole)
        box.addButton("لاحقًا", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is dl:
            QDesktopServices.openUrl(QUrl(url))

    def _update_failed(self, message):
        if self._manual:
            error(self, f"تعذر فحص التحديثات:\n{message}")

    # ---------------------------------------------------------------- closing
    def closeEvent(self, event):
        if not self.readonly:
            try:
                self.db.log("إغلاق البرنامج")
                self.db.close()
                self.folder.backup("close")
            finally:
                self.folder.release()
        else:
            self.db.close()
        event.accept()
