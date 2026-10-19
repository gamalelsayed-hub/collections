"""Opening the program: data folder, user, lock."""
import os

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QVBoxLayout)

from ..db import DB
from ..storage import DataFolder, LockedError
from .widgets import error, warn


def choose_folder(parent=None, current=""):
    QMessageBox.information(parent, "فولدر البيانات",
                            "اختر الفولدر المشترك الذي تُحفظ فيه بيانات البرنامج (مثلًا فولدر على Google Drive).\n"
                            "كل الأجهزة التي تستخدم البرنامج يجب أن تختار نفس الفولدر.")
    path = QFileDialog.getExistingDirectory(parent, "فولدر البيانات", current or os.path.expanduser("~"))
    if path:
        QSettings().setValue("data_folder", path)
    return path


class UserDialog(QDialog):
    def __init__(self, db, last_user):
        super().__init__()
        self.db = db
        self.setWindowTitle("الدخول")
        f = QFormLayout(self)
        f.addRow(QLabel("اسم المستخدم يظهر في سجل العمليات وفي رسالة القفل للزميل الآخر."))
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.addItems([u["name"] for u in db.users()])
        if last_user:
            self.name.setCurrentText(last_user)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        f.addRow("الاسم:", self.name)
        f.addRow("كلمة السر:", self.password)
        if db.setting("require_password") != "1":
            self.password.setPlaceholderText("(غير مطلوبة إلا لو اتعملت للمستخدم)")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _ok(self):
        name = self.name.currentText().strip()
        if not name:
            warn(self, "اكتب اسمك.")
            return
        known = {u["name"]: u for u in self.db.users()}
        if name in known:
            if not self.db.check_password(name, self.password.text()):
                warn(self, "كلمة السر غير صحيحة.")
                return
        else:
            if self.db.setting("require_password") == "1" and known:
                warn(self, "المستخدم غير مسجل. اطلب من المسؤول إضافتك من الإعدادات.")
                return
            self.db.save_user(name)
        self.accept()

    def user(self):
        return self.name.currentText().strip()


class LockedDialog(QDialog):
    """Shown when the program is already open on another computer."""
    READ_ONLY, UNLOCK = 1, 2

    def __init__(self, lock):
        super().__init__()
        self.choice = None
        self.setWindowTitle("البرنامج مفتوح على جهاز آخر")
        v = QVBoxLayout(self)
        msg = QLabel(f"البرنامج مفتوح حالياً عند «{lock.get('user', '—')}» على جهاز «{lock.get('machine', '—')}» "
                     f"منذ {lock.get('since', '—')}.\n\nيمكنك الفتح للاطلاع فقط بدون تعديل، أو فك القفل إذا كان "
                     "البرنامج أُغلق عنده فجأة (تأكد من الزميل أولاً حتى لا تضيع بيانات).")
        msg.setWordWrap(True)
        v.addWidget(msg)
        for text, val in (("فتح للاطلاع فقط", self.READ_ONLY), ("فك القفل والفتح للتعديل", self.UNLOCK)):
            b = QPushButton(text)
            b.setMinimumHeight(34)
            b.clicked.connect(lambda _=None, x=val: self._pick(x))
            v.addWidget(b)
        cancel = QPushButton("خروج")
        cancel.clicked.connect(self.reject)
        v.addWidget(cancel)

    def _pick(self, val):
        self.choice = val
        self.accept()


def open_session():
    """Returns (folder, db, user, readonly) or None if the user cancelled."""
    s = QSettings()
    path = s.value("data_folder", "")
    while not path or not os.path.isdir(path):
        if path and not os.path.isdir(path):
            warn(None, f"فولدر البيانات غير موجود أو غير متاح الآن:\n{path}\n\nتأكد أن Google Drive شغال، أو اختر الفولدر.")
        path = choose_folder(None, path)
        if not path:
            return None
    folder = DataFolder(path)
    copies = folder.conflict_copies()
    if copies:
        warn(None, "يوجد في فولدر البيانات نسخ متعارضة من قاعدة البيانات (غالبًا من مزامنة Google Drive):\n"
                   + "\n".join(os.path.basename(c) for c in copies)
                   + "\n\nالبرنامج يستخدم data.db فقط. راجع النسخ الأخرى قبل حذفها.")
    DataFolder.wait_for_sync(folder.db_path)
    try:
        db = DB(folder.db_path)
    except Exception as e:  # noqa: BLE001
        error(None, f"تعذر فتح قاعدة البيانات:\n{e}")
        return None
    dlg = UserDialog(db, s.value("user_name", ""))
    if dlg.exec() != QDialog.Accepted:
        db.close()
        return None
    user = dlg.user()
    s.setValue("user_name", user)
    db.user = user
    readonly = False
    try:
        folder.acquire(user)
    except LockedError as e:
        ld = LockedDialog(e.info)
        if ld.exec() != QDialog.Accepted:
            db.close()
            return None
        if ld.choice == LockedDialog.UNLOCK:
            folder.force_unlock()
            folder.acquire(user)
            db.log("فك القفل", f"كان مفتوحًا عند {e.info.get('user')} على {e.info.get('machine')}")
        else:
            readonly = True
    if not readonly:
        folder.backup("open")
        db.log("فتح البرنامج")
    return folder, db, user, readonly
