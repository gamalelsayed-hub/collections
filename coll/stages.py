"""Day 7 / 14 / 21 of the cycle: signed statements, receipts, the payment rule, letters and negotiation.

Payment rule: paid (cumulative receipts uploaded for the cycle) ÷ overdue at Day 1. A customer who reaches the
threshold (70% by default) leaves the cycle. The others get the next letter:
  level 0 → 1003 finance letter
  level 1 → 1004 legal letter (PN version if the customer has a promissory note) + stop-sale alert
  level 2 → 1005 PN to execution (if the legal letter was the PN version) or 1006 lawsuit warning
"""
import os
import re
import shutil
import zipfile
from datetime import date

from . import letters as L
from .day1 import safe_name

STAGES = {
    "finance": (1, "خطاب الإدارة المالية"),
    "legal": (2, "خطاب الإدارة القانونية"),
    "action": (3, "الإجراء القانوني"),
}
LEVEL_OF_KIND = {"1003": 1, "1004": 2, "1004PN": 2, "1005": 3, "1006": 3}
KIND_NAMES = {"1003": "خطاب مالي", "1004": "خطاب قانوني", "1004PN": "خطاب قانوني (سند لأمر)",
              "1005": "إحالة السند للتنفيذ", "1006": "إنذار دعوى", "1002": "اتفاقية تسوية"}
DAY1_STATUSES = ("", "مطلوب مطابقة", "كشف ناقص", "كشف جاهز", "اترسل كشف")


THRESHOLD_KEYS = {"finance": "pay_threshold", "legal": "pay_threshold_legal", "action": "pay_threshold_action"}
NEXT_STAGE = {0: "finance", 1: "legal", 2: "action", 3: "action"}


def threshold(db, stage="finance"):
    """Paid share of the Day 1 overdue that stops the letter of this stage."""
    return db.setting_num(THRESHOLD_KEYS[stage or "finance"])


def thresholds_by_level(db):
    return {lvl: threshold(db, st) for lvl, st in NEXT_STAGE.items()}


def negotiating_codes(db):
    return {n["code"] for n in db.negotiations(active_only=True)}


def derive_status(c, thr, negotiating):
    """thr: one threshold, or {level: threshold} for the stage each customer is waiting for."""
    if isinstance(thr, dict):
        thr = thr.get(c.get("level") or 0, 0.7)
    if c["code"] in negotiating:
        return "تحت التفاوض"
    if c.get("excluded"):
        return "مستبعد"
    if (c.get("pct") or 0) >= thr:
        return f"سدد {c['pct'] * 100:.0f}%"
    level = c.get("level") or 0
    if level == 3:
        return "إحالة السند للتنفيذ" if c.get("pn_letter") else "إنذار دعوى"
    if level == 2:
        return "خطاب قانوني — إيقاف بيع"
    if level == 1:
        return "خطاب مالي"
    if c.get("matched") == 1:
        return "مطابق"
    if c.get("matched") == 0:
        return "غير مطابق"
    if c.get("status") in DAY1_STATUSES:
        return c["status"]
    return "اترسل كشف" if c.get("statement") else "مطلوب مطابقة"


def refresh_status(db, cycle, codes=None):
    thr, neg = thresholds_by_level(db), negotiating_codes(db)
    for c in db.cycle_customers(cycle["id"], required_only=True):
        if codes is not None and c["code"] not in codes:
            continue
        st = derive_status(c, thr, neg)
        if st != c["status"]:
            db.update_cycle_customer(cycle["id"], c["code"], commit=False, status=st)
    db.commit()


# ------------------------------------------------------------------ signed statements
CODE_IN_NAME = re.compile(r"(?<!\d)(\d{6,10})(?!\d)")


def attach_signed(db, folder, cycle, paths):
    """Signed statements named with the customer number (e.g. "18010274.pdf" or "18010274 - name.jpg").
    Returns (matched [(code, name)], unknown files)."""
    cust = {c["code"]: c for c in db.cycle_customers(cycle["id"])}
    dest = folder.files_dir(cycle["month"], "signed")
    matched, unknown = [], []
    for p in paths:
        m = next((x for x in CODE_IN_NAME.findall(os.path.basename(p)) if x in cust), None)
        if not m:
            unknown.append(os.path.basename(p))
            continue
        matched.append((m, cust[m]["name"]))
        attach_signed_to(db, folder, cycle, m, p, dest)
    refresh_status(db, cycle, {c for c, _ in matched})
    return matched, unknown


def attach_signed_to(db, folder, cycle, code, path, dest=None):
    dest = dest or folder.files_dir(cycle["month"], "signed")
    c = db.cycle_customer(cycle["id"], code)
    ext = os.path.splitext(path)[1]
    target = os.path.join(dest, f"{code} - {safe_name(c['name'] if c else '')}{ext}")
    n = 1
    while os.path.exists(target):
        n += 1
        target = os.path.join(dest, f"{code} - {safe_name(c['name'] if c else '')} ({n}){ext}")
    shutil.copy2(path, target)
    db.update_cycle_customer(cycle["id"], code, matched=1, signed=os.path.relpath(target, folder.path))
    db.log("كشف موقع", os.path.basename(path), code=code, cycle_id=cycle["id"])
    refresh_status(db, cycle, {code})


def set_matched(db, cycle, code, value, note=""):
    db.update_cycle_customer(cycle["id"], code, matched=value)
    db.log("مطابقة", {1: "مطابق", 0: "غير مطابق", None: "إلغاء"}[value] + (f" — {note}" if note else ""),
           code=code, cycle_id=cycle["id"])
    refresh_status(db, cycle, {code})


# ------------------------------------------------------------------ receipts
STAGE_DAYS = {"finance": "day_finance", "legal": "day_legal", "action": "day_action"}


def cycle_start(db, cycle):
    """Day 1 of the collection period: the 1st of the cycle month (September cycle → September receipts),
    unless changed for this cycle."""
    cyc = db.cycle(cycle["month"])
    return cyc.get("start_date") or f"{cycle['month']}-01"


def holidays(db):
    """Holiday dates from the settings (one per line, dd/mm/yyyy or yyyy-mm-dd)."""
    out = set()
    for line in (db.setting("holidays") or "").replace("،", "\n").replace(",", "\n").splitlines():
        t = line.strip()
        try:
            out.add(date.fromisoformat(t) if "-" in t else date(*map(int, reversed(t.split("/")))))
        except (ValueError, TypeError):
            continue
    return out


def stage_end(db, cycle, stage):
    """Last day whose receipts count for a stage: the stage day counted from Day 1 (1 Oct + 7 → 7 Oct), in working
    days when the setting is on (weekend and holidays skipped)."""
    from datetime import timedelta
    start = date.fromisoformat(cycle_start(db, cycle))
    n = int(db.setting_num(STAGE_DAYS[stage]))
    if db.setting("workdays") != "1":
        return (start + timedelta(days=n - 1)).isoformat()
    weekend = {int(x) for x in (db.setting("weekend") or "").split(",") if x.strip().isdigit()}
    off = holidays(db)
    d, count = start, 0
    while True:
        if d.weekday() not in weekend and d not in off:
            count += 1
            if count >= n:
                return d.isoformat()
        d += timedelta(days=1)


def add_receipts(db, folder, cycle, recs, path, start="", end=""):
    """Store the receipts of one file dated within [start, end]; the others are left for their own stage
    (re-uploading later never counts a voucher twice). Returns counts for the screen."""
    before = [r for r in recs if start and r.date < start]
    after = [r for r in recs if end and r.date > end]
    recs = [r for r in recs if (not start or r.date >= start) and (not end or r.date <= end)]
    dest = folder.files_dir(cycle["month"], "receipts")
    target = os.path.join(dest, safe_name(os.path.basename(path)))
    if os.path.abspath(path) != os.path.abspath(target):
        shutil.copy2(path, target)
    rel = os.path.relpath(target, folder.path)
    added = db.add_receipts(cycle["id"], recs, rel)
    required = {c["code"] for c in db.cycle_customers(cycle["id"], required_only=True)}
    outside = sorted({r.code for r in recs if r.code not in required})
    recompute_paid(db, cycle, start, end)
    db.log("رفع سندات قبض", f"{os.path.basename(path)}: {added} سند جديد بمبلغ "
                           f"{sum(r.amount for r in recs):,.2f}" + (f" (الفترة {start} — {end})" if end else ""),
           cycle_id=cycle["id"])
    return {"added": added, "duplicates": len(recs) - added, "outside": outside,
            "total": sum(r.amount for r in recs if r.code in required), "before": len(before), "after": len(after),
            "count": len(recs)}


def recompute_paid(db, cycle, start="", end=""):
    """Paid = receipts dated within the period up to the end of the selected stage (cumulative from Day 1)."""
    paid = db.paid_by_code(cycle["id"], start, end)
    for c in db.cycle_customers(cycle["id"]):
        p = paid.get(c["code"], 0.0)
        base = c["overdue"] or 0
        pct = p / base if base > 0.005 else (1.0 if p > 0 else 0.0)
        db.update_cycle_customer(cycle["id"], c["code"], commit=False, paid=p, pct=pct)
    db.commit()
    refresh_status(db, cycle)


# ------------------------------------------------------------------ exclusion
def exclude(db, cycle, code, reason):
    db.update_cycle_customer(cycle["id"], code, excluded=1, exclude_reason=reason)
    db.log("استبعاد من الإجراءات", reason, code=code, cycle_id=cycle["id"])
    refresh_status(db, cycle, {code})


def include(db, cycle, code):
    db.update_cycle_customer(cycle["id"], code, excluded=0, exclude_reason="")
    db.log("إلغاء الاستبعاد", "", code=code, cycle_id=cycle["id"])
    refresh_status(db, cycle, {code})


# ------------------------------------------------------------------ letters
def remaining(c, mode="remaining"):
    """Default letter amount: overdue left after the receipts, or the whole balance left (setting letter_amount)."""
    r = (c["overdue"] or 0) - (c["paid"] or 0)
    if mode == "balance" or r <= 0.005:
        r = (c["balance"] or 0) - (c["paid"] or 0)
    return round(max(r, 0.0), 2)


def candidates(db, cycle, stage):
    """Customers at the level before this stage, with eligible flag, reason, letter kind and default amount."""
    level = STAGES[stage][0]
    thr, neg = threshold(db, stage), negotiating_codes(db)
    unmatched_rule = db.setting("letter_unmatched") == "1"
    min_letter = db.setting_num("min_letter")
    mode = db.setting("letter_amount")
    masters = db.customers()
    out = []
    for c in db.cycle_customers(cycle["id"], required_only=True):
        if (c["level"] or 0) != level - 1:
            continue
        m = masters.get(c["code"], {})
        pct = c["pct"] or 0
        reasons, eligible = [], True
        amount = remaining(c, mode)
        if c["code"] in neg:
            eligible, reasons = False, ["تحت التفاوض"]
        elif m.get("perm_exclude"):
            eligible, reasons = False, [f"استثناء دائم: {m.get('perm_reason') or ''}"]
        elif c["excluded"]:
            eligible, reasons = False, [f"مستبعد: {c['exclude_reason']}"]
        elif pct >= thr:
            if stage == "finance" and unmatched_rule and c["matched"] != 1:
                reasons = [f"سدد {pct * 100:.0f}% لكن لم يطابق"]
            else:
                eligible, reasons = False, [f"سدد {pct * 100:.0f}%"]
        else:
            reasons.append("لم يسدد" if pct <= 0 else f"سدد {pct * 100:.0f}% فقط")
            if stage == "finance" and c["matched"] != 1:
                reasons.append("غير مطابق" if c["matched"] == 0 else "لم يرجع الكشف موقعًا")
            if min_letter and amount < min_letter:
                eligible = False
                reasons.append(f"المبلغ المتبقي أقل من حد الخطاب ({min_letter:,.0f})")
        if stage == "finance":
            kind = "1003"
        elif stage == "legal":
            kind = "1004PN" if m.get("has_pn") else "1004"
        else:
            kind = "1005" if c["pn_letter"] else "1006"
        row = dict(c)
        row.update(eligible=eligible, reason="، ".join(reasons), kind=kind, amount=amount,
                   cr_no=m.get("cr_no", ""), has_pn=m.get("has_pn"), pn_no=m.get("pn_no", ""))
        if kind == "1005" and not m.get("pn_no"):
            row["reason"] += "، ⚠ رقم السند لأمر غير مسجل في بيانات العميل"
        out.append(row)
    out.sort(key=lambda r: (not r["eligible"], -(r["amount"] or 0)))
    return out


def letterhead(db, folder):
    return L.Letterhead(db.setting("company"), folder.asset("logo.png"), db.setting("letter_footer"))


def images(folder):
    return {"الختم": folder.asset("stamp.png"), "التوقيع": folder.asset("signature.png")}


def render_letter(db, folder, kind, cust, amount, serial, date_iso, prev, out_path, extra=None):
    tpl = db.template(kind)
    values = L.letter_values(db, cust, amount, serial, date_iso, prev, extra)
    body = L.merge(tpl["html"], values, images(folder))
    L.write_pdf([body], out_path, letterhead(db, folder), title=serial)
    return out_path


def issue(db, folder, cycle, items, date_iso=None, stage=None):
    """items: [{code, kind, amount}]. Writes one PDF per letter, grouped by rep, plus one printable PDF and
    one ZIP per rep. Returns packages [{rep, email, rep_record, letters, dir, zip, combined}]."""
    date_iso = date_iso or date.today().isoformat()
    masters = db.customers()
    base = folder.files_dir(cycle["month"], "letters")
    by_rep = {}
    for it in items:
        c = db.cycle_customer(cycle["id"], it["code"])
        cust = dict(masters.get(it["code"], {}))
        cust.update(code=c["code"], name=c["name"] or cust.get("name", ""), rep_name=c["rep_name"])
        rep = db.rep_for(c["rep_name"]) if c["rep_name"] else None
        key = rep["name"] if rep else f"بدون مندوب ({c['rep_name'] or '—'})"
        kind = it["kind"]
        prev = db.last_letter(c["code"])
        serial = db.next_serial(kind)
        out_dir = os.path.join(base, f"{kind[:4]} {KIND_NAMES[kind]}", safe_name(key))
        pdf = os.path.join(out_dir, f"{c['code']} - {safe_name(c['name'])} - {safe_name(serial)}.pdf")
        try:
            render_letter(db, folder, kind, cust, it["amount"], serial, date_iso, prev, pdf)
            db.add_letter(serial, kind, c["code"], cycle["id"], date_iso, it["amount"],
                          os.path.relpath(pdf, folder.path), prev["serial"] if prev else "", c["rep_name"])
            fields = {"level": LEVEL_OF_KIND[kind]}
            if kind == "1004PN":
                fields["pn_letter"] = 1
            db.update_cycle_customer(cycle["id"], c["code"], commit=False, **fields)
            db.log("إصدار خطاب", f"{serial} — {KIND_NAMES[kind]} — {it['amount']:,.2f}", code=c["code"],
                   cycle_id=cycle["id"])   # commits the letter, serial and level together
        except Exception:
            db.con.rollback()   # the serial is not consumed when the letter could not be written
            raise
        e = by_rep.setdefault(key, {"rep": key, "email": rep["email"] if rep else "", "rep_record": rep,
                                    "letters": [], "dir": out_dir})
        e["letters"].append({"code": c["code"], "name": c["name"], "serial": serial, "kind": kind,
                             "amount": it["amount"], "pdf": pdf})
    refresh_status(db, cycle, {it["code"] for it in items})
    return package(db, folder, cycle, by_rep, date_iso)


def package(db, folder, cycle, by_rep, date_iso):
    from pypdf import PdfReader, PdfWriter
    zips = folder.files_dir(cycle["month"], "letters", "zips")
    out = []
    for key, e in sorted(by_rep.items()):
        w = PdfWriter()
        for l in e["letters"]:
            for page in PdfReader(l["pdf"]).pages:
                w.add_page(page)
        stamp = date_iso.replace("-", "")
        combined = os.path.join(zips, f"{safe_name(key)} - خطابات {stamp} (للطباعة).pdf")
        with open(combined, "wb") as f:
            w.write(f)
        zpath = os.path.join(zips, f"{safe_name(key)} - خطابات {stamp}.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for l in e["letters"]:
                z.write(l["pdf"], os.path.basename(l["pdf"]))
        e["zip"], e["combined"] = zpath, combined
        out.append(e)
    return out


def cancel_letter(db, cycle_id, serial, reason):
    """Cancelled letters keep their serial (status ملغي); the customer goes back to its previous level."""
    db.cancel_letter(serial, reason)
    row = db.con.execute("SELECT code, cycle_id FROM letters WHERE serial=?", (serial,)).fetchone()
    if not row:
        return
    code, cid = row[0], row[1] or cycle_id
    active = [l for l in db.letters(code=code, cycle_id=cid) if l["status"] != "ملغي" and l["kind"] in LEVEL_OF_KIND]
    level = max((LEVEL_OF_KIND[l["kind"]] for l in active), default=0)
    pn = 1 if any(l["kind"] == "1004PN" for l in active) else 0
    db.update_cycle_customer(cid, code, level=level, pn_letter=pn)
    db.log("إلغاء خطاب", f"{serial}: {reason}", code=code, cycle_id=cid)
    cyc = db.con.execute("SELECT * FROM cycles WHERE id=?", (cid,)).fetchone()
    if cyc:
        refresh_status(db, dict(cyc), {code})


def stop_sale(db, cycle):
    """Customers that must not be sold to (legal letter issued and still below the threshold)."""
    thr, neg = threshold(db, "legal"), negotiating_codes(db)
    return [c for c in db.cycle_customers(cycle["id"], required_only=True)
            if (c["level"] or 0) >= 2 and (c["pct"] or 0) < thr and not c["excluded"] and c["code"] not in neg]


# ------------------------------------------------------------------ negotiation (form 1002)
def start_negotiation(db, folder, cycle, code, data, date_iso=None):
    """data: amount, rep (customer representative), title, id_no, option (1 instalments / 2 cash 130%),
    inst: [(amount, iso date)] up to 4."""
    date_iso = date_iso or date.today().isoformat()
    cust = dict(db.customer(code) or {"code": code})
    c = db.cycle_customer(cycle["id"], code) if cycle else None
    if c:
        cust.update(name=c["name"] or cust.get("name", ""), rep_name=c["rep_name"])
    extra = {"الممثل": data.get("rep", ""), "الصفة": data.get("title", ""), "رقم_الهوية": data.get("id_no", ""),
             "خيار_الأقساط": "✔" if data.get("option", 1) == 1 else "  ",
             "خيار_النقدي": "✔" if data.get("option", 1) == 2 else "  "}
    inst = list(data.get("inst") or [])
    for i in range(4):
        a, d = inst[i] if i < len(inst) else (None, "")
        extra[f"القسط{i + 1}_مبلغ"] = L.money(a) if a else "________"
        extra[f"القسط{i + 1}_تاريخ"] = L.fmt_date(d) if d else "____/____/2026"
    serial = db.next_serial("1002")
    month = cycle["month"] if cycle else date_iso[:7]
    pdf = os.path.join(folder.files_dir(month, "letters", "1002 اتفاقيات التسوية"),
                       f"{code} - {safe_name(cust.get('name', ''))} - {safe_name(serial)}.pdf")
    try:
        render_letter(db, folder, "1002", cust, data["amount"], serial, date_iso, db.last_letter(code), pdf, extra)
        db.add_letter(serial, "1002", code, cycle["id"] if cycle else None, date_iso, data["amount"],
                      os.path.relpath(pdf, folder.path), "", cust.get("rep_name", ""))
        db.commit()
    except Exception:
        db.con.rollback()
        raise
    db.add_negotiation(code, cycle["id"] if cycle else None, data["amount"], data, serial,
                       os.path.relpath(pdf, folder.path))
    db.log("بدء تفاوض", f"{serial} — {data['amount']:,.2f}", code=code, cycle_id=cycle["id"] if cycle else None)
    if cycle:
        refresh_status(db, cycle, {code})
    return pdf


def close_negotiation(db, cycle, nid, kept, note=""):
    """kept=True: the customer honoured the agreement (leaves the cycle).
    kept=False («لم يلتزم»): back to the stages from the last letter sent."""
    n = next((x for x in db.negotiations() if x["id"] == nid), None)
    if not n:
        return
    db.close_negotiation(nid, "التزم" if kept else "لم يلتزم", note)
    if cycle and kept:
        db.update_cycle_customer(cycle["id"], n["code"], excluded=1,
                                 exclude_reason=f"التزم باتفاقية التسوية {n['serial']}")
    db.log("إنهاء تفاوض", ("التزم" if kept else "لم يلتزم — يرجع للمراحل") + (f" — {note}" if note else ""),
           code=n["code"], cycle_id=cycle["id"] if cycle else None)
    if cycle:
        refresh_status(db, cycle, {n["code"]})


def late_instalments(db, today=None):
    """Active negotiations whose instalments due by today are not covered by receipts since the agreement."""
    today = (today or date.today()).isoformat()
    out = []
    for n in db.negotiations(active_only=True):
        inst = [(a or 0, d) for a, d in (n["data"].get("inst") or []) if d]
        due = sum(a for a, d in inst if d <= today)
        if due <= 0:
            continue
        since = n["created"][:10]
        paid = db.con.execute("SELECT COALESCE(SUM(amount),0) FROM receipts WHERE code=? AND date>=?",
                              (n["code"], since)).fetchone()[0]
        if paid + 0.5 < due:
            nxt = next((d for a, d in sorted(inst, key=lambda x: x[1]) if d > today), "")
            out.append({"id": n["id"], "code": n["code"], "name": n["name"], "due": due, "paid": paid, "next": nxt})
    return out
