"""«النماذج»: edit the letter templates at any time, the serial format, the letterhead, stamp and signature."""
import os
import re
import tempfile
from datetime import date

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QPixmap, QTextCharFormat, QTextCursor, QTextTableFormat
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QPushButton, QSpinBox, QSplitter, QTabWidget, QTextEdit,
                               QToolButton, QVBoxLayout, QWidget)

from .. import letters as L
from .. import stages
from .. import templates as T
from .widgets import ask, error, info, warn

BODY = re.compile(r"<body[^>]*>(.*)</body>", re.S)
IMAGES = [("logo.png", "الشعار (أعلى يسار الخطاب والعلامة المائية)"), ("stamp.png", "الختم — يظهر مكان {الختم}"),
          ("signature.png", "التوقيع — يظهر مكان {التوقيع}")]


class TemplatesPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.kind = None
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)

        # ---- editor
        w = QWidget()
        h = QHBoxLayout(w)
        split = QSplitter()
        h.addWidget(split)
        self.list = QListWidget()
        self.list.setMaximumWidth(330)
        for k in T.KINDS:
            self.list.addItem(T.TITLES[k])
        self.list.currentRowChanged.connect(self._select)
        split.addWidget(self.list)
        right = QWidget()
        v = QVBoxLayout(right)
        form = QFormLayout()
        self.serial = QLineEdit()
        self.serial.setToolTip("{رقم} = الرقم التسلسلي بأربع خانات، {السنة} = السنة")
        self.counter = QSpinBox()
        self.counter.setRange(0, 999999)
        self.counter.setToolTip("آخر رقم مستخدم — الخطاب القادم يأخذ الرقم التالي. عدّله لو كنت بدأت الترقيم ورقيًا.")
        row = QHBoxLayout()
        row.addWidget(self.serial, 2)
        row.addWidget(QLabel("آخر رقم مستخدم:"))
        row.addWidget(self.counter)
        form.addRow("صيغة رقم الخطاب:", row)
        self.example = QLabel()
        self.example.setStyleSheet("color:#475467;")
        form.addRow("", self.example)
        self.serial.textChanged.connect(self._example)
        self.counter.valueChanged.connect(self._example)
        v.addLayout(form)

        tb = QHBoxLayout()
        for text, fn, tip in (("B", self._bold, "عريض"), ("I", self._italic, "مائل"), ("U", self._underline, "تسطير"),
                              ("⇶", lambda: self._align(Qt.AlignRight), "محاذاة يمين"),
                              ("☰", lambda: self._align(Qt.AlignHCenter), "توسيط"),
                              ("⇇", lambda: self._align(Qt.AlignLeft), "محاذاة يسار"),
                              ("≣", lambda: self._align(Qt.AlignJustify), "ضبط")):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            tb.addWidget(b)
        self.size = QComboBox()
        self.size.addItems(["10", "11", "12", "13", "14", "16", "18", "20"])
        self.size.setCurrentText("13")
        self.size.activated.connect(lambda: self._size(float(self.size.currentText())))
        tb.addWidget(QLabel("الحجم:"))
        tb.addWidget(self.size)
        self.field = QComboBox()
        self.field.addItem("➕ إدراج حقل...", None)
        for k, label in T.FIELDS.items():
            self.field.addItem(f"{label}  {{{k}}}", k)
        self.field.activated.connect(self._insert_field)
        tb.addWidget(self.field, 1)
        b = QPushButton("جدول (اسم/قيمة)")
        b.setToolTip("يدرج جدول من عمودين: العنوان يمين والقيمة يسار")
        b.clicked.connect(self._insert_table)
        tb.addWidget(b)
        v.addLayout(tb)
        self.editor = QTextEdit()
        self.editor.setLayoutDirection(Qt.RightToLeft)
        self.editor.setAcceptRichText(True)
        f = QFont("Arial")
        f.setPointSize(12)
        self.editor.setFont(f)
        v.addWidget(self.editor, 1)
        hint = QLabel("الحقول بين { } تُستبدل تلقائيًا ببيانات العميل عند الإصدار. الشعار واسم الشركة يُضافان أعلى كل "
                      "صفحة تلقائيًا. في الجداول: العمود الأخير يظهر على اليمين.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475467;")
        v.addWidget(hint)
        bar = QHBoxLayout()
        for text, fn in (("💾 حفظ النموذج", self.save), ("👁 معاينة PDF", self.preview),
                         ("↩ استرجاع النص الأصلي", self.reset)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        self.state = QLabel()
        bar.addWidget(self.state)
        v.addLayout(bar)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        tabs.addTab(w, "تعديل النماذج")

        # ---- letter data & images
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("بيانات تظهر في الخطابات")
        f = QFormLayout(g)
        self.company = QLineEdit()
        self.company_cr = QLineEdit()
        self.mobile = QLineEdit()
        self.email = QLineEdit()
        self.footer = QLineEdit()
        self.footer.setPlaceholderText("مثال: العنوان — الهاتف — الموقع (اختياري، يظهر أسفل كل صفحة)")
        self.unmatched = QCheckBox("إصدار خطاب الإدارة المالية لمن لم يطابق حتى لو سدد النسبة")
        f.addRow("اسم الشركة:", self.company)
        f.addRow("السجل التجاري للشركة:", self.company_cr)
        f.addRow("جوال/واتساب التواصل {جوال_التواصل}:", self.mobile)
        f.addRow("إيميل التواصل {ايميل_التواصل}:", self.email)
        f.addRow("تذييل الصفحة:", self.footer)
        f.addRow(self.unmatched)
        b = QPushButton("💾 حفظ")
        b.clicked.connect(self.save_data)
        f.addRow(b)
        v.addWidget(g)
        g = QGroupBox("الصور (PNG بخلفية شفافة أفضل)")
        grid = QVBoxLayout(g)
        self.thumbs = {}
        for name, label in IMAGES:
            row = QHBoxLayout()
            thumb = QLabel()
            thumb.setFixedSize(160, 90)
            thumb.setStyleSheet("border:1px solid #d0d5dd; background:white;")
            thumb.setAlignment(Qt.AlignCenter)
            self.thumbs[name] = thumb
            row.addWidget(thumb)
            row.addWidget(QLabel(label), 1)
            b1 = QPushButton("اختيار صورة")
            b1.clicked.connect(lambda _=None, n=name: self.pick_image(n))
            b2 = QPushButton("حذف")
            b2.clicked.connect(lambda _=None, n=name: self.remove_image(n))
            row.addWidget(b1)
            row.addWidget(b2)
            grid.addLayout(row)
        v.addWidget(g)
        g = QGroupBox("ورق الخطابات (الترويسة والتذييل) — صفحة A4 كاملة تظهر خلف كل النماذج")
        row = QHBoxLayout(g)
        self.paper = QLabel()
        self.paper.setFixedSize(90, 127)
        self.paper.setStyleSheet("border:1px solid #d0d5dd; background:white;")
        self.paper.setAlignment(Qt.AlignCenter)
        row.addWidget(self.paper)
        col = QVBoxLayout()
        note = QLabel("اختر ملف PDF أو صورة للورق الرسمي (مثل الورق المطبوع بالشعار والعنوان). عند وجوده يحل محل "
                      "الشعار واسم الشركة وتذييل الصفحة. حدد أين يبدأ النص وأين ينتهي حتى لا يغطي الترويسة أو التذييل.")
        note.setWordWrap(True)
        col.addWidget(note)
        form = QHBoxLayout()
        self.top_mm = QSpinBox()
        self.top_mm.setRange(10, 120)
        self.top_mm.setSuffix(" مم")
        self.bottom_mm = QSpinBox()
        self.bottom_mm.setRange(5, 100)
        self.bottom_mm.setSuffix(" مم")
        form.addWidget(QLabel("بداية النص من أعلى الصفحة:"))
        form.addWidget(self.top_mm)
        form.addWidget(QLabel("ونهايته قبل أسفل الصفحة بـ:"))
        form.addWidget(self.bottom_mm)
        form.addStretch()
        col.addLayout(form)
        btns = QHBoxLayout()
        for text, fn in (("اختيار ملف الورق (PDF أو صورة)", self.pick_paper), ("حذف", self.remove_paper),
                         ("💾 حفظ المسافات", self.save_paper), ("👁 معاينة على خطاب", self.preview_paper)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch()
        col.addLayout(btns)
        row.addLayout(col, 1)
        v.addWidget(g)
        v.addStretch()
        tabs.addTab(w, "بيانات الخطابات والختم والتوقيع")

    # ---------------------------------------------------------------- load
    def load(self):
        db = self.win.db
        self.company.setText(db.setting("company"))
        self.company_cr.setText(db.setting("company_cr"))
        self.mobile.setText(db.setting("contact_mobile"))
        self.email.setText(db.setting("contact_email"))
        self.footer.setText(db.setting("letter_footer"))
        self.unmatched.setChecked(db.setting("letter_unmatched") == "1")
        for name, _ in IMAGES:
            p = self.win.folder.asset(name)
            if not os.path.exists(p) and name == "logo.png":
                p = os.path.join(L.RES, "logo.png")
            pix = QPixmap(p) if os.path.exists(p) else QPixmap()
            self.thumbs[name].setPixmap(pix.scaled(150, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                        if not pix.isNull() else QPixmap())
            if pix.isNull():
                self.thumbs[name].setText("لا توجد صورة")
        self.top_mm.setValue(int(db.setting_num("letterhead_top")))
        self.bottom_mm.setValue(int(db.setting_num("letterhead_bottom")))
        p = self.win.folder.asset(stages.LETTERHEAD)
        pix = QPixmap(p) if os.path.exists(p) else QPixmap()
        if pix.isNull():
            self.paper.setPixmap(QPixmap())
            self.paper.setText("بدون\n(الترويسة\nالحالية)")
        else:
            self.paper.setPixmap(pix.scaled(88, 125, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        else:
            self._select(self.list.currentRow())

    def _select(self, i):
        if i < 0:
            return
        self.kind = T.KINDS[i]
        tpl = self.win.db.template(self.kind)
        self.editor.setHtml(f'<html><body dir="rtl">{tpl["html"]}</body></html>')
        L.make_rtl(self.editor.document())
        self.serial.setText(tpl["serial_format"])
        self.counter.setValue(self.win.db.serial_counter(self.kind))
        self.state.setText("✏ نموذج معدّل" if tpl["custom"] else "النص الأصلي")
        self._example()

    def _example(self):
        fmt = self.serial.text()
        n = self.counter.value() + 1
        ex = fmt.replace("{رقم}", f"{n:04d}").replace("{السنة}", date.today().strftime("%Y"))
        self.example.setText(f"الخطاب القادم سيأخذ الرقم: {ex if ex != fmt else fmt + f'-{n:04d}'}"
                             + ("   (النوعان 1004 يشتركان في نفس الترقيم)" if self.kind in ("1004", "1004PN") else ""))

    # ---------------------------------------------------------------- formatting
    def _merge(self, fmt):
        cur = self.editor.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.WordUnderCursor)
        cur.mergeCharFormat(fmt)
        self.editor.mergeCurrentCharFormat(fmt)

    def _bold(self):
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Normal if self.editor.fontWeight() > QFont.Normal else QFont.Bold)
        self._merge(fmt)

    def _italic(self):
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.editor.fontItalic())
        self._merge(fmt)

    def _underline(self):
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.editor.fontUnderline())
        self._merge(fmt)

    def _size(self, pt):
        fmt = QTextCharFormat()
        fmt.setFontPointSize(pt)
        self._merge(fmt)

    def _align(self, a):
        self.editor.setAlignment(a | Qt.AlignAbsolute)

    def _insert_field(self):
        k = self.field.currentData()
        if k:
            self.editor.textCursor().insertText(f"{{{k}}}")
        self.field.setCurrentIndex(0)
        self.editor.setFocus()

    def _insert_table(self):
        fmt = QTextTableFormat()
        fmt.setBorder(1)
        fmt.setCellPadding(5)
        fmt.setCellSpacing(0)
        fmt.setWidth(self.editor.document().textWidth() * 0.95)
        table = self.editor.textCursor().insertTable(2, 2, fmt)
        table.cellAt(0, 1).firstCursorPosition().insertText("العنوان")
        table.cellAt(0, 0).firstCursorPosition().insertText("{اسم_العميل}")
        table.cellAt(1, 1).firstCursorPosition().insertText("العنوان")
        table.cellAt(1, 0).firstCursorPosition().insertText("{المبلغ}")
        L.make_rtl(self.editor.document())

    # ---------------------------------------------------------------- actions
    def body_html(self):
        m = BODY.search(self.editor.toHtml())
        return m.group(1).strip() if m else self.editor.toHtml()

    def save(self):
        if not self.win.can_edit() or not self.kind:
            return
        fmt = self.serial.text().strip()
        if not fmt:
            warn(self, "اكتب صيغة رقم الخطاب، مثل RE-SL-26-1003-{رقم}")
            return
        db = self.win.db
        db.save_template(self.kind, self.body_html(), fmt)
        if self.counter.value() != db.serial_counter(self.kind):
            if self.counter.value() < db.serial_counter(self.kind) and not ask(
                    self, "رقم العداد أقل من آخر رقم مستخدم — قد يتكرر رقم خطاب. متأكد؟"):
                return
            db.set_serial_counter(self.kind, self.counter.value())
        db.log("تعديل نموذج", T.TITLES[self.kind])
        self.state.setText("✏ نموذج معدّل — محفوظ")
        info(self, "تم حفظ النموذج. الخطابات القادمة تُصدر بالنص الجديد (الخطابات الصادرة لا تتغير).")

    def reset(self):
        if not self.win.can_edit() or not self.kind:
            return
        if ask(self, "استرجاع النص الأصلي لهذا النموذج؟ سيضيع تعديلك عليه."):
            self.win.db.reset_template(self.kind)
            self.win.db.log("استرجاع نموذج أصلي", T.TITLES[self.kind])
            self._select(self.list.currentRow())

    def preview(self):
        if not self.kind:
            return
        db = self.win.db
        cust = {"code": "18010000", "name": "مؤسسة مثال للتجارة", "cr_no": "4030000000", "rep_name": "اسم المندوب",
                "pn_no": "123456", "pn_value": 100000.0, "pn_date": date.today().isoformat()}
        extra = {"الممثل": "اسم الممثل", "الصفة": "المالك", "رقم_الهوية": "1000000000", "خيار_الأقساط": "✔",
                 "خيار_النقدي": "  "}
        for i in range(4):
            extra[f"القسط{i + 1}_مبلغ"] = "2,500.00"
            extra[f"القسط{i + 1}_تاريخ"] = "__/__/2026"
        values = L.letter_values(db, cust, 10000.0, "RE-SL-26-XXXX-0000 (معاينة)", date.today().isoformat(),
                                 {"serial": "RE-SL-26-1003-0000", "date": date.today().isoformat()}, extra)
        body = L.merge(self.body_html(), values, stages.images(self.win.folder))
        out = os.path.join(tempfile.gettempdir(), f"معاينة {self.kind}.pdf")
        try:
            L.write_pdf([body], out, stages.letterhead(db, self.win.folder), "معاينة")
        except Exception as e:  # noqa: BLE001
            error(self, f"تعذر إنشاء المعاينة:\n{e}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def save_data(self):
        if not self.win.can_edit():
            return
        db = self.win.db
        for key, wdg in (("company", self.company), ("company_cr", self.company_cr), ("contact_mobile", self.mobile),
                         ("contact_email", self.email), ("letter_footer", self.footer)):
            db.set_setting(key, wdg.text().strip())
        db.set_setting("letter_unmatched", "1" if self.unmatched.isChecked() else "0")
        db.log("تعديل بيانات الخطابات")
        info(self, "تم الحفظ.")

    def pick_image(self, name):
        if not self.win.can_edit():
            return
        path, _ = QFileDialog.getOpenFileName(self, "اختيار صورة", os.path.expanduser("~"), "صور (*.png *.jpg *.jpeg)")
        if not path:
            return
        from PySide6.QtGui import QImage
        img = QImage(path)
        if img.isNull():
            error(self, "تعذر فتح الصورة.")
            return
        img.save(self.win.folder.asset(name), "PNG")
        self.win.db.log("تغيير صورة", name)
        self.load()

    def pick_paper(self):
        if not self.win.can_edit():
            return
        path, _ = QFileDialog.getOpenFileName(self, "ورق الخطابات", os.path.expanduser("~"),
                                              "PDF أو صورة (*.pdf *.png *.jpg *.jpeg)")
        if not path:
            return
        img = L.page_image(path)
        if img.isNull():
            error(self, "تعذر فتح الملف.")
            return
        img.save(self.win.folder.asset(stages.LETTERHEAD), "PNG")
        self.win.db.log("تغيير ورق الخطابات", os.path.basename(path))
        self.load()
        self.preview_paper()

    def remove_paper(self):
        if not self.win.can_edit():
            return
        p = self.win.folder.asset(stages.LETTERHEAD)
        if os.path.exists(p) and ask(self, "حذف ورق الخطابات والرجوع للترويسة السابقة (الشعار واسم الشركة)؟"):
            os.remove(p)
            self.win.db.log("حذف ورق الخطابات")
            self.load()

    def save_paper(self):
        if not self.win.can_edit():
            return
        self.win.db.set_setting("letterhead_top", self.top_mm.value())
        self.win.db.set_setting("letterhead_bottom", self.bottom_mm.value())
        info(self, "تم حفظ المسافات.")

    def preview_paper(self):
        """The finance letter on the letter paper, with sample values."""
        db = self.win.db
        db.set_setting("letterhead_top", self.top_mm.value())
        db.set_setting("letterhead_bottom", self.bottom_mm.value())
        sample = {"code": "00000000", "name": "عميل تجريبي", "cr_no": "0000000000", "rep_name": "مندوب تجريبي"}
        values = L.letter_values(db, sample, 12345.5, "معاينة", date.today().isoformat())
        body = L.merge(db.template("1003")["html"], values, stages.images(self.win.folder))
        out = os.path.join(tempfile.gettempdir(), "معاينة ورق الخطابات.pdf")
        try:
            L.write_pdf([body], out, stages.letterhead(db, self.win.folder), "معاينة")
        except Exception as e:  # noqa: BLE001
            error(self, f"تعذر إنشاء المعاينة:\n{e}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def remove_image(self, name):
        if not self.win.can_edit():
            return
        p = self.win.folder.asset(name)
        if os.path.exists(p) and ask(self, "حذف الصورة؟"):
            os.remove(p)
            self.load()
