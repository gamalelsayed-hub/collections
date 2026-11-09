"""Receipt vouchers (سندات القبض) from the system, PDF or Excel.

Only lines paid by a customer count: the analytic account (الحساب التحليلي) must be a customer number.
Internal movements (cash ↔ cash, cash ↔ bank, bank ↔ bank) use cash/bank accounts (1110xxx) with a box code as
analytic, so they are excluded.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime

from .textutil import AMOUNT, code_text, fix_pdf_word, to_number

DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
CUSTOMER_ACCOUNT = "1140"     # العملاء and the reps' custody accounts
ROLES = ["voucher", "due", "date", "account", "name", "code", "amount"]
ROLE_LABELS = {"voucher": "رقم السند", "due": "تاريخ الاستحقاق (يُحسب به السداد)", "date": "تاريخ السند",
               "account": "رقم الحساب", "name": "اسم الحساب", "code": "الحساب التحليلي (رقم العميل)",
               "amount": "المبلغ"}
HEADER_WORDS = {"voucher": ("رقم السند",), "due": ("الاستحقاق",), "date": ("تاريخ السند", "التاريخ", "تاريخ"),
                "account": ("رقم الحساب",),
                "name": ("اسم الحساب", "اسم العميل"), "code": ("التحليلي", "رقم العميل"), "amount": ("المبلغ",)}


@dataclass
class Receipt:
    voucher: str
    date: str          # ISO yyyy-mm-dd
    account: str
    name: str
    code: str
    amount: float
    due: str = ""      # تاريخ الاستحقاق (ISO) — the date the payment counts on; empty = the voucher date

    @property
    def counted(self):
        return self.due or self.date


def parse_date(v):
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    m = DATE.match(str(v or "").strip())
    if m:
        d, mth, y = map(int, m.groups())
        return f"{y:04d}-{mth:02d}-{d:02d}"
    return str(v or "")[:10]


def is_customer_line(account, code, known_codes=None):
    if not code or not re.fullmatch(r"\d{6,}", code):
        return False
    if known_codes is not None and code in known_codes:
        return True
    return (account or "").startswith(CUSTOMER_ACCOUNT)


def read_pdf(path, known_codes=None, progress=None):
    """Return (customer receipts, excluded internal/other lines count). progress(done, total, text) per page."""
    import pdfplumber

    from .pdfrepair import readable
    out, excluded = [], 0
    with pdfplumber.open(readable(path)) as pdf:
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            if progress:
                progress(i, n, f"صفحة {i + 1}")
            rows = {}
            for w in page.extract_words():
                rows.setdefault(round(w["top"] / 4), []).append(w)
            for k in sorted(rows):
                toks = [fix_pdf_word(w["text"]) for w in sorted(rows[k], key=lambda w: -w["x0"])]
                rec = _pdf_line(toks)
                if rec is None:
                    continue
                if is_customer_line(rec.account, rec.code, known_codes):
                    out.append(rec)
                else:
                    excluded += 1
    return out, excluded


def _pdf_line(toks):
    """A voucher line: number, date, ..., account (7 digits), name, analytic, amount, ..."""
    if len(toks) < 6 or not re.fullmatch(r"\d+", toks[0]) or not DATE.match(toks[1]):
        return None
    acc_i = next((i for i, t in enumerate(toks) if i > 2 and re.fullmatch(r"11\d{5}", t)), None)
    amt_i = next((i for i, t in enumerate(toks) if acc_i is not None and i > acc_i
                  and AMOUNT.match(t) and "." in t), None)
    if acc_i is None or amt_i is None:
        return None
    code = next((toks[i] for i in range(amt_i - 1, acc_i, -1) if re.fullmatch(r"\d{3,}", toks[i])), "")
    name = " ".join(t for t in toks[acc_i + 1:amt_i] if t != code)
    name = re.sub(r"\s*(SAR|RAS)\s*", " ", name).strip()
    name = re.sub(r"(RAS|SAR)$", "", name).strip()
    later = [t for t in toks[amt_i + 1:] if DATE.match(t)]      # the due date comes after the amount
    due = parse_date(later[-1]) if later else ""
    return Receipt(toks[0], parse_date(toks[1]), toks[acc_i], name, code, to_number(toks[amt_i]) or 0.0, due)


def guess_columns(rows):
    for i, r in enumerate(rows[:30]):
        cells = [str(v).strip() if v is not None else "" for v in r]
        found = {}
        for role in ROLES:
            for w in HEADER_WORDS[role]:
                c = next((k for k, t in enumerate(cells) if t and w in t and k not in found.values()), None)
                if c is not None:
                    found[role] = c
                    break
        if "code" in found and "amount" in found:
            return i + 1, found
    return 0, {}


def read_rows(rows, first, mapping, known_codes=None):
    out, excluded = [], 0
    for r in rows[first:]:
        def get(role):
            c = mapping.get(role)
            return r[c] if c is not None and c < len(r) else None
        amount = to_number(get("amount"))
        if not amount:
            continue
        due = parse_date(get("due")) if get("due") not in (None, "") else ""
        rec = Receipt(code_text(get("voucher")), parse_date(get("date")), code_text(get("account")),
                      str(get("name") or "").strip(), code_text(get("code")), amount, due)
        if not rec.date:
            rec.date = due
        if is_customer_line(rec.account, rec.code, known_codes) if rec.account else \
                (rec.code in (known_codes or ()) or bool(re.fullmatch(r"\d{6,}", rec.code or ""))):
            out.append(rec)
        else:
            excluded += 1
    return out, excluded
