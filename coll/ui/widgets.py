"""Shared dialogs and small helpers for the screens."""
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
                               QLabel, QMessageBox, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

NAVY = "#12355b"
MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
STATUS_COLORS = {"كشف ناقص": "#b42318", "كشف جاهز": "#067647", "اترسل كشف": "#1d6fb8", "مطلوب مطابقة": "#b54708"}


def month_label(m):
    return f"{MONTHS[int(m[5:7]) - 1]} {m[:4]}" if m else "—"


def info(parent, text):
    QMessageBox.information(parent, "معلومة", text)


def warn(parent, text):
    QMessageBox.warning(parent, "تنبيه", text)


def error(parent, text):
    QMessageBox.critical(parent, "خطأ", text)


def ask(parent, text):
    return QMessageBox.question(parent, "تأكيد", text) == QMessageBox.Yes


def ro(text, align_num=False):
    it = QTableWidgetItem("" if text is None else str(text))
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if align_num:
        it.setTextAlignment(Qt.AlignAbsolute | Qt.AlignRight | Qt.AlignVCenter)
    return it


def money(v):
    if v is None:
        return "—"
    return "‎" + (f"({abs(v):,.2f})" if v < 0 else f"{v:,.2f}") + "‎"


def styled_table(cols):
    t = QTableWidget(0, len(cols))
    t.setHorizontalHeaderLabels(cols)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setAlternatingRowColors(True)
    t.setStyleSheet(f"QHeaderView::section {{ background:{NAVY}; color:white; font-weight:600; padding:4px; }}")
    return t


def color_item(it, color):
    it.setForeground(QColor(color))
    f = it.font()
    f.setBold(True)
    it.setFont(f)


class MonthDialog(QDialog):
    def __init__(self, parent, title, default=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        d = date.today()
        default = default or f"{d.year:04d}-{d.month:02d}"
        f = QFormLayout(self)
        self.year = QSpinBox()
        self.year.setRange(2020, 2100)
        self.year.setValue(int(default[:4]))
        self.month = QComboBox()
        self.month.addItems(MONTHS)
        self.month.setCurrentIndex(int(default[5:7]) - 1)
        f.addRow("السنة:", self.year)
        f.addRow("الشهر:", self.month)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def value(self):
        return f"{self.year.value():04d}-{self.month.currentIndex() + 1:02d}"


def col_letter(i):
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


class ColumnMapDialog(QDialog):
    """Choose the column of each field; the choice is saved and reused next time."""

    def __init__(self, parent, rows, roles, labels, first, mapping, help_text):
        super().__init__(parent)
        self.rows = rows
        self.setWindowTitle("تحديد الأعمدة")
        self.resize(1100, 640)
        lay = QVBoxLayout(self)
        h = QLabel(help_text)
        h.setWordWrap(True)
        lay.addWidget(h)
        grid = QGridLayout()
        width = len(rows[0]) if rows else 0
        self.combos = {}
        for i, role in enumerate(roles):
            cb = QComboBox()
            cb.addItem("— غير موجود —", None)
            for c in range(width):
                hint = self._hint(c, first)
                cb.addItem(f"عمود {col_letter(c)}" + (f" — {hint}" if hint else ""), c)
            if mapping.get(role) is not None and mapping[role] < width:
                cb.setCurrentIndex(mapping[role] + 1)
            self.combos[role] = cb
            grid.addWidget(QLabel(labels[role]), i // 5 * 2, i % 5)
            grid.addWidget(cb, i // 5 * 2 + 1, i % 5)
        lay.addLayout(grid)
        row = QFormLayout()
        self.first = QSpinBox()
        self.first.setRange(1, max(1, len(rows)))
        self.first.setValue(first + 1)
        row.addRow("أول صف بيانات:", self.first)
        lay.addLayout(row)
        t = QTableWidget(min(len(rows), 40), width)
        t.setHorizontalHeaderLabels([col_letter(c) for c in range(width)])
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for r in range(t.rowCount()):
            for c in range(width):
                v = rows[r][c]
                t.setItem(r, c, QTableWidgetItem("" if v is None else str(v)))
        t.resizeColumnsToContents()
        lay.addWidget(t, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _hint(self, c, first):
        parts = [str(self.rows[r][c]).strip() for r in range(max(0, first - 2), first)
                 if self.rows[r][c] is not None and str(self.rows[r][c]).strip()]
        return " / ".join(parts)[:35]

    def mapping(self):
        return {r: cb.currentData() for r, cb in self.combos.items() if cb.currentData() is not None}

    def first_row(self):
        return self.first.value() - 1
