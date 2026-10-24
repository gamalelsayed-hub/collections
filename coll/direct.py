"""Customers who neither matched nor paid the threshold: a data update form (to get the customer's official
e-mail, signed), then the statement sent to the customer directly instead of through the rep. No reply within
the set days (7 by default) counts as acceptance: the customer is considered matched and the stages continue."""
import os
from datetime import date, timedelta

from . import stages as S
from .day1 import safe_name
from .letters import fmt_date, money


def candidates(db, cycle):
    """Required customers not matched and below the finance threshold (not excluded / negotiating)."""
    thr, neg = S.threshold(db, "finance"), S.negotiating_codes(db)
    masters = db.customers()
    days = int(db.setting_num("confirm_days"))
    out = []
    for c in db.cycle_customers(cycle["id"], required_only=True):
        m = masters.get(c["code"], {})
        if c["matched"] == 1 or c["excluded"] or c["code"] in neg or m.get("perm_exclude"):
            continue
        if (c["pct"] or 0) >= thr:
            continue
        r = dict(c)
        r["email"] = (m.get("email") or "").strip()
        r["state"] = state(c, days)
        out.append(r)
    out.sort(key=lambda r: -(r["overdue"] or 0))
    return out


def deadline(sent_iso, days):
    return (date.fromisoformat(sent_iso) + timedelta(days=days)).isoformat()


def state(c, days):
    if c.get("matched") == 0:
        return "غير مطابق" + (f": {c['match_reason']}" if c.get("match_reason") else "")
    if c.get("direct_sent"):
        end = deadline(c["direct_sent"], days)
        left = (date.fromisoformat(end) - date.today()).days
        return f"أُرسلت المصادقة للعميل {fmt_date(c['direct_sent'])} — " + (
            f"باقي {left} يوم (حتى {fmt_date(end)})" if left > 0 else "انتهت المهلة")
    if c.get("upd_serial"):
        return f"صدر نموذج تحديث البيانات {c['upd_serial']} — بانتظار إيميل العميل"
    return "لم يصدر نموذج تحديث البيانات"


def issue_forms(db, folder, cycle, codes, date_iso=None):
    """Data update form (SL-26-1005) per customer, grouped by rep (one printable PDF and one ZIP per rep)."""
    date_iso = date_iso or date.today().isoformat()
    masters = db.customers()
    base = folder.files_dir(cycle["month"], "letters")
    by_rep = {}
    for code in codes:
        c = db.cycle_customer(cycle["id"], code)
        cust = dict(masters.get(code, {}))
        cust.update(code=code, name=c["name"] or cust.get("name", ""), rep_name=c["rep_name"])
        rep = db.rep_for(c["rep_name"]) if c["rep_name"] else None
        key = rep["name"] if rep else f"بدون مندوب ({c['rep_name'] or '—'})"
        serial = db.next_serial("UPD")
        out_dir = os.path.join(base, "1005 نموذج تحديث بيانات", safe_name(key))
        pdf = os.path.join(out_dir, f"{code} - {safe_name(c['name'])} - {safe_name(serial)}.pdf")
        try:
            S.render_letter(db, folder, "UPD", cust, c["balance"] or 0, serial, date_iso, None, pdf)
            db.add_letter(serial, "UPD", code, cycle["id"], date_iso, c["balance"] or 0,
                          os.path.relpath(pdf, folder.path), "", c["rep_name"])
            db.update_cycle_customer(cycle["id"], code, commit=False, upd_serial=serial, upd_date=date_iso)
            db.log("نموذج تحديث بيانات", serial, code=code, cycle_id=cycle["id"])
        except Exception:
            db.con.rollback()
            raise
        e = by_rep.setdefault(key, {"rep": key, "email": rep["email"] if rep else "", "rep_record": rep,
                                    "letters": [], "dir": out_dir})
        e["letters"].append({"code": code, "name": c["name"], "serial": serial, "kind": "UPD", "amount": 0,
                             "pdf": pdf})
    return S.package(db, folder, cycle, by_rep, date_iso)


def mails(db, folder, cycle, codes, today=None):
    """One e-mail per customer to his own address, with his statement. Returns (mails, problems)."""
    today = today or date.today().isoformat()
    days = int(db.setting_num("confirm_days"))
    masters = db.customers()
    month = cycle["month"]
    out, problems = [], []
    for code in codes:
        c = db.cycle_customer(cycle["id"], code)
        email = (masters.get(code, {}).get("email") or "").strip()
        stmt = os.path.join(folder.path, c["statement"]) if c.get("statement") else ""
        if not email:
            problems.append(f"{code} {c['name']}: لا يوجد إيميل للعميل")
            continue
        if not stmt or not os.path.exists(stmt):
            problems.append(f"{code} {c['name']}: لا يوجد كشف حساب جاهز لهذه الدورة")
            continue
        values = {"name": c["name"], "code": code, "balance": money(c["stmt_balance"] if c["stmt_balance"] is not None
                                                                      else c["balance"]),
                  "days": days, "deadline": fmt_date(deadline(today, days)), "month": month,
                  "company": db.setting("company") or ""}
        out.append({"rep": f"{code} — {c['name']}", "to": email, "code": code,
                    "subject": _fill(db.setting("direct_subject"), values),
                    "body": _fill(db.setting("direct_body"), values), "files": [stmt], "count": "كشف حساب"})
    return out, problems


def _fill(text, values):
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def mark_sent(db, cycle, code, to, today=None):
    today = today or date.today().isoformat()
    db.update_cycle_customer(cycle["id"], code, direct_sent=today, direct_to=to)
    db.log("مصادقة مباشرة", f"أُرسل كشف الحساب للعميل على {to}", code=code, cycle_id=cycle["id"])
    S.refresh_status(db, cycle, {code})


def apply_silent_acceptance(db, cycle, today=None):
    """Customers who got the statement directly and did not reply within the days: matched.
    Returns [(code, name)]."""
    today = today or date.today().isoformat()
    days = int(db.setting_num("confirm_days"))
    done = []
    for c in db.cycle_customers(cycle["id"], required_only=True):
        if not c.get("direct_sent") or c["matched"] is not None:
            continue
        if today >= deadline(c["direct_sent"], days):
            note = (f"اعتُبر مطابقًا لعدم الرد خلال {days} أيام من إرسال المصادقة بتاريخ {fmt_date(c['direct_sent'])}"
                    f" إلى {c['direct_to']}")
            db.update_cycle_customer(cycle["id"], c["code"], commit=False, matched=1, match_reason=note)
            db.log("مطابقة (عدم رد)", note, code=c["code"], cycle_id=cycle["id"])
            done.append((c["code"], c["name"]))
    db.commit()
    if done:
        S.refresh_status(db, cycle, {c for c, _ in done})
    return done
