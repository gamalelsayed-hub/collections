"""Aging report import and the "reconciliation required" rule.

A customer may appear on several rows (credit and custody); rows are grouped by customer code.
Overdue per row: custody ("عهدة") = buckets older than the custody limit (default 30 days),
other types = buckets older than the credit limit (default 60 days).
"""
import csv

from .textutil import code_text, norm, to_number

BUCKETS = ["b0", "b1", "b2", "b3", "b4"]
BUCKET_NAMES = ["0 - 30", "31 - 60", "61 - 90", "91 - 120", "أكثر من 120"]
ROLES = ["code", "name", "region", "branch", "rep", "cls", "ctype", "b0", "b1", "b2", "b3", "b4", "guarantee"]
ROLE_LABELS = {
    "code": "رقم العميل", "name": "اسم العميل", "region": "المنطقة", "branch": "الفرع", "rep": "المندوب",
    "cls": "التصنيف", "ctype": "النوع (آجل / عهدة)", "b0": "0 - 30", "b1": "31 - 60", "b2": "61 - 90",
    "b3": "91 - 120", "b4": "أكثر من 120", "guarantee": "ضمان بنكي",
}
HEADER_WORDS = {
    "code": ("رقم العميل", "كود العميل", "الكود", "رقم"), "name": ("اسم العميل", "الاسم", "اسم"),
    "region": ("المنطقة",), "branch": ("الفرع",), "rep": ("المندوب", "البائع"), "cls": ("التصنيف", "تصنيف"),
    "ctype": ("نوع العميل", "النوع", "نوع"), "b0": ("0 - 30", "0-30", "حالي"), "b1": ("31 - 60", "31-60"),
    "b2": ("61 - 90", "61-90"), "b3": ("91 - 120", "91-120"),
    "b4": ("أكثر من 120", "اكثر من 120", "120+", "> 120"), "guarantee": ("ضمان",),
}


def read_table(path):
    p = path.lower()
    if p.endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        rows = None
        for enc in ("utf-8-sig", "cp1256"):
            try:
                with open(path, newline="", encoding=enc) as f:
                    rows = [list(r) for r in csv.reader(f)]
                break
            except UnicodeDecodeError:
                continue
    width = max((len(r) for r in rows), default=0)
    return [r + [None] * (width - len(r)) for r in rows]


def guess_columns(rows):
    """(first data row, {role: column}) from the header titles."""
    for i, r in enumerate(rows[:30]):
        cells = [str(v).strip() if v is not None else "" for v in r]
        found = {}
        for role in ROLES:
            for w in HEADER_WORDS[role]:
                c = next((k for k, t in enumerate(cells) if t and w in t and k not in found.values()), None)
                if c is not None:
                    found[role] = c
                    break
        if "code" in found and len(found) >= 5:
            return i + 1, found
    return 0, {}


def is_custody(ctype):
    return "عهد" in (ctype or "")


def first_overdue_bucket(days):
    """Index of the first bucket that is overdue for a limit in days (30 → 31-60 bucket)."""
    for i, limit in enumerate((30, 60, 90, 120)):
        if days <= limit:
            return i + 1
    return 5


def row_overdue(r, custody_days, credit_days):
    first = first_overdue_bucket(custody_days if is_custody(r.get("ctype")) else credit_days)
    return sum(r[b] for b in BUCKETS[first:])


def read_rows(rows, first, mapping):
    out = []
    for r in rows[first:]:
        def get(role):
            c = mapping.get(role)
            return r[c] if c is not None and c < len(r) else None
        code = code_text(get("code"))
        if not code or not any(ch.isdigit() for ch in code):
            continue
        rec = {"code": code, "name": str(get("name") or "").strip(), "region": str(get("region") or "").strip(),
               "branch": str(get("branch") or "").strip(), "rep_name": str(get("rep") or "").strip(),
               "cls": str(get("cls") or "").strip(), "ctype": str(get("ctype") or "").strip(),
               "guarantee": to_number(get("guarantee")) or 0.0}
        for b in BUCKETS:
            rec[b] = to_number(get(b)) or 0.0
        out.append(rec)
    return out


def group_customers(rows, custody_days, credit_days):
    """One record per customer code: totals, overdue, types and the responsible rep."""
    groups = {}
    for r in rows:
        groups.setdefault(r["code"], []).append(r)
    out = []
    for code, rs in groups.items():
        rec = {"code": code, "name": next((x["name"] for x in rs if x["name"]), ""), "warning": ""}
        for b in BUCKETS:
            rec[b] = sum(x[b] for x in rs)
        for x in rs:
            x["_balance"] = sum(x[b] for b in BUCKETS)
            x["_overdue"] = row_overdue(x, custody_days, credit_days)
        rec["balance"] = sum(x["_balance"] for x in rs)
        rec["overdue"] = sum(x["_overdue"] for x in rs)
        types = []
        for x in rs:
            t = "عهدة" if is_custody(x["ctype"]) else (x["ctype"] or "آجل")
            if t not in types:
                types.append(t)
        rec["types"] = " + ".join(types)
        main = max(rs, key=lambda x: (x["_overdue"], x["_balance"]))
        rec["rep_name"] = main["rep_name"]
        reps = sorted({x["rep_name"] for x in rs if x["rep_name"]})
        if len(reps) > 1:
            rec["warning"] = f"العميل مسجل على أكثر من مندوب: {'، '.join(reps)}"
        rec["required"] = 1 if rec["overdue"] > 0.005 else 0
        rec["status"] = "مطلوب مطابقة" if rec["required"] else ""
        for f in ("region", "branch", "cls", "ctype"):
            rec[f] = main[f]
        out.append(rec)
    out.sort(key=lambda r: -r["overdue"])
    return out


def rep_names(rows):
    return sorted({r["rep_name"] for r in rows if r.get("rep_name")}, key=norm)
