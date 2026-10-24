"""Settings: rules and dates, e-mail, users, data folder and backups."""
import base64
import os

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
                               QTabWidget, QVBoxLayout,
                               QWidget)

from .. import mailer, stages
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
        inner = QWidget()
        outer = QVBoxLayout(inner)

        def group(title):
            g = QGroupBox(title)
            form = QFormLayout(g)
            outer.addWidget(g)
            return form

        def money_box(maximum=10_000_000, step=100):
            sp = QSpinBox()
            sp.setRange(0, maximum)
            sp.setSingleStep(step)
            sp.setGroupSeparatorShown(True)
            sp.setSuffix(" ريال")
            return sp

        def pct_box():
            sp = QSpinBox()
            sp.setRange(1, 100)
            sp.setSuffix(" %")
            return sp

        f = group("الشركة")
        self.company = QLineEdit()
        f.addRow("اسم الشركة:", self.company)

        f = group("مين يدخل دورة المطابقة (يُطبق عند رفع تقرير الأعمار)")
        self.custody = QComboBox()
        self.credit = QComboBox()
        for cb in (self.custody, self.credit):
            for d in (30, 60, 90, 120):
                cb.addItem(f"أكثر من {d} يوم", d)
        f.addRow("عميل عهدة مطلوب مطابقة إذا تأخر:", self.custody)
        f.addRow("عميل آجل مطلوب مطابقة إذا تأخر:", self.credit)
        self.min_overdue = money_box()
        self.min_overdue.setToolTip("العميل الذي متأخره أقل من هذا المبلغ لا يدخل دورة المطابقة ولا تصدر له خطابات")
        f.addRow("أقل مبلغ متأخر للمطابقة (أكثر من):", self.min_overdue)
        self.max_customers = QSpinBox()
        self.max_customers.setRange(0, 100_000)
        self.max_customers.setSingleStep(10)
        self.max_customers.setSpecialValueText("بدون حد — كل العملاء المتأخرين")
        self.max_customers.setToolTip("مطابقة أكبر عدد من العملاء المتأخرين فقط هذا الشهر، بالترتيب من الأكبر متأخرًا")
        f.addRow("عدد العملاء في الدورة (الأكبر متأخرًا):", self.max_customers)
        self.guarantee = QCheckBox("العميل الذي عنده ضمان بنكي يغطي المتأخر لا يدخل الدورة")
        self.rest = QCheckBox("العميل الذي طابق وسدد النسبة في الدورة السابقة يرتاح هذا الشهر")
        f.addRow(self.guarantee)
        f.addRow(self.rest)
        f.addRow(QLabel("استثناء مناديب أو تصنيفات أو عملاء بعينهم: من تبويب «الاستثناءات»."))

        f = group("الخطابات")
        self.threshold = pct_box()
        self.threshold_legal = pct_box()
        self.threshold_action = pct_box()
        f.addRow("نسبة السداد التي تعفي من خطاب الإدارة المالية:", self.threshold)
        f.addRow("نسبة السداد التي توقف الخطاب القانوني:", self.threshold_legal)
        f.addRow("نسبة السداد التي توقف التوجيه النهائي:", self.threshold_action)
        self.min_letter = money_box()
        self.min_letter.setSpecialValueText("بدون حد")
        f.addRow("لا يصدر خطاب إذا كان المبلغ المتبقي أقل من:", self.min_letter)
        self.letter_amount = QComboBox()
        for key, label in stages.LETTER_AMOUNTS.items():
            self.letter_amount.addItem(label, key)
        self.letter_amount.setToolTip("الرصيد والمتأخر من تقرير الأعمار يوم 1، والسداد = سندات القبض المحسوبة حتى "
                                      "نهاية المرحلة. تقدر تعدل مبلغ أي خطاب يدويًا قبل الإصدار.")
        f.addRow("مبلغ الخطاب:", self.letter_amount)

        f = group("المواعيد")
        self.days = {}
        for key, label in (("day_statements", "يوم تجهيز الكشوف"), ("day_finance", "يوم خطاب الإدارة المالية"),
                           ("day_legal", "يوم خطاب الإدارة القانونية"), ("day_action", "يوم التوجيه النهائي")):
            sp = QSpinBox()
            sp.setRange(1, 60)
            self.days[key] = sp
            f.addRow(label + " (من بداية الدورة):", sp)
        self.workdays = QCheckBox("حساب الأيام بأيام العمل (بدون أيام الإجازة الأسبوعية والإجازات الرسمية)")
        f.addRow(self.workdays)
        week = QHBoxLayout()
        self.weekend = {}
        for num, name in ((6, "الأحد"), (0, "الاثنين"), (1, "الثلاثاء"), (2, "الأربعاء"), (3, "الخميس"),
                          (4, "الجمعة"), (5, "السبت")):
            cb = QCheckBox(name)
            self.weekend[num] = cb
            week.addWidget(cb)
        week.addStretch()
        f.addRow("الإجازة الأسبوعية:", week)
        self.holidays = QPlainTextEdit()
        self.holidays.setPlaceholderText("تاريخ في كل سطر، مثل 23/09/2026")
        self.holidays.setMaximumHeight(90)
        f.addRow("الإجازات الرسمية:", self.holidays)

        f = group("الكشوف")
        self.attach_aging = QCheckBox("إرفاق صفحة أعمار الديون مع كشف كل عميل (إذا كان إجماليها = رصيد الكشف)")
        f.addRow(self.attach_aging)
        self.tolerance = money_box(100_000, 1)
        f.addRow("أقصى فرق مقبول بين رصيد الكشف وتقرير الأعمار:", self.tolerance)

        b = QPushButton("💾 حفظ الإعدادات")
        b.clicked.connect(self.save_rules)
        outer.addWidget(b)
        outer.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        tabs.addTab(scroll, "القواعد والمواعيد")

        # ---- exclusions
        w = QWidget()
        v = QVBoxLayout(w)
        note = QLabel("المحدد هنا لا يدخل أي دورة (يُطبق عند رفع تقرير الأعمار القادم).")
        note.setWordWrap(True)
        v.addWidget(note)
        row = QHBoxLayout()
        g = QGroupBox("مناديب مستثنون (كما في تقرير الأعمار)")
        gl = QVBoxLayout(g)
        self.skip_reps = QListWidget()
        gl.addWidget(self.skip_reps)
        row.addWidget(g)
        g = QGroupBox("تصنيفات عملاء مستثناة")
        gl = QVBoxLayout(g)
        self.skip_classes = QListWidget()
        gl.addWidget(self.skip_classes)
        row.addWidget(g)
        v.addLayout(row, 1)
        g = QGroupBox("عملاء مستثنون دائمًا (من بطاقة العميل أو كليك يمين في شاشة المتابعة)")
        gl = QVBoxLayout(g)
        self.perm = QListWidget()
        gl.addWidget(self.perm)
        b = QPushButton("↩ إلغاء الاستثناء الدائم للعميل المحدد")
        b.clicked.connect(self.remove_perm)
        gl.addWidget(b)
        v.addWidget(g, 1)
        b = QPushButton("💾 حفظ الاستثناءات")
        b.clicked.connect(self.save_exclusions)
        v.addWidget(b)
        tabs.addTab(w, "الاستثناءات")

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
        self.cc = QLineEdit()
        self.cc.setPlaceholderText("اختياري — مثل manager@company.com (أكثر من إيميل: افصل بفاصلة)")
        f2.addRow("نسخة لكل إيميل (CC):", self.cc)
        f2.addRow("الموضوع:", self.subject)
        f2.addRow("النص:", self.body)
        v.addWidget(g2)
        g3 = QGroupBox("المصادقة المباشرة للعميل — المتغيرات: {name} {code} {balance} {days} {deadline} {month} {company}")
        f3 = QFormLayout(g3)
        self.confirm_days = QSpinBox()
        self.confirm_days.setRange(1, 60)
        self.confirm_days.setSuffix(" يوم")
        self.d_subject = QLineEdit()
        self.d_body = QPlainTextEdit()
        self.d_body.setMinimumHeight(140)
        f3.addRow("عدم الرد خلال (يُعتبر مطابقًا):", self.confirm_days)
        f3.addRow("الموضوع:", self.d_subject)
        f3.addRow("النص:", self.d_body)
        v.addWidget(g3)
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
        self.threshold_legal.setValue(int(round(db.setting_num("pay_threshold_legal") * 100)))
        self.threshold_action.setValue(int(round(db.setting_num("pay_threshold_action") * 100)))
        self.min_overdue.setValue(int(db.setting_num("min_overdue")))
        self.max_customers.setValue(int(db.setting_num("max_customers")))
        self.guarantee.setChecked(db.setting("guarantee_skip") == "1")
        self.rest.setChecked(db.setting("rest_matched") == "1")
        self.min_letter.setValue(int(db.setting_num("min_letter")))
        self.letter_amount.setCurrentIndex(max(0, self.letter_amount.findData(db.setting("letter_amount"))))
        for k, sp in self.days.items():
            sp.setValue(int(db.setting_num(k)))
        self.workdays.setChecked(db.setting("workdays") == "1")
        off = {x.strip() for x in db.setting("weekend").split(",")}
        for num, cb in self.weekend.items():
            cb.setChecked(str(num) in off)
        self.holidays.setPlainText(db.setting("holidays"))
        self.attach_aging.setChecked(db.setting("attach_aging") == "1")
        self.tolerance.setValue(int(db.setting_num("balance_tolerance")))
        self.cc.setText(db.setting("mail_cc"))
        self.load_exclusions()
        s = QSettings()
        self.host.setText(s.value("mail_host", ""))
        self.port.setText(str(s.value("mail_port", "465")))
        self.user.setText(s.value("mail_user", ""))
        self.password.setText(_dec(s.value("mail_password", "")))
        self.sender.setText(s.value("mail_sender", "الإدارة المالية"))
        self.subject.setText(db.setting("mail_subject"))
        self.body.setPlainText(db.setting("mail_body"))
        self.confirm_days.setValue(int(db.setting_num("confirm_days")))
        self.d_subject.setText(db.setting("direct_subject"))
        self.d_body.setPlainText(db.setting("direct_body"))
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
        days = [self.days[k].value() for k in ("day_statements", "day_finance", "day_legal", "day_action")]
        if days != sorted(days) or len(set(days[1:])) < 3:
            warn(self, "ترتيب أيام المراحل غير صحيح: لازم يكون يوم الكشوف ← المالية ← القانونية ← الإجراء، "
                       "وكل مرحلة بعد التي قبلها.")
            return
        if self.workdays.isChecked() and all(cb.isChecked() for cb in self.weekend.values()):
            warn(self, "اخترت كل أيام الأسبوع إجازة — اترك يوم عمل واحد على الأقل.")
            return
        rates = [self.threshold.value(), self.threshold_legal.value(), self.threshold_action.value()]
        if rates != sorted(rates) and not ask(
                self, "نسبة السداد في مرحلة أقل من المرحلة التي قبلها — يعني عميل يُعفى من خطاب ثم يُطلب منه الخطاب "
                      "الأشد. متأكد من الحفظ؟"):
            return
        db = self.win.db
        db.set_setting("company", self.company.text().strip())
        db.set_setting("custody_days", self.custody.currentData())
        db.set_setting("credit_days", self.credit.currentData())
        db.set_setting("pay_threshold", self.threshold.value() / 100)
        db.set_setting("pay_threshold_legal", self.threshold_legal.value() / 100)
        db.set_setting("pay_threshold_action", self.threshold_action.value() / 100)
        db.set_setting("min_overdue", self.min_overdue.value())
        db.set_setting("max_customers", self.max_customers.value())
        db.set_setting("guarantee_skip", "1" if self.guarantee.isChecked() else "0")
        db.set_setting("rest_matched", "1" if self.rest.isChecked() else "0")
        db.set_setting("min_letter", self.min_letter.value())
        db.set_setting("letter_amount", self.letter_amount.currentData())
        for k, sp in self.days.items():
            db.set_setting(k, sp.value())
        db.set_setting("workdays", "1" if self.workdays.isChecked() else "0")
        db.set_setting("weekend", ",".join(str(n) for n, cb in self.weekend.items() if cb.isChecked()))
        db.set_setting("holidays", self.holidays.toPlainText().strip())
        db.set_setting("attach_aging", "1" if self.attach_aging.isChecked() else "0")
        db.set_setting("balance_tolerance", self.tolerance.value())
        db.log("تعديل الإعدادات")
        self.win.update_banner()
        info(self, "تم الحفظ.\n• قواعد دخول الدورة تُطبق عند رفع تقرير الأعمار القادم.\n"
                   "• قواعد الخطابات والمواعيد تُطبق فورًا على شاشة المتابعة.")

    def load_exclusions(self):
        db = self.win.db
        custs = db.customers().values()
        reps = sorted({c["rep_name"] for c in custs if c.get("rep_name")} | set(db.setting_list("skip_reps")))
        classes = sorted({c["cls"] for c in custs if c.get("cls")} | set(db.setting_list("skip_classes")))
        for lst, values, chosen in ((self.skip_reps, reps, set(db.setting_list("skip_reps"))),
                                    (self.skip_classes, classes, set(db.setting_list("skip_classes")))):
            lst.clear()
            for v in values:
                it = QListWidgetItem(v)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if v in chosen else Qt.Unchecked)
                lst.addItem(it)
        self.perm.clear()
        for c in custs:
            if c.get("perm_exclude"):
                it = QListWidgetItem(f"{c['code']} — {c['name']} — {c.get('perm_reason') or ''}")
                it.setData(Qt.UserRole, c["code"])
                self.perm.addItem(it)

    def save_exclusions(self):
        if not self.win.can_edit():
            return
        import json

        def checked(lst):
            return [lst.item(i).text() for i in range(lst.count()) if lst.item(i).checkState() == Qt.Checked]
        db = self.win.db
        db.set_setting("skip_reps", json.dumps(checked(self.skip_reps), ensure_ascii=False))
        db.set_setting("skip_classes", json.dumps(checked(self.skip_classes), ensure_ascii=False))
        db.log("تعديل الاستثناءات")
        info(self, "تم حفظ الاستثناءات — تُطبق عند رفع تقرير الأعمار القادم.")

    def remove_perm(self):
        it = self.perm.currentItem()
        if not it or not self.win.can_edit():
            return
        c = self.win.db.customer(it.data(Qt.UserRole))
        c.update(perm_exclude=0, perm_reason="")
        self.win.db.save_customer(c)
        self.win.db.log("إلغاء استثناء دائم", "", code=c["code"])
        self.load_exclusions()

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
            self.win.db.set_setting("mail_cc", self.cc.text().strip())
            self.win.db.set_setting("confirm_days", self.confirm_days.value())
            self.win.db.set_setting("direct_subject", self.d_subject.text())
            self.win.db.set_setting("direct_body", self.d_body.toPlainText())
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
