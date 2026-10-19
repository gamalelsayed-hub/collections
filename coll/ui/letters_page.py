"""Letters register (cancel, open) and negotiations (form 1002)."""
import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import stages
from ..letters import fmt_date
from .widgets import ask, color_item, info, money, ro, styled_table, warn


class LettersPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)

        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث بالعميل أو رقم الخطاب...")
        self.search.textChanged.connect(self.fill)
        self.kind = QComboBox()
        self.kind.addItem("كل الأنواع", "")
        for k, name in stages.KIND_NAMES.items():
            self.kind.addItem(f"{k[:4]} — {name}", k)
        self.kind.currentIndexChanged.connect(self.fill)
        self.status = QComboBox()
        self.status.addItems(["الكل", "صادر", "ملغي"])
        self.status.currentIndexChanged.connect(self.fill)
        bar.addWidget(self.search, 2)
        bar.addWidget(self.kind, 1)
        bar.addWidget(self.status)
        v.addLayout(bar)
        self.table = styled_table(["رقم الخطاب", "النوع", "التاريخ", "رقم العميل", "اسم العميل", "المندوب", "المبلغ",
                                   "الحالة", "الخطاب السابق", "المستخدم", "سبب الإلغاء"])
        self.table.doubleClicked.connect(self.open_pdf)
        v.addWidget(self.table, 1)
        bar = QHBoxLayout()
        for text, fn in (("📄 فتح الخطاب", self.open_pdf), ("✖ إلغاء الخطاب (يبقى رقمه مسجلًا)", self.cancel)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        self.count = QLabel()
        bar.addWidget(self.count)
        v.addLayout(bar)
        tabs.addTab(w, "سجل الخطابات")

        w = QWidget()
        v = QVBoxLayout(w)
        note = QLabel("التفاوض يُبدأ من شاشة «المتابعة والخطابات» (كليك يمين على العميل). أثناء التفاوض يُستثنى العميل "
                      "من المراحل. «لم يلتزم» يرجعه للمراحل من آخر خطاب، و«التزم» يُخرجه من الدورة.")
        note.setWordWrap(True)
        v.addWidget(note)
        self.neg = styled_table(["#", "رقم العميل", "اسم العميل", "التاريخ", "المبلغ", "الأقساط", "الحالة",
                                 "رقم الاتفاقية", "ملاحظة"])
        v.addWidget(self.neg, 1)
        bar = QHBoxLayout()
        for text, fn in (("📄 فتح الاتفاقية", self.open_neg), ("✔ التزم (إنهاء)", lambda: self.close_neg(True)),
                         ("✖ لم يلتزم (يرجع للمراحل)", lambda: self.close_neg(False))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        v.addLayout(bar)
        tabs.addTab(w, "التفاوض (1002)")

    def load(self):
        self.data = self.win.db.letters()
        self.fill()
        self.fill_neg()

    def fill(self):
        s = self.search.text().strip()
        kind = self.kind.currentData()
        st = self.status.currentText()
        rows = [l for l in self.data if (not s or s in l["serial"] or s in (l["code"] or "") or s in (l["name"] or ""))
                and (not kind or l["kind"] == kind) and (st == "الكل" or l["status"] == st)]
        self.rows = rows
        t = self.table
        t.setRowCount(len(rows))
        for i, l in enumerate(rows):
            vals = [l["serial"], stages.KIND_NAMES.get(l["kind"], l["kind"]), fmt_date(l["date"]), l["code"], l["name"],
                    l["rep_name"], money(l["amount"]), l["status"], l["prev_serial"], l["user"], l["cancel_reason"]]
            for c, val in enumerate(vals):
                it = ro(val, c == 6)
                if c == 7 and l["status"] == "ملغي":
                    color_item(it, "#b42318")
                t.setItem(i, c, it)
        t.resizeColumnsToContents()
        self.count.setText(f"{len(rows)} خطاب")

    def current(self):
        i = self.table.currentRow()
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def open_pdf(self):
        l = self.current()
        if l and l["pdf"]:
            p = os.path.join(self.win.folder.path, l["pdf"])
            if os.path.exists(p):
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))
            else:
                warn(self, "ملف الخطاب غير موجود (ربما لم يكتمل تزامن جوجل درايف).")

    def cancel(self):
        l = self.current()
        if not l or not self.win.can_edit():
            return
        if l["status"] == "ملغي":
            info(self, "الخطاب ملغي من قبل.")
            return
        reason, ok = QInputDialog.getText(self, "إلغاء خطاب", f"سبب إلغاء الخطاب {l['serial']}:")
        if not ok:
            return
        if not reason.strip():
            warn(self, "لازم تكتب سبب الإلغاء.")
            return
        if ask(self, f"إلغاء الخطاب {l['serial']}؟\nيبقى الرقم مسجلًا بحالة «ملغي» ولا يُستخدم مرة أخرى، "
                     "ويرجع العميل للمرحلة السابقة."):
            stages.cancel_letter(self.win.db, l["cycle_id"], l["serial"], reason.strip())
            self.load()

    # ---------------------------------------------------------------- negotiations
    def fill_neg(self):
        self.negs = self.win.db.negotiations()
        t = self.neg
        t.setRowCount(len(self.negs))
        for i, n in enumerate(self.negs):
            inst = n["data"].get("inst") or []
            inst_text = " | ".join(f"{a:,.0f} في {fmt_date(d)}" for a, d in inst) or "سحب نقدي 130%"
            vals = [n["id"], n["code"], n["name"], n["created"][:10], money(n["amount"]), inst_text, n["status"],
                    n["serial"], n["note"]]
            for c, val in enumerate(vals):
                it = ro(val, c == 4)
                if c == 6:
                    color_item(it, {"جاري": "#6941c6", "التزم": "#067647", "لم يلتزم": "#b42318"}.get(n["status"], "#344054"))
                t.setItem(i, c, it)
        t.resizeColumnsToContents()
        late = {x["id"] for x in stages.late_instalments(self.win.db)}
        for i, n in enumerate(self.negs):
            if n["id"] in late:
                self.neg.item(i, 5).setText("⏰ قسط متأخر — " + self.neg.item(i, 5).text())
                color_item(self.neg.item(i, 5), "#b42318")

    def current_neg(self):
        i = self.neg.currentRow()
        return self.negs[i] if 0 <= i < len(self.negs) else None

    def open_neg(self):
        n = self.current_neg()
        if n and n["pdf"]:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(self.win.folder.path, n["pdf"])))

    def close_neg(self, kept):
        n = self.current_neg()
        if not n or not self.win.can_edit():
            return
        if n["status"] != "جاري":
            info(self, "هذا التفاوض منتهي.")
            return
        note, ok = QInputDialog.getText(self, "إنهاء التفاوض", "ملاحظة (اختياري):")
        if not ok:
            return
        db = self.win.db
        # apply to the newest cycle that contains the customer
        cycle = next((c for c in db.cycles() if db.cycle_customer(c["id"], n["code"])), None)
        stages.close_negotiation(db, cycle, n["id"], kept, note.strip())
        self.load()
