"""Monthly dashboard: the cycle at a glance, filtered by rep, and the month-end Excel report."""
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from .. import report
from .widgets import NAVY, error, money, month_label, ro, styled_table


class Card(QFrame):
    def __init__(self, title, color=NAVY):
        super().__init__()
        self.setObjectName("card")
        self.setStyleSheet("QFrame#card { background:white; border:1px solid #e4e7ec; border-radius:8px; }")
        v = QVBoxLayout(self)
        t = QLabel(title)
        t.setStyleSheet("color:#475467;")
        self.value = QLabel("—")
        self.value.setStyleSheet(f"color:{color}; font-size:17pt; font-weight:700;")
        self.sub = QLabel("")
        self.sub.setStyleSheet("color:#667085;")
        for w in (t, self.value, self.sub):
            v.addWidget(w)

    def set(self, value, sub=""):
        self.value.setText(value)
        self.sub.setText(sub)


class DashboardPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.rows = []
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("الدورة:"))
        self.cycle_box = QComboBox()
        self.cycle_box.setMinimumWidth(180)
        self.cycle_box.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.cycle_box)
        top.addWidget(QLabel("المندوب:"))
        self.rep = QComboBox()
        self.rep.setMinimumWidth(240)
        self.rep.currentIndexChanged.connect(self.fill)
        top.addWidget(self.rep)
        top.addStretch()
        b = QPushButton("📊 تقرير نهاية الشهر Excel")
        b.clicked.connect(self.export)
        top.addWidget(b)
        lay.addLayout(top)

        grid = QGridLayout()
        specs = [("customers", "العملاء المطلوب مطابقتهم"), ("overdue", "المتأخر يوم 1"),
                 ("paid", "المسدد خلال الدورة", "#067647"), ("statements", "الكشوف"),
                 ("matched", "المطابقات", "#067647"), ("exited", "سددوا وخرجوا من الدورة", "#067647"),
                 ("letters", "الخطابات المصدرة", "#b54708"), ("stop_sale", "إيقاف بيع", "#b42318"),
                 ("other", "تفاوض / استبعاد", "#6941c6")]
        self.cards = {}
        for i, spec in enumerate(specs):
            card = Card(spec[1], spec[2] if len(spec) > 2 else NAVY)
            self.cards[spec[0]] = card
            grid.addWidget(card, i // 5, i % 5)
        lay.addLayout(grid)

        t = QLabel("حسب المندوب (اضغط مرتين على مندوب لعرضه فقط)")
        t.setStyleSheet(f"color:{NAVY}; font-weight:700; margin-top:6px;")
        lay.addWidget(t)
        self.table = styled_table(["المندوب", "العملاء", "المتأخر يوم 1", "المسدد", "نسبة التحصيل", "مطابق",
                                   "غير مطابق", "الكشف لم يرجع", "سددوا وخرجوا من الدورة", "خطاب مالي",
                                   "خطاب قانوني", "إجراء قانوني", "إيقاف بيع"])
        tips = {5: "رجع كشفه موقعًا ومطابقًا", 6: "رجع كشفه وعليه اعتراض", 7: "لم يرجع الكشف الموقع من المندوب بعد",
                8: "سدد نسبة الإعفاء من المتأخر (70% افتراضيًا) فخرج من الدورة ولا تصدر له خطابات",
                12: "عليه خطاب قانوني ولم يسدد النسبة — لا يُباع له"}
        for col, tip in tips.items():
            self.table.horizontalHeaderItem(col).setToolTip(tip)
        self.table.doubleClicked.connect(self._pick_rep)
        lay.addWidget(self.table, 1)

    def load(self):
        cur = self.cycle_box.currentData()
        self.cycle_box.blockSignals(True)
        self.cycle_box.clear()
        for c in self.win.db.cycles():
            self.cycle_box.addItem(f"دورة {month_label(c['month'])}", c["month"])
        if cur:
            self.cycle_box.setCurrentIndex(max(0, self.cycle_box.findData(cur)))
        self.cycle_box.blockSignals(False)
        self.refresh()

    def cycle(self):
        m = self.cycle_box.currentData()
        return self.win.db.cycle(m) if m else None

    def refresh(self):
        cyc = self.cycle()
        self.rows = report.customer_rows(self.win.db, cyc) if cyc else []
        cur = self.rep.currentText()
        self.rep.blockSignals(True)
        self.rep.clear()
        self.rep.addItem("كل المناديب")
        self.rep.addItems(sorted({r["rep"] for r in self.rows}))
        self.rep.setCurrentIndex(max(0, self.rep.findText(cur)))
        self.rep.blockSignals(False)
        self.fill()

    def visible(self):
        rep = self.rep.currentText()
        return [r for r in self.rows if rep in ("", "كل المناديب") or r["rep"] == rep]

    def fill(self):
        rows = self.visible()
        s = report.summarize(rows)
        n = s["customers"] or 1
        self.cards["customers"].set(f"{s['customers']}", f"الرصيد {money(s['balance'])}")
        self.cards["overdue"].set(money(s["overdue"]))
        self.cards["paid"].set(money(s["paid"]), f"{s['pct'] * 100:.0f}% من المتأخر")
        self.cards["statements"].set(f"{s['statements']}", f"أرسل {s['sent']} — ناقص {s['missing']}")
        self.cards["matched"].set(f"{s['matched']}", f"{s['matched'] / n * 100:.0f}% — غير مطابق {s['not_matched']} — "
                                                     f"الكشف لم يرجع {s['not_returned']}")
        self.cards["exited"].set(f"{s['exited']}", f"{s['exited'] / n * 100:.0f}% من العملاء")
        self.cards["letters"].set(f"{s['1003'] + s['1004'] + s['1005/1006']}",
                                  f"مالي {s['1003']} — قانوني {s['1004']} — إجراء {s['1005/1006']}"
                                  + (f" — ملغي {s['cancelled']}" if s["cancelled"] else ""))
        self.cards["stop_sale"].set(f"{s['stop_sale']}")
        self.cards["other"].set(f"{s['negotiating']} / {s['excluded']}", f"مستمر من دورة سابقة {s['carried']}")

        reps = report.by_rep(rows)
        t = self.table
        t.setRowCount(len(reps))
        for i, r in enumerate(reps):
            t.setItem(i, 0, ro(r["rep"]))
            t.setItem(i, 1, ro(r["customers"], True))
            t.setItem(i, 2, ro(money(r["overdue"]), True))
            t.setItem(i, 3, ro(money(r["paid"]), True))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(min(100, int(round(r["pct"] * 100))))
            bar.setFormat(f"{r['pct'] * 100:.0f}%")
            bar.setLayoutDirection(Qt.LeftToRight)
            t.setCellWidget(i, 4, bar)
            for c, key in enumerate(("matched", "not_matched", "not_returned", "exited", "1003", "1004",
                                     "1005/1006", "stop_sale"), start=5):
                t.setItem(i, c, ro(r[key], True))
        t.resizeColumnsToContents()
        t.setColumnWidth(4, 140)

    def _pick_rep(self, index):
        name = self.table.item(index.row(), 0).text()
        self.rep.setCurrentIndex(max(0, self.rep.findText(name)))

    def export(self):
        cyc = self.cycle()
        if not cyc:
            return
        rep = self.rep.currentText()
        rep = None if rep in ("", "كل المناديب") else rep
        name = f"تقرير التحصيل {cyc['month']}" + (f" - {rep}" if rep else "") + ".xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "تقرير نهاية الشهر", os.path.join(os.path.expanduser("~"), name),
                                              "Excel (*.xlsx)")
        if not path:
            return
        try:
            report.export_excel(self.win.db, cyc, path, rep)
        except Exception as e:  # noqa: BLE001
            error(self, f"تعذر إنشاء التقرير:\n{e}")
            return
        self.win.db.log("تقرير نهاية الشهر", os.path.basename(path), cycle_id=cyc["id"])
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
