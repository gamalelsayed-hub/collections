"""Synthetic data only — no real customer files in the repository."""
from coll import statements as ST
from coll.textutil import fix_pdf_word, norm, to_number


def vis(s):
    """Arabic word as the system's PDF stores it (visual order)."""
    return s[::-1]


class FakePage:
    def __init__(self, lines):
        self.words = []
        for row, tokens in enumerate(lines):
            x = 500
            for t in tokens:  # tokens given in reading order (right to left)
                self.words.append({"text": t, "top": row * 20, "x0": x, "x1": x + 50})
                x -= 60

    def extract_words(self, **_):
        return self.words


def test_fix_pdf_word():
    assert fix_pdf_word(vis("رقم")) == "رقم"
    assert fix_pdf_word("12,345.50") == "12,345.50"
    assert fix_pdf_word("١٢") == "12"
    assert norm("إجمالي  الرصيد") == "اجمالي الرصيد"
    assert to_number("(1,000.50)") == -1000.5
    assert to_number("250-") == -250


def test_read_page_credit_and_custody():
    page = FakePage([
        [vis("رقم"), vis("العميل"), "90000001", vis("مؤسسة"), vis("الاختبار")],
        [vis("رقم"), vis("الحساب"), "1140101", vis("العملاء")],
        [vis("إجمالي"), vis("الرصيد"), vis("عليكم"), "1,250.75"],
    ])
    info = ST.read_page(page)
    assert info["code"] == "90000001"
    assert info["name"] == "مؤسسة الاختبار"
    assert info["account"] == "1140101"
    assert info["balance"] == 1250.75

    page = FakePage([
        [vis("رقم"), vis("العميل"), "90000002", vis("شركة")],
        [vis("رقم"), vis("الحساب"), "1140115", vis("عهدة"), vis("مبيعات"), vis("سالم"), vis("أحمد")],
        [vis("إجمالي"), vis("الرصيد"), vis("لكم"), "18.79"],
    ])
    info = ST.read_page(page)
    assert info["balance"] == -18.79
    sec = ST.Section(info["code"], info["name"], info["account"], info["account_name"], "x.pdf")
    assert sec.is_custody and sec.custody_rep == "سالم أحمد"
