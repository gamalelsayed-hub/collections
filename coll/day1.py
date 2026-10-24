"""Day 1 of the cycle: attach system statements to the customers that need reconciliation,
check them, build one statement per customer and one ZIP per rep."""
import os
import re
import shutil
import tempfile
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


def attach_file(db, folder, cycle, path, mode, rep_name="", progress=None):
    """mode: 'credit' (one file for all credit customers) or 'custody' (one file per rep).
    Stores a copy of the file and the sections of the customers that need reconciliation."""
    name = os.path.basename(path)
    path = readable(path)   # repaired copy if the file's ending is damaged
    sections, unread = ST.read_pdf(path, progress)
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
    tol = db.setting_num("balance_tolerance")
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
            warnings += _carry_over(c, parts, pc, prev_secs.get(c["code"], []), prev["month"], tol)
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
            if abs(total - (c["balance"] or 0)) > tol:
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


def _carry_over(c, parts, pc, prev_parts, prev_month, tol=BALANCE_TOLERANCE):
    """Monthly statements (starting after last month's statement): check the opening balance against the balance
    the customer confirmed, or attach last month's statement when the customer did not reconcile."""
    starts = [p.get("date_from") or "" for p in parts]
    prev_end = max((p.get("date_to") or "" for p in prev_parts), default="")
    if not prev_end or not all(starts) or min(starts) <= prev_end:
        return []   # the new statement already covers last month's period
    if pc["matched"] == 1:
        openings = [p.get("opening") for p in parts]
        if None not in openings and pc["stmt_balance"] is not None \
                and abs(sum(openings) - pc["stmt_balance"]) > tol:
            return [f"⚠ الرصيد الافتتاحي {sum(openings):,.2f} لا يساوي الرصيد الذي طابق عليه العميل في دورة "
                    f"{prev_month} ({pc['stmt_balance']:,.2f})"]
        return []
    if pc["statement"]:
        c["prepend"] = pc["statement"]
        return [f"📎 العميل لم يطابق في دورة {prev_month} — يُرفق كشف الشهر السابق قبل كشف هذا الشهر"]
    return []


def aging_page(db, folder, c, out):
    """One page on the letterhead: the customer's aging buckets from the aging report and the overdue amount."""
    from . import letters as L
    from .stages import letterhead
    as_of = max((p.get("date_to") or "" for p in c.get("parts") or []), default="")
    # ranges in words: «0 - 30» would be flipped to «30 - 0» inside Arabic text
    buckets = [("من 0 إلى 30 يوم", c["b0"]), ("من 31 إلى 60 يوم", c["b1"]), ("من 61 إلى 90 يوم", c["b2"]),
               ("من 91 إلى 120 يوم", c["b3"]), ("أكثر من 120 يوم", c["b4"])]
    # Qt draws table columns left to right: write them reversed so «0 - 30» is on the right
    cols = [("الإجمالي", c["balance"])] + buckets[::-1]
    head = "".join(f'<td align="center" bgcolor="#12355b"><font color="white"><b>{t}</b></font></td>' for t, _ in cols)
    vals = "".join(f'<td align="center">{L.money(v or 0)}</td>' for _, v in cols)
    body = (
        '<p dir="rtl" align="center" style="font-size:15pt; font-weight:bold;">أعمار الديون</p>'
        f'<p dir="rtl" align="right" style="font-size:12pt;"><b>العميل:</b> {c["name"]}<br/>'
        f'<b>رقم العميل:</b> {c["code"]}<br/><b>نوع الحساب:</b> {c.get("types") or ""}'
        + (f'<br/><b>حتى تاريخ:</b> {L.fmt_date(as_of)}' if as_of else "") + '</p>'
        '<table dir="rtl" width="100%" border="1" cellspacing="0" cellpadding="6" style="font-size:11pt;">'
        f'<tr>{head}</tr><tr>{vals}</tr></table>'
        f'<p dir="rtl" align="right" style="font-size:13pt; margin-top:14px;"><b>المبلغ المتأخر المطلوب سداده:</b> '
        f'{L.money(c["overdue"] or 0)} ريال سعودي<br/><b>إجمالي الأعمار = رصيد كشف الحساب:</b> '
        f'{L.money(c["balance"] or 0)} ريال سعودي</p>'
        '<p dir="rtl" align="right" style="font-size:11pt; color:#475467;">الأعمار من تقرير أعمار الديون لدى الشركة، '
        'وتُحسب بالأيام من تاريخ الفاتورة. نرجو مراجعتها مع كشف الحساب المرفق.</p>')
    L.write_pdf([body], out, letterhead(db, folder), "أعمار الديون")
    return out


def rep_of(db, rep_name):
    rep = db.rep_for(rep_name) if rep_name else None
    return rep


def build_packages(db, folder, cycle, progress=None):
    """Write one PDF per customer (credit + custody merged) and one ZIP per rep with a summary sheet.
    Returns [{rep, email, zip, customers}] and the customers without a rep."""
    rows = review(db, cycle)
    tol = db.setting_num("balance_tolerance")
    month = cycle["month"]
    base = folder.files_dir(month, "statements")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)
    by_rep = {}
    todo = [c for c in rows if c["parts"]]
    cache = ST.PdfCache()
    for i, c in enumerate(todo):
        if progress:
            progress(i, len(todo), c["name"])
        rep = rep_of(db, c["rep_name"])
        key = rep["name"] if rep else f"بدون مندوب ({c['rep_name'] or '—'})"
        rep_dir = os.path.join(base, safe_name(key))
        pdf = os.path.join(rep_dir, f"{c['code']} - {safe_name(c['name'])}.pdf")
        parts = [(os.path.join(folder.path, p["source"]), p["pages"]) for p in c["parts"]]
        old = os.path.join(folder.path, c["prepend"]) if c["prepend"] else ""
        if old and os.path.exists(old):
            parts.insert(0, (old, None))
        aging_pdf = ""
        balance_ok = c["stmt_balance"] is not None and abs(c["stmt_balance"] - (c["balance"] or 0)) <= tol
        if db.setting("attach_aging") == "1" and not balance_ok:
            # the aging total must equal the statement balance, or the customer sees two different figures
            warn = "⚠ لم تُرفق صفحة الأعمار لأن إجمالي الأعمار لا يساوي رصيد الكشف"
            c["warning"] = " | ".join(w for w in (c["warning"], warn) if w)
            db.update_cycle_customer(cycle["id"], c["code"], warning=c["warning"])
        if db.setting("attach_aging") == "1" and balance_ok:
            aging_pdf = os.path.join(tempfile.mkdtemp(prefix="coll-"), "aging.pdf")
            aging_page(db, folder, c, aging_pdf)
            parts.append((aging_pdf, None))
        ST.write_pdf(parts, pdf, renumber=True, cache=cache)
        if aging_pdf:
            shutil.rmtree(os.path.dirname(aging_pdf), ignore_errors=True)
        db.update_cycle_customer(cycle["id"], c["code"], statement=os.path.relpath(pdf, folder.path))
        entry = by_rep.setdefault(key, {"rep": key, "email": rep["email"] if rep else "", "rep_record": rep,
                                        "customers": [], "dir": rep_dir})
        entry["customers"].append(c)
    cache.close()
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


MATCH_HEAD, REASON_HEAD = "حالة المطابقة", "سبب عدم المطابقة"
MATCH_CHOICES = ["مطابق", "غير مطابق", "لم يرد"]


def read_rep_sheet(path):
    """The customers sheet returned by a rep: [(code, status, reason)] for the rows with a status."""
    import openpyxl
    from .textutil import code_text, norm
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        head = next((i for i, r in enumerate(rows[:15]) if any(norm(v) == norm(MATCH_HEAD) for v in r if v)), None)
        if head is None:
            continue
        cells = [norm(v) for v in rows[head]]
        c_code = next((k for k, v in enumerate(cells) if v == norm("رقم العميل")), 0)
        c_st = cells.index(norm(MATCH_HEAD))
        c_rs = next((k for k, v in enumerate(cells) if v == norm(REASON_HEAD)), None)
        for r in rows[head + 1:]:
            code = code_text(r[c_code]) if c_code < len(r) else ""
            st = str(r[c_st] or "").strip() if c_st < len(r) else ""
            if not code or not st:
                continue
            reason = str(r[c_rs] or "").strip() if c_rs is not None and c_rs < len(r) else ""
            choice = next((ch for ch in MATCH_CHOICES if norm(ch) == norm(st)), None)
            out.append((code, choice or st, reason))
    wb.close()
    return out


def apply_rep_sheet(db, cycle, entries):
    """مطابق → matched, غير مطابق → not matched with the reason, لم يرد → noted (still waiting).
    Returns (applied, unknown codes, invalid statuses)."""
    from . import stages
    known = {c["code"] for c in db.cycle_customers(cycle["id"])}
    applied, unknown, invalid = 0, [], []
    for code, st, reason in entries:
        if code not in known:
            unknown.append(code)
            continue
        if st == "مطابق":
            stages.set_matched(db, cycle, code, 1, "من ملف المندوب")
        elif st == "غير مطابق":
            stages.set_matched(db, cycle, code, 0, reason or "بدون سبب من المندوب")
        elif st == "لم يرد":
            db.update_cycle_customer(cycle["id"], code, matched=None, match_reason="لم يرد" + (f": {reason}" if reason
                                                                                              else ""))
            db.log("مطابقة", "لم يرد العميل (من ملف المندوب)", code=code, cycle_id=cycle["id"])
        else:
            invalid.append(f"{code}: {st}")
            continue
        applied += 1
    return applied, unknown, invalid


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
    head = ["رقم العميل", "اسم العميل", "النوع", "رصيد الأعمار", "المتأخر", "رصيد الكشف", "تفصيل الكشف", "ملاحظات",
            MATCH_HEAD, REASON_HEAD]
    ws.append(head)
    for cell in ws[3]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="12355B")
    for cell in (ws["I3"], ws["J3"]):
        cell.fill = PatternFill("solid", fgColor="B54708")
    for c in customers:
        ws.append([c["code"], c["name"], c["types"], c["balance"], c["overdue"], c["stmt_balance"], c["stmt_detail"],
                   c["warning"], "", ""])
    last = 3 + len(customers)
    if customers:
        from openpyxl.worksheet.datavalidation import DataValidation
        dv = DataValidation(type="list", formula1='"' + ",".join(MATCH_CHOICES) + '"', allow_blank=True,
                            showErrorMessage=True, errorTitle="حالة المطابقة",
                            error="اختر من القائمة: " + " / ".join(MATCH_CHOICES))
        dv.prompt, dv.promptTitle, dv.showInputMessage = "اختر حالة المطابقة من القائمة", "حالة المطابقة", True
        ws.add_data_validation(dv)
        dv.add(f"I4:I{last}")
        fill = PatternFill("solid", fgColor="FFF4D6")
        for r in range(4, last + 1):
            ws.cell(r, 9).fill = fill
            ws.cell(r, 10).fill = fill
    ws.append([])
    ws.append(["عبّئ «حالة المطابقة» لكل عميل، واكتب السبب في حال «غير مطابق»، ثم أرجع الملف للتحصيل."])
    for col, w in zip("ABCDEFGHIJ", (14, 40, 14, 14, 14, 14, 40, 50, 16, 45)):
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
