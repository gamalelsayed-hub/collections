"""Settings: rules and dates, e-mail, users, data folder and backups."""
import base64
import os

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from .. import mailer
from .widgets import ask, error, info, warn


def _enc(s):
    return base64.b64encode(s.encode("utf-8")).decode("ascii") if s else ""


def _dec(s):
    try:
        return base64.b64decode((s or "").encode("ascii")).decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""


def mail_config():
    s = QSettings()
    cfg = {"host": s.value("mail_host", ""), "port": s.value("mail_port", "465"), "user": s.value("mail_user", ""),
           "password": _dec(s.value("mail_password", "")), "sender_name": s.value("mail_sender", "")}
    return cfg if cfg["host"] and cfg["user"] and cfg["password"] else None


class SettingsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)

        # ---- rules & stage days
        w = QWidget()
        f = QFormLayout(w)
        self.company = QLineEdit()
        f.addRow("اسم الشركة:", self.company)
        self.custody = QComboBox()
        self.credit = QComboBox()
        for cb in (self.custody, self.credit):
            for d in (30, 60, 90, 120):
                cb.addItem(f"أكثر من {d} يوم", d)
        f.addRow("عميل عهدة مطلوب مطابقة إذا تأخر:", self.custody)
        f.addRow("عميل آجل مطلوب مطابقة إذا تأخر:", self.credit)
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 100)
        self.threshold.setSuffix(" %")
        f.addRow("نسبة السداد التي تعفي من الإجراء:", self.threshold)
        self.min_overdue = QSpinBox()
        self.min_overdue.setRange(0, 10_000_000)
        self.min_overdue.setSingleStep(100)
        self.min_overdue.setGroupSeparatorShown(True)
        self.min_overdue.setSuffix(" ريال")
        self.min_overdue.setToolTip("العميل الذي متأخره أقل من هذا المبلغ لا يدخل دورة المطابقة ولا تصدر له خطابات")
        f.addRow("أقل مبلغ متأخر للمطابقة (أكثر من):", self.min_overdue)
        self.max_customers = QSpinBox()
        self.max_customers.setRange(0, 100_000)
        self.max_customers.setSingleStep(10)
        self.max_customers.setSpecialValueText("بدون حد — كل العملاء المتأخرين")
        self.max_customers.setToolTip("مطابقة أكبر عدد من العملاء المتأخرين فقط هذا الشهر، بالترتيب من الأكبر متأخرًا")
        f.addRow("عدد العملاء في الدورة (الأكبر متأخرًا):", self.max_customers)
        self.days = {}
        for key, label in (("day_statements", "يوم تجهيز الكشوف"), ("day_finance", "يوم خطاب الإدارة المالية"),
                           ("day_legal", "يوم خطاب الإدارة القانونية"), ("day_action", "يوم الإجراء القانوني")):
            sp = QSpinBox()
            sp.setRange(1, 28)
            self.days[key] = sp
            f.addRow(label + " (من الشهر):", sp)
        b = QPushButton("💾 حفظ")
        b.clicked.connect(self.save_rules)
        f.addRow(b)
        tabs.addTab(w, "القواعد والمواعيد")

        # ---- e-mail
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("خادم الإيميل (يُحفظ على هذا الجهاز فقط)")
        f = QFormLayout(g)
        self.preset = QComboBox()
        self.preset.addItem("— اختر —", None)
        for name, (host, port) in mailer.PRESETS.items():
            self.preset.addItem(name, (host, port))
        self.preset.currentIndexChanged.connect(self._preset)
        self.host = QLineEdit()
        self.port = QLineEdit()
        self.user = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.sender = QLineEdit()
        f.addRow("نوع الإيميل:", self.preset)
        f.addRow("الخادم (SMTP):", self.host)
        f.addRow("المنفذ:", self.port)
        f.addRow("الإيميل:", self.user)
        f.addRow("كلمة سر التطبيق:", self.password)
        f.addRow("اسم المرسل:", self.sender)
        note = QLabel("Zoho: من حسابك ← Security ← App Passwords ← أنشئ كلمة سر للبرنامج واستخدمها هنا (وليس كلمة سرك "
                      "العادية). حسابات الشركات غالبًا smtppro.zoho.com.")
        note.setWordWrap(True)
        f.addRow(note)
        v.addWidget(g)
        g2 = QGroupBox("نص الرسالة للمندوب — المتغيرات: {rep} {month} {count}")
        f2 = QFormLayout(g2)
        self.subject = QLineEdit()
        self.body = QPlainTextEdit()
        self.body.setMinimumHeight(140)
        f2.addRow("الموضوع:", self.subject)
        f2.addRow("النص:", self.body)
        v.addWidget(g2)
        bar = QHBoxLayout()
        for text, fn in (("💾 حفظ", self.save_mail), ("🔌 اختبار (إرسال رسالة لنفسي)", self.test_mail)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        v.addLayout(bar)
        tabs.addTab(w, "الإيميل")

        # ---- users
        w = QWidget()
        v = QVBoxLayout(w)
        self.require_pw = QCheckBox("طلب كلمة السر عند الدخول")
        v.addWidget(self.require_pw)
        self.users = QListWidget()
        v.addWidget(self.users)
        f = QFormLayout()
        self.new_user = QLineEdit()
        self.new_pw = QLineEdit()
        self.new_pw.setEchoMode(QLineEdit.Password)
        f.addRow("اسم المستخدم:", self.new_user)
        f.addRow("كلمة السر:", self.new_pw)
        v.addLayout(f)
        b = QPushButton("💾 حفظ المستخدم / تغيير كلمة السر")
        b.clicked.connect(self.save_user)
        v.addWidget(b)
        tabs.addTab(w, "المستخدمون")

        # ---- data folder & backups
        w = QWidget()
        v = QVBoxLayout(w)
        self.folder_lbl = QLabel()
        self.folder_lbl.setWordWrap(True)
        v.addWidget(self.folder_lbl)
        bar = QHBoxLayout()
        for text, fn in (("📂 فتح الفولدر", self.open_folder), ("تغيير فولدر البيانات", self.change_folder)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        v.addLayout(bar)
        v.addWidget(QLabel("النسخ الاحتياطية (تلقائية عند كل فتح وإغلاق — آخر 30 نسخة):"))
        self.backups = QListWidget()
        v.addWidget(self.backups, 1)
        bar = QHBoxLayout()
        for text, fn in (("💾 نسخة احتياطية الآن", self.backup_now), ("↩ استرجاع النسخة المحددة", self.restore)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        v.addLayout(bar)
        tabs.addTab(w, "البيانات والنسخ الاحتياطية")

    # ---------------------------------------------------------------- load
    def load(self):
        db = self.win.db
        self.company.setText(db.setting("company"))
        self.custody.setCurrentIndex(max(0, self.custody.findData(int(db.setting_num("custody_days")))))
        self.credit.setCurrentIndex(max(0, self.credit.findData(int(db.setting_num("credit_days")))))
        self.threshold.setValue(int(round(db.setting_num("pay_threshold") * 100)))
        self.min_overdue.setValue(int(db.setting_num("min_overdue")))
        self.max_customers.setValue(int(db.setting_num("max_customers")))
        for k, sp in self.days.items():
            sp.setValue(int(db.setting_num(k)))
        s = QSettings()
        self.host.setText(s.value("mail_host", ""))
        self.port.setText(str(s.value("mail_port", "465")))
        self.user.setText(s.value("mail_user", ""))
        self.password.setText(_dec(s.value("mail_password", "")))
        self.sender.setText(s.value("mail_sender", "الإدارة المالية"))
        self.subject.setText(db.setting("mail_subject"))
        self.body.setPlainText(db.setting("mail_body"))
        self.require_pw.setChecked(db.setting("require_password") == "1")
        self.users.clear()
        for u in db.users():
            self.users.addItem(f"{u['name']}" + ("  🔒" if u["password"] else ""))
        self.folder_lbl.setText(f"فولدر البيانات: {self.win.folder.path}")
        self.backups.clear()
        for p in self.win.folder.backups():
            self.backups.addItem(os.path.basename(p))

    # ---------------------------------------------------------------- actions
    def save_rules(self):
        if not self.win.can_edit():
            return
        db = self.win.db
        db.set_setting("company", self.company.text().strip())
        db.set_setting("custody_days", self.custody.currentData())
        db.set_setting("credit_days", self.credit.currentData())
        db.set_setting("pay_threshold", self.threshold.value() / 100)
        db.set_setting("min_overdue", self.min_overdue.value())
        db.set_setting("max_customers", self.max_customers.value())
        for k, sp in self.days.items():
            db.set_setting(k, sp.value())
        db.log("تعديل الإعدادات")
        info(self, "تم الحفظ. القواعد الجديدة تُطبّق عند رفع تقرير الأعمار القادم.")

    def _preset(self):
        d = self.preset.currentData()
        if d:
            self.host.setText(d[0])
            self.port.setText(str(d[1]))

    def save_mail(self):
        s = QSettings()
        s.setValue("mail_host", self.host.text().strip())
        s.setValue("mail_port", self.port.text().strip() or "465")
        s.setValue("mail_user", self.user.text().strip())
        s.setValue("mail_password", _enc(self.password.text()))
        s.setValue("mail_sender", self.sender.text().strip())
        if self.win.can_edit(silent=True):
            self.win.db.set_setting("mail_subject", self.subject.text())
            self.win.db.set_setting("mail_body", self.body.toPlainText())
        info(self, "تم حفظ إعدادات الإيميل.")

    def test_mail(self):
        self.save_mail()
        cfg = mail_config()
        if not cfg:
            warn(self, "أكمل الخادم والإيميل وكلمة سر التطبيق.")
            return
        try:
            res = mailer.send_all(cfg, [(cfg["user"], "اختبار برنامج التحصيل", "رسالة اختبار — الإعدادات تعمل.", [])])
        except Exception as e:  # noqa: BLE001
            error(self, f"فشل الاتصال:\n{e}")
            return
        ok = res and res[0][1]
        (info if ok else error)(self, "تم الإرسال — راجع صندوق الوارد." if ok else f"فشل: {res[0][2]}")

    def save_user(self):
        if not self.win.can_edit():
            return
        db = self.win.db
        db.set_setting("require_password", "1" if self.require_pw.isChecked() else "0")
        name = self.new_user.text().strip()
        if name:
            db.save_user(name, self.new_pw.text())
            db.log("حفظ مستخدم", name)
        self.new_user.clear()
        self.new_pw.clear()
        self.load()
        info(self, "تم الحفظ.")

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.win.folder.path))

    def change_folder(self):
        from .startup import choose_folder
        if choose_folder(self, self.win.folder.path):
            info(self, "أغلق البرنامج وافتحه مرة أخرى لاستخدام الفولدر الجديد.")

    def backup_now(self):
        if self.win.can_edit():
            self.win.folder.backup("manual")
            self.load()

    def restore(self):
        if not self.win.can_edit():
            return
        item = self.backups.currentItem()
        if not item:
            return
        path = os.path.join(self.win.folder.path, "backups", item.text())
        if not ask(self, f"استرجاع النسخة {item.text()}؟\nسيتم حفظ نسخة من الوضع الحالي قبل الاسترجاع."):
            return
        self.win.restore_backup(path)
