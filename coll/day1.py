"""Day 1 of the cycle: attach system statements to the customers that need reconciliation,
check them, build one statement per customer and one ZIP per rep."""
import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

from . import statements as ST
from .pdfrepair import readable
from .textutil import norm

BALANCE_TOLERANCE = 1.0


@dataclass
class UploadResult:
    file: str
    mode: str
    attached: list = field(default_factory=list)      # (code, name, account_name, balance)
    ignored: list = field(default_factory=list)       # codes found but not required
    unknown: list = field(default_factory=list)       # codes not in the aging report at all
    rep_mismatch: list = field(default_factory=list)  # custody file of another rep
    unread_pages: list = field(default_factory=list)


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]+', "-", str(s)).strip()[:80] or "—"


def attach_file(db, folder, cycle, path, mode, rep_name=""):
    """mode: 'credit' (one file for all credit customers) or 'custody' (one file per rep).
    Stores a copy of the file and the sections of the customers that need reconciliation."""
    name = os.path.basename(path)
    path = readable(path)   # repaired copy if the file's ending is damaged
    sections, unread = ST.read_pdf(path)
    res = UploadResult(name, mode, unread_pages=unread)
    cust = {c["code"]: c for c in db.cycle_customers(cycle["id"])}
    src_dir = folder.files_dir(cycle["month"], "sources")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    copy = os.path.join(src_dir, f"{stamp} - {safe_name(name)}")
    shutil.copy2(path, copy)
    for sec in sections:
        c = cust.get(sec.code)
        if c is None:
            res.unknown.append((sec.code, sec.name))
            continue
        if not c["required"]:
            res.ignored.append(sec.code)
            continue
        if mode == "custody" and rep_name and sec.is_custody and norm(sec.custody_rep) not in norm(rep_name) \
                and norm(rep_name) not in norm(sec.custody_rep):
            res.rep_mismatch.append((sec.code, sec.name, sec.custody_rep))
        db.save_section(cycle["id"], sec, mode, os.path.relpath(copy, folder.path))  # relative: Drive paths differ per PC
        res.attached.append((sec.code, sec.name or c["name"], sec.account_name, sec.balance))
    db.commit()
    db.log("رفع كشوف", f"{res.file} ({'آجل' if mode == 'credit' else 'عهدة ' + rep_name}): "
                       f"{len(res.attached)} كشف لعملاء مطلوب مطابقتهم، {len(res.ignored)} ليس عليهم مطابقة، "
                       f"{len(res.unknown)} غير موجودين في الأعمار", cycle_id=cycle["id"])
    return res


def review(db, cycle):
    """Check every required customer against its statement sections. Updates status/warnings and returns
    a list of dicts for the screen."""
    secs = db.sections(cycle["id"])
    prev = db.previous_cycle(cycle["month"])
    prev_cust = {x["code"]: x for x in db.cycle_customers(prev["id"])} if prev else {}
    prev_secs = db.sections(prev["id"]) if prev else {}
    out = []
    for c in db.cycle_customers(cycle["id"], required_only=True):
        parts = secs.get(c["code"], [])
        warnings = [c["warning"]] if c["warning"] and "أكثر من مندوب" in c["warning"] else []
        c["prepend"] = ""
        pc = prev_cust.get(c["code"])
        if parts and pc:
            warnings += _carry_over(c, parts, pc, prev_secs.get(c["code"], []), prev["month"])
        if not parts:
            status, total, detail = "كشف ناقص", None, ""
        else:
            total = sum(p["balance"] or 0 for p in parts)
            detail = " + ".join(f"{'آجل' if p['account'] == ST.CREDIT_ACCOUNT else p['account_name']}: "
                                f"{(p['balance'] or 0):,.2f}" for p in parts)
            status = "كشف جاهز"
            kinds = {p["account"] == ST.CREDIT_ACCOUNT for p in parts}
            if len(kinds) > 1:
                warnings.append(f"⚠ العميل له كشف آجل وكشف عهدة — تم دمجهما في ملف واحد. راجع الرصيد: {detail}")
            if any(p["balance"] is None for p in parts):
                warnings.append("⚠ لم يُقرأ رصيد أحد الكشوف — راجعه يدويًا")
            if abs(total - (c["balance"] or 0)) > BALANCE_TOLERANCE:
                warnings.append(f"⚠ رصيد الكشف {total:,.2f} لا يساوي رصيد تقرير الأعمار {c['balance']:,.2f} "
                                f"(فرق {total - c['balance']:,.2f})")
        warning = " | ".join(w for w in warnings if w)
        # later stages (sent, matched, letters...) keep their status
        if c["status"] not in ("", "مطلوب مطابقة", "كشف ناقص", "كشف جاهز"):
            status = c["status"]
        db.update_cycle_customer(cycle["id"], c["code"], status=status, stmt_balance=total, stmt_detail=detail,
                                 warning=warning)
        c.update(status=status, stmt_balance=total, stmt_detail=detail, warning=warning, parts=parts)
        out.append(c)
    return out


def _carry_over(c, parts, pc, prev_parts, prev_month):
    """Monthly statements (starting after last month's statement): check the opening balance against the balance
    the customer confirmed, or attach last month's statement when the customer did not reconcile."""
    starts = [p.get("date_from") or "" for p in parts]
    prev_end = max((p.get("date_to") or "" for p in prev_parts), default="")
    if not prev_end or not all(starts) or min(starts) <= prev_end:
        return []   # the new statement already covers last month's period
    if pc["matched"] == 1:
        openings = [p.get("opening") for p in parts]
        if None not in openings and pc["stmt_balance"] is not None \
                and abs(sum(openings) - pc["stmt_balance"]) > BALANCE_TOLERANCE:
            return [f"⚠ الرصيد الافتتاحي {sum(openings):,.2f} لا يساوي الرصيد الذي طابق عليه العميل في دورة "
                    f"{prev_month} ({pc['stmt_balance']:,.2f})"]
        return []
    if pc["statement"]:
        c["prepend"] = pc["statement"]
        return [f"📎 العميل لم يطابق في دورة {prev_month} — يُرفق كشف الشهر السابق قبل كشف هذا الشهر"]
    return []


def rep_of(db, rep_name):
    rep = db.rep_for(rep_name) if rep_name else None
    return rep


def build_packages(db, folder, cycle):
    """Write one PDF per customer (credit + custody merged) and one ZIP per rep with a summary sheet.
    Returns [{rep, email, zip, customers}] and the customers without a rep."""
    rows = review(db, cycle)
    month = cycle["month"]
    base = folder.files_dir(month, "statements")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)
    by_rep = {}
    for c in rows:
        if not c["parts"]:
            continue
        rep = rep_of(db, c["rep_name"])
        key = rep["name"] if rep else f"بدون مندوب ({c['rep_name'] or '—'})"
        rep_dir = os.path.join(base, safe_name(key))
        pdf = os.path.join(rep_dir, f"{c['code']} - {safe_name(c['name'])}.pdf")
        parts = [(os.path.join(folder.path, p["source"]), p["pages"]) for p in c["parts"]]
        old = os.path.join(folder.path, c["prepend"]) if c["prepend"] else ""
        if old and os.path.exists(old):
            parts.insert(0, (old, None))
        ST.write_pdf(parts, pdf)
        db.update_cycle_customer(cycle["id"], c["code"], statement=os.path.relpath(pdf, folder.path))
        entry = by_rep.setdefault(key, {"rep": key, "email": rep["email"] if rep else "", "rep_record": rep,
                                        "customers": [], "dir": rep_dir})
        entry["customers"].append(c)
    zips_dir = folder.files_dir(month, "zips")
    for f in os.listdir(zips_dir):
        os.remove(os.path.join(zips_dir, f))
    packages = []
    for key, e in sorted(by_rep.items()):
        summary = os.path.join(e["dir"], "قائمة العملاء.xlsx")
        _summary_sheet(e["customers"], key, month, summary)
        zpath = os.path.join(zips_dir, f"{safe_name(key)} - كشوف {month}.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for name in sorted(os.listdir(e["dir"])):
                z.write(os.path.join(e["dir"], name), name)
        e["zip"] = zpath
        packages.append(e)
    db.log("تجهيز الكشوف", f"{sum(len(p['customers']) for p in packages)} كشف في {len(packages)} ملف مضغوط",
           cycle_id=cycle["id"])
    return packages


def _summary_sheet(customers, rep, month, path):
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.sheet_view.rightToLeft = True
    ws.title = "العملاء"
    ws.append([f"كشوف العملاء المطلوب مطابقتهم — {rep} — {month}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    head = ["رقم العميل", "اسم العميل", "النوع", "رصيد الأعمار", "المتأخر", "رصيد الكشف", "تفصيل الكشف", "ملاحظات"]
    ws.append(head)
    for cell in ws[3]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="12355B")
    for c in customers:
        ws.append([c["code"], c["name"], c["types"], c["balance"], c["overdue"], c["stmt_balance"], c["stmt_detail"],
                   c["warning"]])
    for col, w in zip("ABCDEFGH", (14, 40, 14, 14, 14, 14, 40, 50)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=4, min_col=4, max_col=6):
        for cell in row:
            cell.number_format = "#,##0.00"
    wb.save(path)


def export_all(packages, dest_dir):
    """Copy every rep ZIP into a folder chosen by the user."""
    os.makedirs(dest_dir, exist_ok=True)
    for p in packages:
        shutil.copy2(p["zip"], dest_dir)
    return dest_dir
