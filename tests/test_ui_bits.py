from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QDoubleSpinBox
from pypdf import PdfReader

from coll import day1
from coll.ui.widgets import NoWheelFilter


def test_wheel_does_not_change_numbers(qapp):
    f = NoWheelFilter(qapp)
    qapp.installEventFilter(f)
    try:
        sp = QDoubleSpinBox()
        sp.setRange(0, 100)
        sp.setValue(70)
        ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                         Qt.NoScrollPhase, False)
        QApplication.sendEvent(sp, ev)
        assert sp.value() == 70
    finally:
        qapp.removeEventFilter(f)


def test_export_warnings_pdf(tmp_path, qapp):
    rows = [{"code": "9000000%d" % i, "name": "عميل تجريبي %d" % i, "rep_name": "مندوب", "types": "آجل",
             "balance": 1000.0 * i, "overdue": 500.0, "stmt_balance": 900.0 * i,
             "warning": "⚠ رصيد الكشف لا يساوي رصيد تقرير الأعمار | ⚠ لم يُقرأ رصيد أحد الكشوف"} for i in range(1, 60)]
    out = day1.export_warnings_pdf(rows, str(tmp_path / "w.pdf"), "العملاء عليهم تنبيه")
    assert len(PdfReader(out).pages) >= 2
