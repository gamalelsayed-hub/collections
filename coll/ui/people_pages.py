"""Customers, reps and activity-log screens."""
import os

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTabWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import attachments as A
from .. import reps as R
from .widgets import NAVY, ask, error, info, money, month_label, ro, styled_table, warn


# ================================================================== customers
class CustomerDialog(QDialog):
    def __init__(self, win, code):
        super().__init__(win)
        self.win = win
        db = win.db
        self.c = db.customer(code) or {"code": code, "name": ""}
        self.setWindowTitle(f"العميل {code} — {self.c.get('name', '')}")
        self.resize(900, 640)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)
        w = QWidget()
        f = QFormLayout(w)
        self.fields = {}
        for key, label in (("name", "اسم العميل"), ("cr_no", "السجل التجاري"), ("vat_no", "الرقم الضريبي"),
                           ("address", "العنوان الوطني المختصر"), ("phone", "الجوال / الهاتف 1"),
                           ("phone2", "الهاتف 2"), ("email", "الإيميل الرسمي للعميل"), ("region", "المنطقة"),
                           ("branch", "الفرع"), ("rep_name", "المندوب"), ("ctype", "النوع"), ("cls", "التصنيف")):
            e = QLineEdit(str(self.c.get(key) or ""))
            self.fields[key] = e
            f.addRow(label + ":", e)
        self.has_pn = QCheckBox("العميل عنده سند لأمر")
        self.has_pn.setChecked(bool(self.c.get("has_pn")))
        f.addRow(self.has_pn)
        self.pn_no = QLineEdit(str(self.c.get("pn_no") or ""))
        self.pn_value = QDoubleSpinBox()
        self.pn_value.setRange(0, 1e12)
        self.pn_value.setDecimals(2)
        self.pn_value.setGroupSeparatorShown(True)
        self.pn_value.setValue(float(self.c.get("pn_value") or 0))
        self.pn_date = QLineEdit(str(self.c.get("pn_date") or ""))
        f.addRow("رقم السند لأمر:", self.pn_no)
        f.addRow("قيمة السند لأمر:", self.pn_value)
        f.addRow("تاريخ السند لأمر:", self.pn_date)
        self.notes = QPlainTextEdit(str(self.c.get("notes") or ""))
        self.notes.setMaximumHeight(80)
        f.addRow("ملاحظات:", self.notes)
        self.perm = QCheckBox("استثناء دائم — لا يدخل أي دورة مطابقة ولا تصدر له خطابات")
        self.perm.setChecked(bool(self.c.get("perm_exclude")))
        self.perm_reason = QLineEdit(str(self.c.get("perm_reason") or ""))
        self.perm_reason.setPlaceholderText("سبب الاستثناء (مثل: عميل شقيق، جهة حكومية...)")
        f.addRow(self.perm)
        f.addRow("سبب الاستثناء:", self.perm_reason)
        tabs.addTab(w, "البيانات")
        tabs.addTab(self._files_tab(), "المرفقات")
        self.files_tab_index = tabs.count() - 1
        self.tabs = tabs
        hist = styled_table(["الدورة", "الحالة", "الرصيد", "المتأخر", "المسدد", "النسبة", "رصيد الكشف", "التنبيهات"])
        rows = []
        for cyc in db.cycles():
            for cc in db.cycle_customers(cyc["id"]):
                if cc["code"] == code:
                    rows.append((cyc["month"], cc))
        hist.setRowCount(len(rows))
        for i, (m, cc) in enumerate(rows):
            for col, v in enumerate((month_label(m), cc["status"] or ("مطلوب مطابقة" if cc["required"] else "—"))):
                hist.setItem(i, col, ro(v))
            for col, v in ((2, cc["balance"]), (3, cc["overdue"]), (4, cc["paid"] or 0), (6, cc["stmt_balance"])):
                hist.setItem(i, col, ro(money(v), True))
            hist.setItem(i, 5, ro(f"{(cc['pct'] or 0) * 100:.0f}%", True))
            hist.setItem(i, 7, ro(" | ".join(x for x in (cc["warning"], cc["exclude_reason"], cc["carried"]) if x)))
        hist.resizeColumnsToContents()
        tabs.addTab(hist, "المراحل والدورات")
        lets = styled_table(["رقم الخطاب", "النوع", "التاريخ", "المبلغ", "الحالة"])
        from ..stages import KIND_NAMES
        ls = db.letters(code=code)
        lets.setRowCount(len(ls))
        for i, l in enumerate(ls):
            for col, v in enumerate((l["serial"], KIND_NAMES.get(l["kind"], l["kind"]), l["date"], money(l["amount"]),
                                     l["status"] + (f" — {l['cancel_reason']}" if l["cancel_reason"] else ""))):
                lets.setItem(i, col, ro(v, col == 3))
        lets.resizeColumnsToContents()
        tabs.addTab(lets, f"الخطابات ({len(ls)})")
        log = styled_table(["الوقت", "المستخدم", "العملية", "التفاصيل"])
        ev = db.events(code=code)
        log.setRowCount(len(ev))
        for i, e in enumerate(ev):
            for col, k in enumerate(("ts", "user", "kind", "detail")):
                log.setItem(i, col, ro(e[k]))
        log.resizeColumnsToContents()
        tabs.addTab(log, "سجل العميل")
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Save).setText("حفظ")
        bb.button(QDialogButtonBox.Close).setText("إغلاق")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Save).setEnabled(not win.readonly)
        lay.addWidget(bb)

    # -------- attachments
    def _files_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.missing_lbl = QLabel()
        self.missing_lbl.setWordWrap(True)
        v.addWidget(self.missing_lbl)
        bar = QHBoxLayout()
        self.file_kind = QComboBox()
        for k, label in A.KINDS:
            self.file_kind.addItem(label, k)
        bar.addWidget(QLabel("نوع المستند:"))
        bar.addWidget(self.file_kind)
        for text, fn in (("📎 إرفاق ملف", self.attach), ("👁 فتح", self.open_file), ("🗑 حذف", self.delete_file)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            b.setEnabled(text.startswith("👁") or not self.win.readonly)
            bar.addWidget(b)
        bar.addStretch()
        v.addLayout(bar)
        self.files = styled_table(["المستند", "اسم الملف", "تاريخ الإرفاق", "بواسطة"])
        self.files.doubleClicked.connect(lambda *_: self.open_file())
        v.addWidget(self.files, 1)
        self.fill_files()
        return w

    def fill_files(self):
        recs = self.win.db.customer_files(self.c["code"])
        self.file_recs = recs
        t = self.files
        t.setRowCount(len(recs))
        for i, r in enumerate(recs):
            for col, val in enumerate((A.KIND_NAMES.get(r["kind"], r["kind"]), r["name"], r["uploaded"][:16], r["user"])):
                t.setItem(i, col, ro(val))
        t.resizeColumnsToContents()
        miss = A.missing(self.win.db, {**self.c, "has_pn": self.has_pn.isChecked()}, recs)
        self.missing_lbl.setText("✓ كل المستندات الأساسية مرفقة." if not miss else
                                 "⚠ ناقص: " + "، ".join(A.KIND_NAMES[k] for k in miss))
        self.missing_lbl.setStyleSheet(f"color:{'#067647' if not miss else '#b54708'}; font-weight:600;")
        if hasattr(self, "tabs"):
            self.tabs.setTabText(self.files_tab_index, f"المرفقات ({len(recs)})")

    def attach(self):
        start = QSettings().value("attach_dir", os.path.expanduser("~"))
        paths, _ = QFileDialog.getOpenFileNames(self, f"إرفاق: {self.file_kind.currentText()}", start,
                                                "مستندات (*.pdf *.png *.jpg *.jpeg *.doc *.docx *.xls *.xlsx);;كل الملفات (*)")
        if not paths:
            return
        QSettings().setValue("attach_dir", os.path.dirname(paths[0]))
        try:
            for p in paths:
                A.add(self.win.db, self.win.folder, self.c["code"], self.file_kind.currentData(), p)
        except OSError as e:
            error(self, f"تعذر نسخ الملف:\n{e}")
        self.fill_files()

    def _current_file(self):
        r = self.files.currentRow()
        return self.file_recs[r] if 0 <= r < len(self.file_recs) else None

    def open_file(self):
        rec = self._current_file()
        if not rec:
            return
        p = A.full_path(self.win.folder, rec)
        if not os.path.exists(p):
            error(self, "الملف غير موجود في فولدر البيانات (ربما لم تكتمل مزامنة الدرايف بعد).")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def delete_file(self):
        rec = self._current_file()
        if rec and ask(self, f"حذف «{A.KIND_NAMES.get(rec['kind'], rec['kind'])}: {rec['name']}»؟"):
            A.remove(self.win.db, self.win.folder, rec)
            self.fill_files()

    def save(self):
        c = dict(self.c)
        for k, e in self.fields.items():
            c[k] = e.text().strip()
        c["has_pn"] = 1 if self.has_pn.isChecked() else 0
        c["pn_no"] = self.pn_no.text().strip()
        c["pn_value"] = self.pn_value.value() or None
        c["pn_date"] = self.pn_date.text().strip()
        c["notes"] = self.notes.toPlainText().strip()
        if self.perm.isChecked() and not self.perm_reason.text().strip():
            warn(self, "اكتب سبب الاستثناء الدائم.")
            return
        if bool(self.perm.isChecked()) != bool(self.c.get("perm_exclude")):
            self.win.db.log("استثناء دائم" if self.perm.isChecked() else "إلغاء استثناء دائم",
                            self.perm_reason.text().strip(), code=c["code"])
        c["perm_exclude"] = 1 if self.perm.isChecked() else 0
        c["perm_reason"] = self.perm_reason.text().strip() if self.perm.isChecked() else ""
        self.win.db.save_customer(c)
        self.win.db.log("تعديل بيانات عميل", code=c["code"])
        self.accept()


class CustomersPage(QWidget):
    COLS = ["رقم العميل", "اسم العميل", "المندوب", "الفرع", "النوع", "السجل التجاري", "الجوال", "سند لأمر",
            "قيمة السند", "الإيميل", "المرفقات"]

    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث بالاسم أو الرقم...")
        self.search.textChanged.connect(self.fill)
        self.f_rep = QComboBox()
        self.f_rep.currentIndexChanged.connect(self.fill)
        self.only_missing = QCheckBox("بيانات ناقصة (سجل تجاري)")
        self.only_missing.toggled.connect(self.fill)
        for w_ in (self.search,):
            bar.addWidget(w_, 2)
        bar.addWidget(QLabel("المندوب:"))
        bar.addWidget(self.f_rep, 1)
        bar.addWidget(self.only_missing)
        imp = QPushButton("📥 استيراد بيانات العملاء من Excel")
        imp.clicked.connect(self.import_excel)
        bar.addWidget(imp)
        lay.addLayout(bar)
        self.summary = QLabel()
        self.summary.setStyleSheet(f"color:{NAVY}; font-weight:700;")
        lay.addWidget(self.summary)
        self.table = styled_table(self.COLS)
        self.table.doubleClicked.connect(lambda idx: self.win.open_customer(self.table.item(idx.row(), 0).text()))
        lay.addWidget(self.table, 1)
        lay.addWidget(QLabel("ضغطتين على العميل لفتح بياناته (السجل التجاري، السند لأمر) وتاريخ مراحله."))

    def load(self):
        self.all = sorted(self.win.db.customers().values(), key=lambda c: c["code"])
        self.files_by_code = {}
        for f in self.win.db.customer_files():
            self.files_by_code.setdefault(f["code"], []).append(f)
        cur = self.f_rep.currentText()
        self.f_rep.blockSignals(True)
        self.f_rep.clear()
        self.f_rep.addItems(["الكل"] + sorted({c["rep_name"] or "—" for c in self.all}))
        self.f_rep.setCurrentIndex(max(0, self.f_rep.findText(cur)))
        self.f_rep.blockSignals(False)
        self.fill()

    def fill(self):
        q = self.search.text().strip()
        rep = self.f_rep.currentText()
        vis = [c for c in getattr(self, "all", [])
               if (not q or q in (c["name"] or "") or q in c["code"])
               and (rep in ("", "الكل") or (c["rep_name"] or "—") == rep)
               and (not self.only_missing.isChecked() or not c["cr_no"])]
        t = self.table
        t.setRowCount(len(vis))
        for i, c in enumerate(vis):
            vals = [c["code"], c["name"], c["rep_name"], c["branch"], c["ctype"], c["cr_no"], c["phone"],
                    "نعم" if c["has_pn"] else "لا"]
            for col, v in enumerate(vals):
                t.setItem(i, col, ro(v))
            t.setItem(i, 8, ro(money(c["pn_value"]) if c["pn_value"] else "", True))
            t.setItem(i, 9, ro(c.get("email") or ""))
            files = self.files_by_code.get(c["code"], [])
            miss = A.missing(self.win.db, c, files)
            it = ro(f"{len(files)} ملف" + (f" — ناقص {len(miss)}" if miss else " ✓") if files else "—")
            if files:
                it.setToolTip("ناقص: " + "، ".join(A.KIND_NAMES[k] for k in miss) if miss else "كل المستندات الأساسية")
            t.setItem(i, 10, it)
        t.resizeColumnsToContents()
        t.setColumnWidth(1, min(t.columnWidth(1), 340))
        self.summary.setText(f"العملاء: {len(vis)} من {len(getattr(self, 'all', []))}   |   بدون سجل تجاري: "
                             f"{sum(1 for c in vis if not c['cr_no'])}   |   عندهم سند لأمر: "
                             f"{sum(1 for c in vis if c['has_pn'])}")

    def import_excel(self):
        """Excel with رقم العميل + any of: اسم العميل، المندوب، الفرع، النوع، السجل التجاري، الجوال، الإيميل،
        سند لأمر (نعم/لا أو رقم السند نفسه)، رقم السند، قيمة السند، تاريخ السند. New customers are added."""
        if not self.win.can_edit():
            return
        from ..aging import read_table
        from ..db import CUSTOMER_FIELDS
        from ..textutil import code_text, to_number
        path, _ = QFileDialog.getOpenFileName(self, "ملف بيانات العملاء", QSettings().value("last_dir", ""),
                                              "Excel (*.xlsx *.xlsm)")
        if not path:
            return
        rows = read_table(path)
        heads = {"code": ("رقم العميل", "كود العميل"), "name": ("اسم العميل",), "rep_name": ("المندوب",),
                 "branch": ("الفرع",), "region": ("المنطقة",), "ctype": ("نوع العميل", "النوع"),
                 "cr_no": ("السجل",), "phone": ("الجوال", "الهاتف"), "email": ("الإيميل", "الايميل", "البريد"),
                 "pn_no": ("رقم السند",), "pn_value": ("قيمة السند",), "pn_date": ("تاريخ السند",),
                 "has_pn": ("سند لأمر", "سند لامر", "سند امر")}
        cols, first = {}, None
        for i, r in enumerate(rows[:15]):
            cells = [str(v or "").strip() for v in r]
            found = {}
            for k, words in heads.items():
                for c, txt in enumerate(cells):
                    if c not in found.values() and any(w in txt for w in words):
                        found[k] = c
                        break
            if "code" in found and len(found) >= 2:
                cols, first = found, i + 1
                break
        if not cols:
            warn(self, "لم أجد عمود «رقم العميل» ومعه عمود بيانات (السجل التجاري، الجوال، سند لأمر، قيمة السند...).")
            return
        db = self.win.db
        existing = db.customers()
        added, seen = 0, {}

        def text(v):
            return code_text(v) if isinstance(v, (int, float)) else str(v).strip()
        for r in rows[first:]:
            code = code_text(r[cols["code"]])
            if not code or not any(ch.isdigit() for ch in code):
                continue
            c = existing.get(code)
            if c is None:
                c = {f: "" for f in CUSTOMER_FIELDS}
                c.update(code=code, has_pn=0, pn_value=None)
                added += 1
            for k, col in cols.items():
                v = r[col]
                if k == "code" or v in (None, ""):
                    continue
                if k == "pn_value":
                    c[k] = to_number(v)
                elif k == "has_pn":
                    t = text(v)
                    if t in ("نعم", "1", "yes", "Yes", "✓", "True", "موجود"):
                        c["has_pn"] = 1
                    elif t in ("0", "لا", "no", "No", "False", "-", "—", "لايوجد", "لا يوجد"):
                        c["has_pn"] = 0
                    else:   # the column holds the note number itself
                        c["has_pn"] = 1
                        if "pn_no" not in cols or not r[cols["pn_no"]]:
                            c["pn_no"] = t
                else:
                    c[k] = text(v)
            if c.get("pn_value") and "has_pn" not in cols:
                c["has_pn"] = 1
            existing[code] = c
            db.save_customer(c)
            seen[code] = c
        n = len(seen)
        pn = sum(1 for c in seen.values() if c.get("has_pn"))
        db.log("استيراد بيانات العملاء", f"{os.path.basename(path)}: {n} عميل، {added} جديد")
        self.load()
        info(self, f"تم استيراد {n} عميل ({added} جديد، {n - added} تحديث)، منهم {pn} عليهم سند لأمر.")


# ================================================================== reps
class RepsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        h = QLabel("① قائمة المناديب وإيميلاتهم.   ② ربط أسماء المناديب كما تظهر في تقرير الأعمار وكشوف العهدة "
                   "بالمندوب الصحيح (مرة واحدة — البرنامج يفتكرها).")
        h.setWordWrap(True)
        h.setStyleSheet("padding:6px; background:#eef4fb; border-radius:6px;")
        lay.addWidget(h)
        tabs = QTabWidget()
        lay.addWidget(tabs)
        w1 = QWidget()
        v1 = QVBoxLayout(w1)
        self.reps = styled_table(["الاسم", "رقم الموظف", "الإيميل", "الفرع", "المسمى", "نشط"])
        self.reps.setEditTriggers(self.reps.EditTrigger.DoubleClicked | self.reps.EditTrigger.EditKeyPressed)
        v1.addWidget(self.reps)
        bar = QHBoxLayout()
        for text, fn in (("📥 استيراد من Excel", self.import_reps), ("＋ مندوب جديد", self.add_rep),
                         ("− حذف المحدد", self.delete_rep), ("💾 حفظ", self.save_reps)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        v1.addLayout(bar)
        tabs.addTab(w1, "المناديب")
        w2 = QWidget()
        v2 = QVBoxLayout(w2)
        self.alias = styled_table(["الاسم في تقرير الأعمار / الكشوف", "عدد العملاء", "المندوب"])
        v2.addWidget(self.alias)
        bar2 = QHBoxLayout()
        b = QPushButton("✨ اقتراح الربط تلقائيًا")
        b.clicked.connect(self.suggest)
        bar2.addWidget(b)
        b = QPushButton("💾 حفظ الربط")
        b.clicked.connect(self.save_alias)
        bar2.addWidget(b)
        bar2.addStretch()
        v2.addLayout(bar2)
        v2.addWidget(QLabel("الأسماء مثل «رئيسي» أو «عميل مورد» اربطها بالمسؤول عن متابعتهم، أو اتركها بدون ربط "
                            "فتُجمع كشوفهم في ملف «بدون مندوب»."))
        tabs.addTab(w2, "ربط الأسماء")

    def load(self):
        db = self.win.db
        reps = db.reps()
        t = self.reps
        t.setRowCount(len(reps))
        for i, r in enumerate(reps):
            for c, k in enumerate(("name", "emp_no", "email", "branch", "title")):
                it = QTableWidgetItem(str(r.get(k) or ""))
                it.setData(Qt.UserRole, r["id"])
                t.setItem(i, c, it)
            it = QTableWidgetItem("نعم" if r["active"] else "لا")
            t.setItem(i, 5, it)
        t.resizeColumnsToContents()
        names = {}
        for c in db.customers().values():
            if c["rep_name"]:
                names[c["rep_name"]] = names.get(c["rep_name"], 0) + 1
        aliases = db.aliases()
        a = self.alias
        a.setRowCount(len(names))
        for i, (n, cnt) in enumerate(sorted(names.items())):
            a.setItem(i, 0, ro(n))
            a.setItem(i, 1, ro(cnt, True))
            cb = QComboBox()
            cb.addItem("— بدون ربط —", None)
            for r in reps:
                cb.addItem(f"{r['name']}  ({r['email'] or 'بدون إيميل'})", r["id"])
            if n in aliases:
                cb.setCurrentIndex(max(0, cb.findData(aliases[n])))
            a.setCellWidget(i, 2, cb)
        a.resizeColumnsToContents()
        a.setColumnWidth(2, 420)

    def add_rep(self):
        t = self.reps
        t.insertRow(t.rowCount())
        t.setItem(t.rowCount() - 1, 5, QTableWidgetItem("نعم"))

    def delete_rep(self):
        if not self.win.can_edit():
            return
        rows = sorted({i.row() for i in self.reps.selectedIndexes()}, reverse=True)
        for r in rows:
            it = self.reps.item(r, 0)
            rid = it.data(Qt.UserRole) if it else None
            if rid and ask(self, f"حذف المندوب {it.text()}؟"):
                self.win.db.delete_rep(rid)
        self.load()

    def save_reps(self):
        if not self.win.can_edit():
            return
        t = self.reps
        for r in range(t.rowCount()):
            def val(c):
                it = t.item(r, c)
                return it.text().strip() if it else ""
            if not val(0):
                continue
            rid = t.item(r, 0).data(Qt.UserRole)
            self.win.db.save_rep({"id": rid, "name": val(0), "emp_no": val(1), "email": val(2).lower(),
                                  "branch": val(3), "title": val(4), "active": 0 if val(5) == "لا" else 1})
        self.win.db.log("تعديل المناديب")
        self.load()
        info(self, "تم الحفظ.")

    def import_reps(self):
        if not self.win.can_edit():
            return
        path, _ = QFileDialog.getOpenFileName(self, "ملف المناديب", QSettings().value("last_dir", ""),
                                              "Excel / CSV (*.xlsx *.xlsm *.csv)")
        if not path:
            return
        try:
            reps = R.import_reps(path)
        except Exception as e:  # noqa: BLE001
            error(self, str(e))
            return
        existing = {r["name"]: r for r in self.win.db.reps()}
        for r in reps:
            if r["name"] in existing:
                r["id"] = existing[r["name"]]["id"]
            self.win.db.save_rep(r)
        self.win.db.log("استيراد المناديب", f"{len(reps)} مندوب")
        self.load()
        n = self.suggest(silent=True)
        for i in range(self.alias.rowCount()):   # save the links right away
            self.win.db.set_alias(self.alias.item(i, 0).text(), self.alias.cellWidget(i, 2).currentData())
        missing = [self.alias.item(i, 0).text() for i in range(self.alias.rowCount())
                   if not self.alias.cellWidget(i, 2).currentData()]
        info(self, f"تم استيراد {len(reps)} مندوب وربط {n} اسم تلقائيًا."
             + (f"\n\nأسماء بدون ربط ({len(missing)}): {'، '.join(missing)}\nاربطها يدويًا من تبويب «ربط الأسماء» "
                "ثم اضغط «حفظ الربط»." if missing else ""))

    def suggest(self, silent=False):
        reps = self.win.db.reps()
        n = 0
        for i in range(self.alias.rowCount()):
            cb = self.alias.cellWidget(i, 2)
            if cb.currentData():
                continue
            s = R.suggest_rep(self.alias.item(i, 0).text(), reps)
            if s:
                cb.setCurrentIndex(cb.findData(s["id"]))
                n += 1
        if not silent:
            info(self, f"تم اقتراح {n} ربط — راجعها ثم اضغط «حفظ الربط».")
        return n

    def save_alias(self):
        if not self.win.can_edit():
            return
        for i in range(self.alias.rowCount()):
            self.win.db.set_alias(self.alias.item(i, 0).text(), self.alias.cellWidget(i, 2).currentData())
        self.win.db.log("ربط أسماء المناديب")
        info(self, "تم حفظ الربط.")


# ================================================================== log
class LogPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث في السجل (مستخدم، عملية، رقم عميل)...")
        self.search.textChanged.connect(self.fill)
        bar.addWidget(self.search)
        lay.addLayout(bar)
        self.table = styled_table(["الوقت", "المستخدم", "العملية", "رقم العميل", "التفاصيل"])
        lay.addWidget(self.table, 1)

    def load(self):
        self.events = self.win.db.events()
        self.fill()

    def fill(self):
        q = self.search.text().strip()
        ev = [e for e in getattr(self, "events", [])
              if not q or any(q in str(e[k] or "") for k in ("user", "kind", "code", "detail"))]
        t = self.table
        t.setRowCount(len(ev))
        for i, e in enumerate(ev):
            for c, k in enumerate(("ts", "user", "kind", "code", "detail")):
                t.setItem(i, c, ro(e[k]))
        t.resizeColumnsToContents()
