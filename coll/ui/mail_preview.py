"""Preview before sending: one separate e-mail per rep, each with its own file; choose who to send to."""
import os
import zipfile

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget)


def _size(path):
    try:
        n = os.path.getsize(path)
    except OSError:
        return "غير موجود!"
    return f"{n / 1024 / 1024:.1f} ميجا" if n > 1024 * 1024 else f"{n / 1024:.0f} كيلو"


class MailPreviewDialog(QDialog):
    """mails: [{rep, to, subject, body, files: [paths], count}]. After exec(): selected() → the mails to send,
    with any edits to subject/body."""

    def __init__(self, parent, mails, cc="", title="مراجعة الإيميلات قبل الإرسال"):
        super().__init__(parent)
        self.mails = mails
        self.current = None
        self.setWindowTitle(title)
        self.resize(1150, 680)
        lay = QVBoxLayout(self)
        note = QLabel("كل مندوب يوصله <b>إيميل منفصل</b> فيه ملفه هو فقط. اختر المناديب من القائمة، واضغط على أي "
                      "مندوب لمعاينة إيميله وتعديل الموضوع أو النص قبل الإرسال.")
        note.setWordWrap(True)
        lay.addWidget(note)
        split = QSplitter()
        lay.addWidget(split, 1)

        left = QWidget()
        lv = QVBoxLayout(left)
        self.list = QListWidget()
        self.list.setMinimumWidth(420)
        for m in mails:
            it = QListWidgetItem(f"{m['rep']}  —  {m['to'] or 'بدون إيميل'}  ({m['count']})")
            if m["to"]:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked)
            else:
                it.setFlags(it.flags() & ~Qt.ItemIsUserCheckable)
                it.setForeground(Qt.gray)
                it.setToolTip("لا يوجد إيميل لهذا المندوب — أضفه من شاشة المناديب أو أرسل يدويًا")
            self.list.addItem(it)
        self.list.currentRowChanged.connect(self._show)
        self.list.itemChanged.connect(self._count)
        lv.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, val in (("تحديد الكل", True), ("إلغاء الكل", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=None, v=val: self._check_all(v))
            row.addWidget(b)
        lv.addLayout(row)
        split.addWidget(left)

        right = QWidget()
        f = QFormLayout(right)
        self.to = QLabel()
        self.cc = QLabel(cc or "—")
        self.subject = QLineEdit()
        self.body = QPlainTextEdit()
        self.body.setMinimumHeight(220)
        self.files = QListWidget()
        self.files.setMaximumHeight(170)
        f.addRow("إلى:", self.to)
        f.addRow("نسخة (CC):", self.cc)
        f.addRow("الموضوع:", self.subject)
        f.addRow("النص:", self.body)
        f.addRow("المرفقات:", self.files)
        b = QPushButton("📂 فتح المرفق")
        b.clicked.connect(self._open_file)
        f.addRow("", b)
        split.addWidget(right)
        split.setStretchFactor(1, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok = bb.button(QDialogButtonBox.Ok)
        bb.button(QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._count()
        if mails:
            self.list.setCurrentRow(0)

    def _save_edits(self):
        if self.current is not None:
            self.mails[self.current]["subject"] = self.subject.text()
            self.mails[self.current]["body"] = self.body.toPlainText()

    def _show(self, i):
        self._save_edits()
        self.current = i if 0 <= i < len(self.mails) else None
        if self.current is None:
            return
        m = self.mails[i]
        self.to.setText(m["to"] or "⚠ لا يوجد إيميل — لن يُرسل")
        self.subject.setText(m["subject"])
        self.body.setPlainText(m["body"])
        self.files.clear()
        for p in m["files"]:
            self.files.addItem(f"📎 {os.path.basename(p)}  ({_size(p)})")
            if p.lower().endswith(".zip") and os.path.exists(p):
                with zipfile.ZipFile(p) as z:
                    for name in z.namelist():
                        self.files.addItem(f"      • {name}")

    def _open_file(self):
        if self.current is not None and self.mails[self.current]["files"]:
            p = self.mails[self.current]["files"][0]
            QDesktopServices.openUrl(QUrl.fromLocalFile(p if os.path.exists(p) else os.path.dirname(p)))

    def _check_all(self, value):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(Qt.Checked if value else Qt.Unchecked)

    def _count(self, *_):
        n = sum(1 for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.Checked)
        self.ok.setText(f"✉ إرسال للمحددين ({n} إيميل منفصل)")
        self.ok.setEnabled(n > 0)

    def selected(self):
        self._save_edits()
        return [m for i, m in enumerate(self.mails) if self.list.item(i).checkState() == Qt.Checked]
