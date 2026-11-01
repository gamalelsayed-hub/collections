"""دورة المطابقات الشهرية — Day 1: aging report → statements → ZIP per rep → e-mail."""
import os
from datetime import date

from PySide6.QtCore import QSettings, QUrl, Qt
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMenu, QPushButton, QVBoxLayout, QWidget)

from .. import aging, day1, mailer
from .. import statements as ST
from ..reps import suggest_rep
from .mail_preview import MailPreviewDialog
from .widgets import (NAVY, STATUS_COLORS, ColumnMapDialog, MonthDialog, Progress, ask, color_item, error, info, money,
                      month_label, ro, styled_table, warn)

STAGES = [("day_statements", "يوم 1", "تجهيز الكشوف وإرسالها للمناديب"),
          ("day_finance", "يوم 7", "المطابقات + سندات القبض ← خطاب الإدارة المالية"),
          ("day_legal", "يوم 14/15", "سندات القبض ← خطاب الإدارة القانونية وإيقاف البيع"),
          ("day_action", "يوم 21/22", "سندات القبض ← التوجيه النهائي (قرار المدير)")]


def step_box(title):
    box = QFrame()
    box.setStyleSheet("QFrame#step { background:white; border:1px solid #e4e7ec; border-radius:8px; }")
    box.setObjectName("step")
    v = QVBoxLayout(box)
    t = QLabel(title)
    t.setStyleSheet(f"color:{NAVY}; font-size:11.5pt; font-weight:700;")
    v.addWidget(t)
    return box, v


class CyclePage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cycle = None
        self.packages = []
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("الدورة:"))
        self.cycle_box = QComboBox()
        self.cycle_box.setMinimumWidth(180)
        self.cycle_box.currentIndexChanged.connect(self._cycle_changed)
        top.addWidget(self.cycle_box)
        self.stages = QLabel()
        self.stages.setStyleSheet("color:#475467;")
        top.addWidget(self.stages, 1)
        lay.addLayout(top)

        steps = QHBoxLayout()
        b1, v1 = step_box("١) تقرير أعمار الديون")
        self.aging_info = QLabel("لم يُرفع بعد")
        self.aging_info.setWordWrap(True)
        v1.addWidget(self.aging_info)
        btn = QPushButton("📥 رفع تقرير الأعمار")
        btn.clicked.connect(self.upload_aging)
        v1.addWidget(btn)
        self.btn_cols = QPushButton("تعديل أعمدة الملف")
        self.btn_cols.clicked.connect(lambda: self.upload_aging(force_columns=True))
        v1.addWidget(self.btn_cols)
        v1.addStretch()
        b2, v2 = step_box("٢) كشوف الحساب من النظام")
        self.stmt_info = QLabel("استخرج كشوف العملاء المطلوب مطابقتهم من النظام (PDF)، ثم ارفعها هنا. "
                                "البرنامج يأخذ كشوف المطلوب مطابقتهم فقط ويتجاهل الباقي.")
        self.stmt_info.setWordWrap(True)
        v2.addWidget(self.stmt_info)
        for text, mode in (("📥 رفع كشوف الآجل (ملف واحد لكل العملاء)", "credit"),
                           ("📥 رفع كشوف عهدة مندوب", "custody")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=None, m=mode: self.upload_statements(m))
            v2.addWidget(b)
        b = QPushButton("📋 نسخ أرقام العملاء المطلوب كشوفهم")
        b.clicked.connect(self.copy_codes)
        v2.addWidget(b)
        v2.addStretch()
        b3, v3 = step_box("٣) التجهيز والإرسال")
        self.pack_info = QLabel("بعد رفع الكشوف: جهّز ملف مضغوط لكل مندوب ثم أرسله.")
        self.pack_info.setWordWrap(True)
        v3.addWidget(self.pack_info)
        for text, fn in (("📦 تجهيز الملفات حسب المندوب", self.build), ("💾 تنزيل الكل", self.download_all),
                         ("📂 فتح فولدر الملفات", self.open_folder), ("✉ إرسال للمناديب", self.send)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            v3.addWidget(b)
        v3.addStretch()
        for b in (b1, b2, b3):
            steps.addWidget(b, 1)
        lay.addLayout(steps)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث بالاسم أو الرقم...")
        self.search.textChanged.connect(self.fill)
        self.f_rep = QComboBox()
        self.f_status = QComboBox()
        self.f_status.addItems(["كل الحالات", "كشف ناقص", "كشف جاهز", "اترسل كشف", "عليه تنبيه"])
        for w in (self.f_rep, self.f_status):
            w.currentIndexChanged.connect(self.fill)
        bar.addWidget(self.search, 2)
        bar.addWidget(QLabel("المندوب:"))
        bar.addWidget(self.f_rep, 1)
        bar.addWidget(QLabel("الحالة:"))
        bar.addWidget(self.f_status, 1)
        b = QPushButton("📎 إرفاق كشف صحيح للعميل المحدد")
        b.setToolTip("يستبدل كشف العميل المحدد فقط (مثلاً بعد تعديل كشف عليه تنبيه) بدون رفع كل الكشوف مرة ثانية")
        b.clicked.connect(lambda: self.attach_one())
        bar.addWidget(b)
        b = QPushButton("⬇ تنزيل العملاء عليهم تنبيه")
        menu = QMenu(b)
        menu.addAction("Excel", lambda: self.export_warnings("xlsx"))
        menu.addAction("PDF", lambda: self.export_warnings("pdf"))
        b.setMenu(menu)
        bar.addWidget(b)
        lay.addLayout(bar)
        self.summary = QLabel()
        self.summary.setStyleSheet(f"color:{NAVY}; font-weight:700;")
        lay.addWidget(self.summary)
        self.table = styled_table(["رقم العميل", "اسم العميل", "المندوب", "النوع", "الرصيد", "المتأخر",
                                   "رصيد الكشف", "الحالة", "التنبيهات"])
        self.table.doubleClicked.connect(self._open_customer)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.visible = []
        lay.addWidget(self.table, 1)

    # ---------------------------------------------------------------- data
    def load(self):
        db = self.win.db
        cur = self.cycle["month"] if self.cycle else None
        self.cycle_box.blockSignals(True)
        self.cycle_box.clear()
        for c in db.cycles():
            self.cycle_box.addItem(f"دورة {month_label(c['month'])}", c["month"])
        if cur:
            self.cycle_box.setCurrentIndex(max(0, self.cycle_box.findData(cur)))
        self.cycle_box.blockSignals(False)
        self._cycle_changed()

    def _cycle_changed(self):
        m = self.cycle_box.currentData()
        self.cycle = self.win.db.cycle(m) if m else None
        self.refresh()

    def refresh(self):
        db = self.win.db
        days = [int(db.setting_num(k)) for k, *_ in STAGES]
        self.stages.setText("   ←   ".join(f"{label} ({d}): {text}" for (k, label, text), d in zip(STAGES, days)))
        if not self.cycle:
            self.aging_info.setText("لا توجد دورة بعد — ارفع تقرير الأعمار لبدء دورة الشهر.")
            self.rows = []
            self.fill()
            return
        self.rows = day1.review(db, self.cycle)
        req = len(self.rows)
        total = db.cycle_customers(self.cycle["id"])
        self.aging_info.setText(f"تقرير {self.cycle.get('aging_file') or ''}\n{len(total)} عميل، منهم {req} مطلوب مطابقة "
                                f"بمتأخر {money(sum(r['overdue'] for r in self.rows))}")
        missing = sum(1 for r in self.rows if r["status"] == "كشف ناقص")
        self.stmt_info.setText(f"جاهز: {req - missing} كشف   |   ناقص: {missing} كشف\n"
                               "ارفع كشوف الآجل في ملف واحد، وكشوف العهدة ملف لكل مندوب.")
        reps = sorted({r["rep_name"] or "—" for r in self.rows})
        cur = self.f_rep.currentText()
        self.f_rep.blockSignals(True)
        self.f_rep.clear()
        self.f_rep.addItems(["الكل"] + reps)
        self.f_rep.setCurrentIndex(max(0, self.f_rep.findText(cur)))
        self.f_rep.blockSignals(False)
        self.fill()

    def fill(self):
        rows = getattr(self, "rows", [])
        q = self.search.text().strip()
        rep = self.f_rep.currentText()
        st = self.f_status.currentText()
        vis = []
        for r in rows:
            if q and q not in r["name"] and q not in r["code"]:
                continue
            if rep not in ("", "الكل") and (r["rep_name"] or "—") != rep:
                continue
            if st == "عليه تنبيه" and not r["warning"]:
                continue
            if st not in ("كل الحالات", "عليه تنبيه") and r["status"] != st:
                continue
            vis.append(r)
        self.visible = vis
        t = self.table
        t.setRowCount(len(vis))
        for i, r in enumerate(vis):
            vals = [r["code"], r["name"], r["rep_name"], r["types"]]
            for c, v in enumerate(vals):
                t.setItem(i, c, ro(v))
            for c, v in ((4, r["balance"]), (5, r["overdue"]), (6, r["stmt_balance"])):
                t.setItem(i, c, ro(money(v), True))
            it = ro(r["status"])
            color_item(it, STATUS_COLORS.get(r["status"], "#344054"))
            t.setItem(i, 7, it)
            w = ro(r["warning"])
            if r["warning"]:
                color_item(w, "#b54708")
            t.setItem(i, 8, w)
        t.resizeColumnsToContents()
        t.setColumnWidth(1, min(t.columnWidth(1), 300))
        t.setColumnWidth(8, min(max(t.columnWidth(8), 200), 700))
        self.summary.setText(f"المعروض: {len(vis)} من {len(rows)} عميل مطلوب مطابقة   |   المتأخر: "
                             f"{money(sum(r['overdue'] for r in vis))}   |   عليهم تنبيه: "
                             f"{sum(1 for r in vis if r['warning'])}")

    def _open_customer(self, index):
        r = self.visible[index.row()] if index.row() < len(self.visible) else None
        if r and r["warning"] and index.column() == 8:     # double click on the warning → attach the right statement
            self.attach_one(r)
            return
        code = self.table.item(index.row(), 0).text()
        self.win.open_customer(code)

    def _selected(self):
        row = self.table.currentRow()
        return self.visible[row] if 0 <= row < len(self.visible) else None

    def _menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self.visible):
            return
        self.table.selectRow(row)
        r = self.visible[row]
        m = QMenu(self)
        m.addAction(QAction("📎 إرفاق الكشف الصحيح لهذا العميل", m, triggered=lambda: self.attach_one(r)))
        if r["parts"]:
            m.addAction(QAction("📄 فتح الكشف الحالي", m, triggered=lambda: self._open_current(r)))
        m.addAction(QAction("👤 ملف العميل", m, triggered=lambda: self.win.open_customer(r["code"])))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _open_current(self, r):
        """The customer's pages from the uploaded statements, as one PDF."""
        import tempfile
        folder = self.win.folder
        if r.get("statement") and os.path.exists(os.path.join(folder.path, r["statement"])):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(folder.path, r["statement"])))
            return
        out = os.path.join(tempfile.mkdtemp(prefix="coll-"), f"{r['code']} - الكشف الحالي.pdf")
        try:
            ST.write_pdf([(os.path.join(folder.path, p["source"]), p["pages"]) for p in r["parts"]], out)
        except Exception as e:  # noqa: BLE001
            error(self, f"تعذر فتح الكشف:\n{e}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    # ------------------------------------------------------- one customer's statement
    def attach_one(self, r=None):
        """Replace the statement of one customer only — no need to upload all the statements again."""
        if not self.win.can_edit() or not self.cycle:
            return
        r = r or self._selected()
        if not r:
            warn(self, "اختر العميل من الجدول أولًا.")
            return
        start = QSettings().value("last_dir", os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(self, f"الكشف الصحيح للعميل {r['code']} - {r['name']}", start,
                                              "PDF (*.pdf)")
        if not path:
            return
        QSettings().setValue("last_dir", os.path.dirname(path))
        db, folder = self.win.db, self.win.folder
        try:
            with Progress(self, f"قراءة كشف {r['name']}") as bar:
                new = day1.replace_customer_statement(db, folder, self.cycle, r["code"], path, bar)
        except Exception as e:  # noqa: BLE001
            error(self, f"تعذر قراءة الملف:\n{e}")
            return
        if not new:
            if not ask(self, f"لم أجد في الملف كشفًا برقم العميل {r['code']}.\n"
                             "إرفاق الملف كله ككشف لهذا العميل وكتابة رصيده يدويًا؟"):
                return
            bal, ok = QInputDialog.getDouble(self, "رصيد الكشف", "إجمالي الرصيد عليكم في الكشف:",
                                             float(r["balance"] or 0), -1e12, 1e12, 2)
            if not ok:
                return
            kinds = {(p["account"], p["account_name"]) for p in r["parts"]}
            acc, acc_name = next(iter(kinds)) if len(kinds) == 1 else (ST.CREDIT_ACCOUNT, "العملاء")
            try:
                new = day1.replace_customer_statement(db, folder, self.cycle, r["code"], path,
                                                      whole=(acc, acc_name, bal))
            except Exception as e:  # noqa: BLE001
                error(self, f"تعذر إرفاق الملف:\n{e}")
                return
        self.refresh()
        now = next((x for x in self.rows if x["code"] == r["code"]), None)
        msg = [f"تم استبدال كشف {r['name']} ({r['code']}) — رصيد الكشف الجديد "
               f"{money(sum(s.balance or 0 for s in new))}، رصيد تقرير الأعمار {money(r['balance'])}."]
        if now and now["warning"]:
            msg.append("\n⚠ ما زال عليه تنبيه:\n" + now["warning"].replace(" | ", "\n"))
        else:
            msg.append("\n✅ لا توجد تنبيهات على العميل الآن.")
        if self.packages:
            self.packages = []
            self.pack_info.setText("تم تغيير كشف عميل — اضغط «تجهيز الملفات حسب المندوب» مرة ثانية قبل التنزيل أو "
                                   "الإرسال.")
            msg.append("\nاضغط «تجهيز الملفات حسب المندوب» مرة ثانية حتى يدخل الكشف الجديد في ملف المندوب.")
        info(self, "\n".join(msg))

    def export_warnings(self, kind):
        rows = [r for r in self.visible if r["warning"]]
        if not rows:
            info(self, "لا يوجد عملاء عليهم تنبيه في القائمة المعروضة.")
            return
        rep = self.f_rep.currentText()
        title = f"العملاء عليهم تنبيه — دورة {month_label(self.cycle['month'])}" + \
            (f" — {rep}" if rep not in ("", "الكل") else "")
        start = QSettings().value("last_dir", os.path.expanduser("~"))
        default = os.path.join(start, f"عليهم تنبيه - {self.cycle['month']}.{kind}")
        flt = "Excel (*.xlsx)" if kind == "xlsx" else "PDF (*.pdf)"
        path, _ = QFileDialog.getSaveFileName(self, "حفظ العملاء عليهم تنبيه", default, flt)
        if not path:
            return
        if not path.lower().endswith("." + kind):
            path += "." + kind
        try:
            (day1.export_warnings_excel if kind == "xlsx" else day1.export_warnings_pdf)(rows, path, title)
        except Exception as e:  # noqa: BLE001
            error(self, f"تعذر الحفظ:\n{e}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ---------------------------------------------------------------- step 1
    def upload_aging(self, force_columns=False):
        if not self.win.can_edit():
            return
        db = self.win.db
        md = MonthDialog(self, "دورة أي شهر؟", self.cycle["month"] if self.cycle else None)
        if md.exec() != QDialog.Accepted:
            return
        month = md.value()
        start = QSettings().value("last_dir", os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(self, "تقرير أعمار الديون", start, "Excel / CSV (*.xlsx *.xlsm *.csv)")
        if not path:
            return
        QSettings().setValue("last_dir", os.path.dirname(path))
        try:
            with Progress(self, "رفع تقرير الأعمار") as bar:
                bar.step(10, f"قراءة {os.path.basename(path)}")
                rows = aging.read_table(path)
                bar.step(100, f"تمت القراءة: {len(rows)} سطر")
        except Exception as e:  # noqa: BLE001
            error(self, f"تعذر قراءة الملف:\n{e}")
            return
        saved = db.column_map("aging")
        first, mapping = aging.guess_columns(rows)
        if saved and not force_columns:
            mapping, first = saved["mapping"], saved["first"]
            mapping = {k: int(v) for k, v in mapping.items()}
        if force_columns or not saved or "code" not in mapping:
            dlg = ColumnMapDialog(self, rows, aging.ROLES, aging.ROLE_LABELS, first, mapping,
                                  "حدد عمود كل بيان مرة واحدة، والبرنامج يحفظ الإعداد للمرات القادمة.")
            if dlg.exec() != QDialog.Accepted:
                return
            mapping, first = dlg.mapping(), dlg.first_row()
            if "code" not in mapping:
                warn(self, "لازم تحدد عمود رقم العميل.")
                return
            db.save_column_map("aging", {"mapping": mapping, "first": first})
        recs = aging.read_rows(rows, first, mapping)
        if not recs:
            warn(self, "لم أجد عملاء في الملف بالأعمدة المحددة. جرّب «تعديل أعمدة الملف».")
            return
        if db.cycle(month) and not ask(self, f"دورة {month_label(month)} موجودة. استبدال تقرير الأعمار؟ "
                                             "(الكشوف المرفوعة تبقى)"):
            return
        with Progress(self, f"تجهيز دورة {month_label(month)}") as bar:
            bar.step(20, f"حساب المتأخر وتحديد المطلوب مطابقتهم ({len(recs)} عميل)")
            grouped = aging.group_customers(recs, db.setting_num("custody_days"), db.setting_num("credit_days"),
                                            db.setting_num("min_overdue"), db.setting_num("max_customers"),
                                            self.skip_rules(month))
            bar.step(50, "تحديث بيانات العملاء")
            new, moved = db.upsert_from_aging(recs)
            bar.step(80, "حفظ الدورة")
            db.create_cycle(month, os.path.basename(path), date.today().isoformat(), grouped)
            bar.step(100, "تم")
        req = [g for g in grouped if g["required"]]
        db.log("رفع تقرير الأعمار", f"{os.path.basename(path)}: {len(grouped)} عميل، {len(req)} مطلوب مطابقة",
               cycle_id=db.cycle(month)["id"])
        auto = []
        reps_list = db.reps()
        for a in aging.rep_names(recs):
            if not db.rep_for(a):
                r = suggest_rep(a, reps_list)
                if r:
                    db.set_alias(a, r["id"])
                    auto.append(f"{a} ← {r['name']}")
        db.commit()
        unmapped = [a for a in aging.rep_names(recs) if not db.rep_for(a)]
        limit = int(db.setting_num("max_customers"))
        small = [g for g in grouped if not g["required"] and 0.005 < g["overdue"] <= db.setting_num("min_overdue")]
        skipped = [g for g in grouped if g.get("skip")]
        cut = [g for g in grouped if not g["required"] and not g.get("skip")
               and g["overdue"] > db.setting_num("min_overdue")]
        msg = [f"دورة {month_label(month)}: {len(grouped)} عميل، منهم {len(req)} مطلوب مطابقة بمتأخر "
               f"{money(sum(r['overdue'] for r in req))}."]
        if small:
            msg.append(f"• {len(small)} عميل متأخره أقل من {db.setting_num('min_overdue'):,.0f} ريال لم يدخل الدورة "
                       "(تقدر تغير الحد من الإعدادات).")
        if skipped:
            kinds = {}
            for g in skipped:
                kinds.setdefault(g["skip"].split(":")[0] if ":" in g["skip"] else "ضمان بنكي", []).append(g)
            msg.append(f"• {len(skipped)} عميل مستثنى بالإعدادات: "
                       + "، ".join(f"{k} ({len(v)})" for k, v in kinds.items()))
        if getattr(db, "carried_forced", None):
            msg.append(f"• {len(db.carried_forced)} عميل مستمر في مراحل الخطابات من الدورة السابقة بقي في الدورة "
                       "حتى لو كان خارج الحدود.")
        if cut:
            msg.append(f"• الدورة محددة بأكبر {limit} عميل متأخر — {len(cut)} عميل آخر لم يدخل هذا الشهر "
                       f"بمتأخر {money(sum(g['overdue'] for g in cut))}.")
        if new:
            msg.append(f"• {len(new)} عميل جديد أضيف لقائمة العملاء.")
        if moved:
            msg.append(f"• {len(moved)} عميل تغير مندوبه (مثال: {moved[0][0]}: {moved[0][1]} ← {moved[0][2]}).")
        if auto:
            msg.append(f"• تم ربط {len(auto)} اسم مندوب تلقائيًا (راجعها في شاشة «المناديب»): {'، '.join(auto)}.")
        if unmapped:
            msg.append(f"• أسماء مناديب غير مربوطة بإيميل ({len(unmapped)}): {'، '.join(unmapped)}.\n"
                       "  اربطها من شاشة «المناديب» حتى تصل الكشوف لكل مندوب.")
        self.cycle = db.cycle(month)
        self.load()
        self.win.update_banner()
        info(self, "\n".join(msg))

    def skip_rules(self, month):
        """Exclusions from the settings, applied when the aging report is uploaded."""
        db = self.win.db
        codes = {c["code"]: f"استثناء دائم: {c['perm_reason'] or 'بدون سبب'}"
                 for c in db.customers().values() if c.get("perm_exclude")}
        if db.setting("rest_matched") == "1":
            prev = db.previous_cycle(month)
            if prev:
                thr = db.setting_num("pay_threshold")
                paid = db.paid_by_code(prev["id"])        # all of last month's receipts
                for c in db.cycle_customers(prev["id"], required_only=True):
                    base = c["overdue"] or 0
                    pct = paid.get(c["code"], 0) / base if base > 0.005 else 1.0
                    if c["matched"] == 1 and pct >= thr and not c["level"] and c["code"] not in codes:
                        codes[c["code"]] = f"شهر راحة: طابق وسدد في دورة {prev['month']}"
        return {"skip_codes": codes, "skip_reps": db.setting_list("skip_reps"),
                "skip_classes": db.setting_list("skip_classes"), "guarantee": db.setting("guarantee_skip") == "1"}

    # ---------------------------------------------------------------- step 2
    def copy_codes(self):
        if not self.cycle:
            return
        codes = [r["code"] for r in self.rows if r["status"] == "كشف ناقص"]
        QApplication.clipboard().setText("\n".join(codes))
        info(self, f"تم نسخ {len(codes)} رقم عميل (الكشوف الناقصة) — الصقها في النظام لاستخراج كشوفهم.")

    def upload_statements(self, mode):
        if not self.win.can_edit():
            return
        if not self.cycle:
            warn(self, "ارفع تقرير الأعمار أولًا.")
            return
        rep_name = ""
        if mode == "custody":
            dlg = QDialog(self)
            dlg.setWindowTitle("كشوف عهدة أي مندوب؟")
            v = QVBoxLayout(dlg)
            v.addWidget(QLabel("اختر المندوب صاحب العهدة (كما في تقرير الأعمار):"))
            cb = QComboBox()
            cb.setEditable(True)
            cb.addItem("")
            cb.addItems(sorted({r["rep_name"] for r in self.rows if r["rep_name"]}))
            v.addWidget(QLabel("اتركه فارغًا ليُقرأ اسم المندوب من حساب العهدة في الكشف نفسه."))
            v.addWidget(cb)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            v.addWidget(bb)
            if dlg.exec() != QDialog.Accepted:
                return
            rep_name = cb.currentText().strip()
        start = QSettings().value("last_dir", os.path.expanduser("~"))
        paths, _ = QFileDialog.getOpenFileNames(self, "ملفات كشوف الحساب (PDF)", start, "PDF (*.pdf)")
        if not paths:
            return
        QSettings().setValue("last_dir", os.path.dirname(paths[0]))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        lines = []
        bar = Progress(self, "قراءة كشوف الحساب")
        try:
            for p in paths:
                bar.title = f"قراءة {os.path.basename(p)} (صفحة)"
                try:
                    r = day1.attach_file(self.win.db, self.win.folder, self.cycle, p, mode, rep_name, bar)
                except Exception as e:  # noqa: BLE001
                    lines.append(f"⛔ {os.path.basename(p)}: تعذر القراءة ({e})")
                    continue
                lines.append(f"📄 {r.file}: أُضيف {len(r.attached)} كشف لعملاء مطلوب مطابقتهم"
                             + (f"، تجاهل {len(r.ignored)} ليس عليهم مطابقة" if r.ignored else "")
                             + (f"، {len(r.unknown)} غير موجودين في تقرير الأعمار" if r.unknown else ""))
                if r.rep_mismatch:
                    lines.append(f"   ⚠ {len(r.rep_mismatch)} كشف عهدة لمندوب آخر: "
                                 + "، ".join(f"{c} ({rep})" for c, _, rep in r.rep_mismatch[:5]))
                if r.unread_pages:
                    lines.append(f"   ⚠ صفحات لم يُقرأ منها رقم العميل: {', '.join(str(x + 1) for x in r.unread_pages)}")
        finally:
            bar.close()
            QApplication.restoreOverrideCursor()
        self.refresh()
        missing = sum(1 for r in self.rows if r["status"] == "كشف ناقص")
        warned = sum(1 for r in self.rows if r["warning"])
        lines.append(f"\nالمتبقي: {missing} كشف ناقص   |   {warned} عميل عليه تنبيه (راجعهم في الجدول)")
        info(self, "\n".join(lines))

    # ---------------------------------------------------------------- step 3
    def build(self):
        if not self.win.can_edit() or not self.cycle:
            return
        missing = sum(1 for r in self.rows if r["status"] == "كشف ناقص")
        if missing and not ask(self, f"يوجد {missing} كشف ناقص. تجهيز الملفات بالكشوف الموجودة فقط؟"):
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        bar = Progress(self, "تجهيز كشف كل عميل")
        try:
            self.packages = day1.build_packages(self.win.db, self.win.folder, self.cycle, bar)
        except Exception as e:  # noqa: BLE001
            bar.close()
            QApplication.restoreOverrideCursor()
            error(self, f"تعذر التجهيز:\n{e}")
            return
        bar.close()
        QApplication.restoreOverrideCursor()
        no_rep = [p for p in self.packages if not p["rep_record"]]
        no_mail = [p for p in self.packages if p["rep_record"] and not p["email"]]
        self.pack_info.setText(f"{len(self.packages)} ملف مضغوط، {sum(len(p['customers']) for p in self.packages)} كشف."
                               + (f"\n⚠ {len(no_rep)} ملف بدون مندوب مربوط" if no_rep else "")
                               + (f"\n⚠ {len(no_mail)} مندوب بدون إيميل" if no_mail else ""))
        self.refresh()
        info(self, "تم تجهيز الملفات:\n" + "\n".join(f"• {p['rep']}: {len(p['customers'])} كشف"
                                                     + (f" ← {p['email']}" if p["email"] else " (بدون إيميل)")
                                                     for p in self.packages))

    def download_all(self):
        if not self.packages:
            warn(self, "جهّز الملفات أولًا (زر «تجهيز الملفات حسب المندوب»).")
            return
        dest = QFileDialog.getExistingDirectory(self, "حفظ الملفات المضغوطة في", os.path.expanduser("~"))
        if dest:
            with Progress(self, "تنزيل الملفات المضغوطة") as bar:
                day1.export_all(self.packages, dest, bar)
                bar(len(self.packages), len(self.packages))
            QDesktopServices.openUrl(QUrl.fromLocalFile(dest))

    def open_folder(self):
        if self.cycle:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.win.folder.files_dir(self.cycle["month"])))

    def send(self):
        if not self.win.can_edit():
            return
        if not self.packages:
            warn(self, "جهّز الملفات أولًا (زر «تجهيز الملفات حسب المندوب»).")
            return
        cfg = self.win.mail_config()
        if not cfg:
            warn(self, "اضبط إعدادات الإيميل أولًا من شاشة الإعدادات، أو استخدم «تنزيل الكل» وأرسل يدويًا.")
            return
        db = self.win.db
        month = month_label(self.cycle["month"])
        mails = []
        for p in self.packages:
            fmt = {"rep": p["rep"], "month": month, "count": len(p["customers"])}
            mails.append({"rep": p["rep"], "to": p["email"], "subject": db.setting("mail_subject").format(**fmt),
                          "body": db.setting("mail_body").format(**fmt), "files": [p["zip"]],
                          "count": f"{len(p['customers'])} كشف", "package": p})
        dlg = MailPreviewDialog(self, mails, cfg.get("cc", ""), "مراجعة إيميلات الكشوف قبل الإرسال")
        if dlg.exec() != QDialog.Accepted:
            return
        chosen = dlg.selected()
        if not chosen:
            return
        sendable = [m["package"] for m in chosen]
        msgs = [(m["to"], m["subject"], m["body"], m["files"]) for m in chosen]
        try:
            with Progress(self, "إرسال الكشوف للمناديب") as bar:
                bar.step(0, "الاتصال بخادم الإيميل")
                results = mailer.send_all(cfg, msgs, lambda d, t: bar(d, t, "إيميل مرسل"))
        except Exception as e:  # noqa: BLE001
            error(self, f"تعذر الاتصال بخادم الإيميل:\n{e}\n\nراجع إعدادات الإيميل، أو استخدم «تنزيل الكل».")
            return
        ok = {to for to, good, _ in results if good}
        for p in sendable:
            if p["email"] in ok:
                for c in p["customers"]:
                    db.update_cycle_customer(self.cycle["id"], c["code"], status="اترسل كشف")
                    db.log("إرسال كشف", f"للمندوب {p['rep']} ({p['email']})", code=c["code"], cycle_id=self.cycle["id"])
        self.refresh()
        bad = [(to, err) for to, good, err in results if not good]
        info(self, f"تم الإرسال إلى {len(ok)} مندوب." + ("\n\nفشل:\n" + "\n".join(f"{t}: {e}" for t, e in bad)
                                                     if bad else ""))
