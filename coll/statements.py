"""Customer statements from the accounting system (PDF): read, split per customer, merge.

Each page of the system's "كشف حساب تحليلي" shows the customer number and the control account
(1140101 العملاء = credit customers, or a rep custody account "عهدة مبيعات ..."). A customer can have a
credit section and one or more custody sections, even inside the same file. Sections are kept per
(customer, account) so the accountant can check each balance.
"""
import os
import re
from dataclasses import dataclass, field

from .textutil import AMOUNT, fix_pdf_word, norm, to_number

CREDIT_ACCOUNT = "1140101"
DATE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")


def _iso(d):
    day, month, year = d.split("/")
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


@dataclass
class Section:
    code: str
    name: str
    account: str
    account_name: str
    source: str            # file path
    pages: list = field(default_factory=list)   # 0-based page numbers in the source
    balance: float = None  # "إجمالي الرصيد عليكم" of the section
    opening: float = None  # "الرصيد الإفتتاحي" (0 when the label has no amount)
    date_from: str = ""    # ISO dates of the statement period
    date_to: str = ""

    @property
    def is_custody(self):
        return self.account != CREDIT_ACCOUNT

    @property
    def custody_rep(self):
        """Rep name from a custody account name like "عهدة مبيعات سلطان العمودي"."""
        if not self.is_custody:
            return ""
        return re.sub(r"^\s*عهد[ةه]\s+مبيعات\s*", "", self.account_name).strip()


def _word_lines(page):
    """Lines of (text, x centre), right to left."""
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    rows = {}
    for w in words:
        rows.setdefault(round(w["top"] / 4), []).append(w)
    out = []
    for k in sorted(rows):
        ws = sorted(rows[k], key=lambda w: -w["x0"])  # right to left
        out.append([(fix_pdf_word(w["text"]), (w["x0"] + w["x1"]) / 2) for w in ws])
    return out


def _lines(page):
    return [[t for t, _ in line] for line in _word_lines(page)]


def _after_label(tokens, label_words):
    """Tokens of a line after a label such as "رقم العميل"."""
    joined = [norm(t) for t in tokens]
    lab = [norm(x) for x in label_words]
    for i in range(len(joined) - len(lab) + 1):
        if joined[i:i + len(lab)] == lab:
            return tokens[i + len(lab):]
    return None


def read_page(page):
    """Return dict(code, name, account, account_name, balance) found on the page (values may be None)."""
    info = {"code": None, "name": "", "account": None, "account_name": "", "balance": None, "opening": None,
            "date_from": "", "date_to": ""}
    debit_x = credit_x = None
    for line in _word_lines(page):
        tokens = [t for t, _ in line]
        for t, x in line:
            if t == "مدين" and debit_x is None:
                debit_x = x
            elif t == "دائن" and credit_x is None:
                credit_x = x
        if not info["date_from"]:
            dates = [t for t in tokens if DATE.fullmatch(t)]
            if len(dates) >= 2 and any(norm(t) == norm("تاريخ") for t in tokens):
                info["date_from"], info["date_to"] = (_iso(d) for d in dates[:2])
                continue
        rest = _after_label(tokens, ["الرصيد", "الإفتتاحي"]) or _after_label(tokens, ["الرصيد", "الافتتاحي"])
        if rest is not None and info["opening"] is None:
            amounts = [(to_number(t), x) for t, x in line[len(tokens) - len(rest):] if AMOUNT.match(t)]
            value, x = amounts[-1] if amounts else (0.0, None)
            # an opening amount printed under «دائن» is a credit balance
            if x is not None and debit_x is not None and credit_x is not None \
                    and abs(x - credit_x) < abs(x - debit_x):
                value = -value
            info["opening"] = value
            continue
        rest = _after_label(tokens, ["رقم", "العميل"])
        if rest and info["code"] is None:
            nums = [t for t in rest if re.fullmatch(r"\d{5,}", t)]
            if nums:
                info["code"] = nums[0]
                info["name"] = " ".join(t for t in rest if t != nums[0] and not re.fullmatch(r"[\d:]+", t)).strip()
            continue
        rest = _after_label(tokens, ["رقم", "الحساب"])
        if rest and info["account"] is None:
            nums = [t for t in rest if re.fullmatch(r"\d{5,}", t)]
            if nums:
                info["account"] = nums[0]
                info["account_name"] = " ".join(t for t in rest if t != nums[0]).strip()
            continue
        for label, sign in ((["إجمالي", "الرصيد", "عليكم"], 1), (["إجمالي", "الرصيد", "لكم"], -1)):
            rest = _after_label(tokens, label)
            if rest is not None:
                amounts = [to_number(t) for t in rest if AMOUNT.match(t)]
                if amounts:
                    info["balance"] = sign * amounts[-1]
    return info


def read_pdf(path):
    """Split a statements PDF into sections (one per customer and control account)."""
    import pdfplumber
    sections = []
    unknown_pages = []
    with pdfplumber.open(path) as pdf:
        current = None
        for i, page in enumerate(pdf.pages):
            info = read_page(page)
            code = info["code"] or (current.code if current else None)
            account = info["account"] or (current.account if current else None)
            if not code:
                unknown_pages.append(i)
                continue
            if current is None or (code, account) != (current.code, current.account):
                current = Section(code, info["name"] or (current.name if current and current.code == code else ""),
                                  account or "", info["account_name"], path, date_from=info["date_from"],
                                  date_to=info["date_to"])
                sections.append(current)
            if current.opening is None and info["opening"] is not None:
                current.opening = info["opening"]
            current.pages.append(i)
            if info["balance"] is not None:
                current.balance = info["balance"]
    return sections, unknown_pages


def write_pdf(parts, out_path):
    """parts: [(source path, [pages] or None for all)] → one PDF."""
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    readers = {}
    for src, pages in parts:
        if src not in readers:
            readers[src] = PdfReader(src)
        for p in (range(len(readers[src].pages)) if pages is None else pages):   # None = all pages
            writer.add_page(readers[src].pages[p])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)
    return out_path


def group_by_customer(sections):
    out = {}
    for s in sections:
        out.setdefault(s.code, []).append(s)
    return out
