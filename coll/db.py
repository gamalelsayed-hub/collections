"""Database: customers, reps, monthly cycles, events log, letters and serials."""
import hashlib
import json
import sqlite3
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY, password TEXT DEFAULT '', active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS reps(
    id INTEGER PRIMARY KEY, emp_no TEXT, name TEXT, email TEXT, branch TEXT, title TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS rep_alias(alias TEXT PRIMARY KEY, rep_id INTEGER);
CREATE TABLE IF NOT EXISTS customers(
    code TEXT PRIMARY KEY, name TEXT, cr_no TEXT DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '',
    region TEXT DEFAULT '', branch TEXT DEFAULT '', rep_name TEXT DEFAULT '', ctype TEXT DEFAULT '', cls TEXT DEFAULT '',
    has_pn INTEGER DEFAULT 0, pn_no TEXT DEFAULT '', pn_value REAL, pn_date TEXT DEFAULT '', notes TEXT DEFAULT '',
    updated TEXT);
CREATE TABLE IF NOT EXISTS cycles(
    id INTEGER PRIMARY KEY, month TEXT UNIQUE, created TEXT, aging_file TEXT, aging_date TEXT);
CREATE TABLE IF NOT EXISTS cycle_customers(
    cycle_id INTEGER, code TEXT, name TEXT, rep_name TEXT, types TEXT, balance REAL, overdue REAL,
    b0 REAL, b1 REAL, b2 REAL, b3 REAL, b4 REAL, required INTEGER, status TEXT DEFAULT '',
    statement TEXT DEFAULT '', stmt_balance REAL, stmt_detail TEXT DEFAULT '', warning TEXT DEFAULT '',
    PRIMARY KEY(cycle_id, code));
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY, ts TEXT, user TEXT, cycle_id INTEGER, code TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS letters(
    id INTEGER PRIMARY KEY, serial TEXT UNIQUE, kind TEXT, code TEXT, cycle_id INTEGER, date TEXT, amount REAL,
    pdf TEXT, status TEXT DEFAULT 'صادر', prev_serial TEXT DEFAULT '', user TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS serials(kind TEXT, year INTEGER, last INTEGER, PRIMARY KEY(kind, year));
CREATE TABLE IF NOT EXISTS column_maps(kind TEXT PRIMARY KEY, mapping TEXT);
CREATE TABLE IF NOT EXISTS stmt_sections(
    cycle_id INTEGER, code TEXT, account TEXT, account_name TEXT, name TEXT, source TEXT, pages TEXT,
    balance REAL, mode TEXT, uploaded TEXT, PRIMARY KEY(cycle_id, code, account));
CREATE TABLE IF NOT EXISTS templates(kind TEXT PRIMARY KEY, html TEXT, serial_format TEXT, updated TEXT, user TEXT);
CREATE TABLE IF NOT EXISTS receipts(
    cycle_id INTEGER, voucher TEXT, date TEXT, code TEXT, name TEXT, account TEXT, amount REAL, source TEXT,
    uploaded TEXT, PRIMARY KEY(cycle_id, voucher, code, amount));
CREATE TABLE IF NOT EXISTS negotiations(
    id INTEGER PRIMARY KEY, code TEXT, cycle_id INTEGER, created TEXT, amount REAL, data TEXT,
    status TEXT DEFAULT 'جاري', serial TEXT DEFAULT '', pdf TEXT DEFAULT '', user TEXT, closed TEXT DEFAULT '',
    note TEXT DEFAULT '');
"""

# columns added after the first release (added to existing databases on open)
MIGRATIONS = [
    ("cycle_customers", "matched", "INTEGER"),            # 1 matched, 0 not matched, NULL not returned yet
    ("cycle_customers", "signed", "TEXT DEFAULT ''"),
    ("cycle_customers", "paid", "REAL DEFAULT 0"),
    ("cycle_customers", "pct", "REAL DEFAULT 0"),
    ("cycle_customers", "excluded", "INTEGER DEFAULT 0"),
    ("cycle_customers", "exclude_reason", "TEXT DEFAULT ''"),
    ("cycle_customers", "level", "INTEGER DEFAULT 0"),    # 1 finance letter, 2 legal letter, 3 legal action
    ("cycle_customers", "pn_letter", "INTEGER DEFAULT 0"),  # legal letter was the promissory-note version
    ("cycle_customers", "carried", "TEXT DEFAULT ''"),
    ("letters", "rep_name", "TEXT DEFAULT ''"),
    ("letters", "cancel_reason", "TEXT DEFAULT ''"),
]
EXTRA_CYCLE_FIELDS = ["matched", "signed", "paid", "pct", "excluded", "exclude_reason", "level", "pn_letter", "carried"]

DEFAULTS = {
    "company": "شركة أدوات التعمير التجارية",
    "custody_days": "30",
    "credit_days": "60",
    "pay_threshold": "0.7",
    "day_statements": "1",
    "day_finance": "7",
    "day_legal": "14",
    "day_action": "21",
    "require_password": "0",
    "company_cr": "4030093636",
    "contact_mobile": "",
    "contact_email": "",
    "letter_footer": "",
    "letter_unmatched": "0",
    "mail_subject": "كشوف حسابات العملاء المطلوب مطابقتهم — {month}",
    "mail_body": ("الأستاذ/ {rep} المحترم،\n\nمرفق كشوف حسابات عملائك المطلوب مطابقتهم لشهر {month} "
                  "({count} عميل).\nنرجو مطابقتها مع العملاء وإعادتها موقعة ومختومة.\n\nمع الشكر،\n"
                  "الإدارة المالية — قسم التحصيل والائتمان"),
}

CYCLE_FIELDS = ["code", "name", "rep_name", "types", "balance", "overdue", "b0", "b1", "b2", "b3", "b4", "required",
                "status", "statement", "stmt_balance", "stmt_detail", "warning"]
CUSTOMER_FIELDS = ["code", "name", "cr_no", "phone", "email", "region", "branch", "rep_name", "ctype", "cls",
                   "has_pn", "pn_no", "pn_value", "pn_date", "notes"]


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_password(pw):
    return hashlib.sha256(("coll:" + pw).encode("utf-8")).hexdigest() if pw else ""


class DB:
    def __init__(self, path, user=""):
        self.path = path
        self.user = user
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        for table, col, decl in MIGRATIONS:
            cols = {r[1] for r in self.con.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                self.con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        self.con.commit()

    def close(self):
        self.con.close()

    # ---------------- settings
    def setting(self, key):
        r = self.con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else DEFAULTS.get(key, "")

    def setting_num(self, key):
        try:
            return float(self.setting(key))
        except (TypeError, ValueError):
            return float(DEFAULTS[key])

    def set_setting(self, key, value):
        self.con.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, str(value)))
        self.con.commit()

    def column_map(self, kind):
        r = self.con.execute("SELECT mapping FROM column_maps WHERE kind=?", (kind,)).fetchone()
        return json.loads(r[0]) if r else None

    def save_column_map(self, kind, mapping):
        self.con.execute("INSERT OR REPLACE INTO column_maps VALUES(?,?)", (kind, json.dumps(mapping)))
        self.con.commit()

    # ---------------- users
    def users(self):
        return [dict(r) for r in self.con.execute("SELECT name, password, active FROM users ORDER BY name")]

    def save_user(self, name, password=None):
        if password is None:
            self.con.execute("INSERT OR IGNORE INTO users(name) VALUES(?)", (name,))
        else:
            self.con.execute("INSERT OR REPLACE INTO users(name, password, active) VALUES(?,?,1)",
                             (name, hash_password(password)))
        self.con.commit()

    def check_password(self, name, password):
        r = self.con.execute("SELECT password FROM users WHERE name=?", (name,)).fetchone()
        return bool(r) and (not r[0] or r[0] == hash_password(password))

    # ---------------- log
    def log(self, kind, detail="", code="", cycle_id=None):
        self.con.execute("INSERT INTO events(ts, user, cycle_id, code, kind, detail) VALUES(?,?,?,?,?,?)",
                         (now(), self.user, cycle_id, code, kind, detail))
        self.con.commit()

    def events(self, code=None, limit=2000):
        q = "SELECT ts, user, cycle_id, code, kind, detail FROM events"
        args = ()
        if code:
            q += " WHERE code=?"
            args = (code,)
        q += " ORDER BY id DESC LIMIT ?"
        return [dict(r) for r in self.con.execute(q, args + (limit,))]

    # ---------------- reps
    def reps(self, active_only=False):
        q = "SELECT * FROM reps" + (" WHERE active=1" if active_only else "") + " ORDER BY name"
        return [dict(r) for r in self.con.execute(q)]

    def save_rep(self, rep):
        if rep.get("id"):
            self.con.execute("UPDATE reps SET emp_no=?, name=?, email=?, branch=?, title=?, active=? WHERE id=?",
                             (rep.get("emp_no", ""), rep["name"], rep.get("email", ""), rep.get("branch", ""),
                              rep.get("title", ""), int(rep.get("active", 1)), rep["id"]))
            rid = rep["id"]
        else:
            cur = self.con.execute("INSERT INTO reps(emp_no, name, email, branch, title, active) VALUES(?,?,?,?,?,?)",
                                   (rep.get("emp_no", ""), rep["name"], rep.get("email", ""), rep.get("branch", ""),
                                    rep.get("title", ""), int(rep.get("active", 1))))
            rid = cur.lastrowid
        self.con.commit()
        return rid

    def delete_rep(self, rid):
        self.con.execute("DELETE FROM reps WHERE id=?", (rid,))
        self.con.execute("DELETE FROM rep_alias WHERE rep_id=?", (rid,))
        self.con.commit()

    def aliases(self):
        return {r[0]: r[1] for r in self.con.execute("SELECT alias, rep_id FROM rep_alias")}

    def set_alias(self, alias, rep_id):
        if rep_id:
            self.con.execute("INSERT OR REPLACE INTO rep_alias VALUES(?,?)", (alias, rep_id))
        else:
            self.con.execute("DELETE FROM rep_alias WHERE alias=?", (alias,))
        self.con.commit()

    def rep_for(self, rep_name):
        """The rep record behind a name as written in the aging report / custody account."""
        from .textutil import norm
        aliases = {norm(k): v for k, v in self.aliases().items()}
        rid = aliases.get(norm(rep_name))
        if rid:
            r = self.con.execute("SELECT * FROM reps WHERE id=?", (rid,)).fetchone()
            return dict(r) if r else None
        return None

    # ---------------- customers
    def customers(self):
        return {r["code"]: dict(r) for r in self.con.execute("SELECT * FROM customers")}

    def customer(self, code):
        r = self.con.execute("SELECT * FROM customers WHERE code=?", (code,)).fetchone()
        return dict(r) if r else None

    def save_customer(self, c):
        fields = CUSTOMER_FIELDS + ["updated"]
        vals = [c.get(f, "") if f not in ("has_pn", "pn_value") else c.get(f) for f in CUSTOMER_FIELDS] + [now()]
        self.con.execute(f"INSERT OR REPLACE INTO customers({', '.join(fields)}) VALUES({','.join('?' * len(fields))})",
                         vals)
        self.con.commit()

    def upsert_from_aging(self, rows):
        """Add new customers and refresh name/branch/rep/type from the aging report.
        Returns (new codes, [(code, old rep, new rep)])."""
        existing = self.customers()
        new, moved = [], []
        for r in rows:
            c = existing.get(r["code"])
            if c is None:
                c = {f: "" for f in CUSTOMER_FIELDS}
                c.update(code=r["code"], has_pn=0, pn_value=None)
                new.append(r["code"])
            elif r.get("rep_name") and c.get("rep_name") and c["rep_name"] != r["rep_name"]:
                moved.append((r["code"], c["rep_name"], r["rep_name"]))
            for f in ("name", "region", "branch", "rep_name", "ctype", "cls"):
                if r.get(f):
                    c[f] = r[f]
            existing[r["code"]] = c
            self.save_customer(c)
        return new, moved

    # ---------------- cycles
    def cycles(self):
        return [dict(r) for r in self.con.execute("SELECT * FROM cycles ORDER BY month DESC")]

    def cycle(self, month):
        r = self.con.execute("SELECT * FROM cycles WHERE month=?", (month,)).fetchone()
        return dict(r) if r else None

    def create_cycle(self, month, aging_file, aging_date, rows):
        """rows: dicts with CYCLE_FIELDS. Replaces the cycle's customer list if it exists."""
        cyc = self.cycle(month)
        keep = {}
        if cyc:
            cid = cyc["id"]
            keep = {c["code"]: c for c in self.cycle_customers(cid)}
            self.con.execute("UPDATE cycles SET aging_file=?, aging_date=? WHERE id=?", (aging_file, aging_date, cid))
            self.con.execute("DELETE FROM cycle_customers WHERE cycle_id=?", (cid,))
        else:
            prev = self.con.execute("SELECT * FROM cycles WHERE month<? ORDER BY month DESC LIMIT 1", (month,)).fetchone()
            cid = self.con.execute("INSERT INTO cycles(month, created, aging_file, aging_date) VALUES(?,?,?,?)",
                                   (month, now(), aging_file, aging_date)).lastrowid
            if prev:
                # customers still inside the letters stages continue from their last letter
                thr = self.setting_num("pay_threshold")
                for c in self.cycle_customers(prev["id"]):
                    if c["level"] and not c["excluded"] and (c["pct"] or 0) < thr:
                        keep[c["code"]] = {"level": c["level"], "pn_letter": c["pn_letter"],
                                           "carried": f"مستمر من دورة {prev['month']}"}
        self.con.executemany(
            f"INSERT INTO cycle_customers(cycle_id, {', '.join(CYCLE_FIELDS)}) VALUES({','.join('?' * (len(CYCLE_FIELDS) + 1))})",
            [(cid,) + tuple(r.get(f, "" if f in ("status", "statement", "stmt_detail", "warning") else None)
                            for f in CYCLE_FIELDS) for r in rows])
        for code, old in keep.items():
            fields = {f: old[f] for f in EXTRA_CYCLE_FIELDS if f in old}
            if cyc and old.get("status") not in (None, "", "مطلوب مطابقة"):
                fields["status"] = old["status"]   # same month re-uploaded: keep the follow-up status
            if fields:
                self.update_cycle_customer(cid, code, commit=False, **fields)
        self.con.commit()
        return cid

    def cycle_customers(self, cycle_id, required_only=False):
        q = "SELECT * FROM cycle_customers WHERE cycle_id=?" + (" AND required=1" if required_only else "")
        return [dict(r) for r in self.con.execute(q + " ORDER BY overdue DESC", (cycle_id,))]

    # ---------------- statement sections
    def save_section(self, cycle_id, sec, mode, source_copy):
        self.con.execute("INSERT OR REPLACE INTO stmt_sections VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (cycle_id, sec.code, sec.account, sec.account_name, sec.name, source_copy,
                          json.dumps(sec.pages), sec.balance, mode, now()))

    def sections(self, cycle_id):
        out = {}
        for r in self.con.execute("SELECT * FROM stmt_sections WHERE cycle_id=? ORDER BY code, account", (cycle_id,)):
            d = dict(r)
            d["pages"] = json.loads(d["pages"])
            out.setdefault(d["code"], []).append(d)
        return out

    def clear_sections(self, cycle_id):
        self.con.execute("DELETE FROM stmt_sections WHERE cycle_id=?", (cycle_id,))
        self.con.commit()

    def commit(self):
        self.con.commit()

    def update_cycle_customer(self, cycle_id, code, commit=True, **fields):
        sets = ", ".join(f"{k}=?" for k in fields)
        self.con.execute(f"UPDATE cycle_customers SET {sets} WHERE cycle_id=? AND code=?",
                         tuple(fields.values()) + (cycle_id, code))
        if commit:
            self.con.commit()

    def cycle_customer(self, cycle_id, code):
        r = self.con.execute("SELECT * FROM cycle_customers WHERE cycle_id=? AND code=?", (cycle_id, code)).fetchone()
        return dict(r) if r else None

    # ---------------- templates & serials
    def template(self, kind):
        from .templates import DEFAULTS, SERIAL_FORMATS
        r = self.con.execute("SELECT html, serial_format FROM templates WHERE kind=?", (kind,)).fetchone()
        return {"kind": kind, "html": r[0] if r and r[0] else DEFAULTS[kind],
                "serial_format": r[1] if r and r[1] else SERIAL_FORMATS[kind], "custom": bool(r)}

    def save_template(self, kind, html, serial_format):
        self.con.execute("INSERT OR REPLACE INTO templates VALUES(?,?,?,?,?)", (kind, html, serial_format, now(), self.user))
        self.con.commit()

    def reset_template(self, kind):
        self.con.execute("DELETE FROM templates WHERE kind=?", (kind,))
        self.con.commit()

    def next_serial(self, kind):
        """Reserve the next serial of a letter type (never reused, even if the letter is cancelled)."""
        from .templates import COUNTER
        key = COUNTER.get(kind, kind)
        r = self.con.execute("SELECT last FROM serials WHERE kind=? AND year=0", (key,)).fetchone()
        n = (r[0] if r else 0) + 1
        self.con.execute("INSERT OR REPLACE INTO serials VALUES(?,0,?)", (key, n))
        fmt = self.template(kind)["serial_format"]
        serial = fmt.replace("{رقم}", f"{n:04d}").replace("{السنة}", datetime.now().strftime("%Y"))
        if serial == fmt:
            serial = f"{fmt}-{n:04d}"
        return serial

    def serial_counter(self, kind):
        from .templates import COUNTER
        r = self.con.execute("SELECT last FROM serials WHERE kind=? AND year=0", (COUNTER.get(kind, kind),)).fetchone()
        return r[0] if r else 0

    def set_serial_counter(self, kind, last):
        from .templates import COUNTER
        self.con.execute("INSERT OR REPLACE INTO serials VALUES(?,0,?)", (COUNTER.get(kind, kind), int(last)))
        self.con.commit()

    # ---------------- letters
    def add_letter(self, serial, kind, code, cycle_id, date, amount, pdf, prev_serial, rep_name):
        self.con.execute("INSERT INTO letters(serial, kind, code, cycle_id, date, amount, pdf, prev_serial, user, created,"
                         " rep_name) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (serial, kind, code, cycle_id, date, amount, pdf, prev_serial, self.user, now(), rep_name))

    def letters(self, code=None, cycle_id=None):
        q, args = "SELECT l.*, c.name FROM letters l LEFT JOIN customers c ON c.code=l.code WHERE 1=1", []
        if code:
            q += " AND l.code=?"
            args.append(code)
        if cycle_id:
            q += " AND l.cycle_id=?"
            args.append(cycle_id)
        return [dict(r) for r in self.con.execute(q + " ORDER BY l.id DESC", args)]

    def last_letter(self, code, before_kinds=None):
        q = "SELECT * FROM letters WHERE code=? AND status!='ملغي'"
        args = [code]
        if before_kinds:
            q += f" AND kind IN ({','.join('?' * len(before_kinds))})"
            args += list(before_kinds)
        r = self.con.execute(q + " ORDER BY id DESC LIMIT 1", args).fetchone()
        return dict(r) if r else None

    def cancel_letter(self, serial, reason):
        self.con.execute("UPDATE letters SET status='ملغي', cancel_reason=? WHERE serial=?", (reason, serial))
        self.con.commit()

    # ---------------- receipts
    def add_receipts(self, cycle_id, recs, source):
        added = 0
        for r in recs:
            cur = self.con.execute("INSERT OR IGNORE INTO receipts VALUES(?,?,?,?,?,?,?,?,?)",
                                   (cycle_id, r.voucher, r.date, r.code, r.name, r.account, r.amount, source, now()))
            added += cur.rowcount
        self.con.commit()
        return added

    def receipts(self, cycle_id, code=None):
        q, args = "SELECT * FROM receipts WHERE cycle_id=?", [cycle_id]
        if code:
            q += " AND code=?"
            args.append(code)
        return [dict(r) for r in self.con.execute(q + " ORDER BY date, voucher", args)]

    def delete_receipts(self, cycle_id, source):
        self.con.execute("DELETE FROM receipts WHERE cycle_id=? AND source=?", (cycle_id, source))
        self.con.commit()

    def paid_by_code(self, cycle_id):
        return {r[0]: r[1] for r in self.con.execute(
            "SELECT code, SUM(amount) FROM receipts WHERE cycle_id=? GROUP BY code", (cycle_id,))}

    # ---------------- negotiations
    def negotiations(self, code=None, active_only=False):
        q, args = "SELECT n.*, c.name FROM negotiations n LEFT JOIN customers c ON c.code=n.code WHERE 1=1", []
        if code:
            q += " AND n.code=?"
            args.append(code)
        if active_only:
            q += " AND n.status='جاري'"
        out = []
        for r in self.con.execute(q + " ORDER BY n.id DESC", args):
            d = dict(r)
            d["data"] = json.loads(d["data"] or "{}")
            out.append(d)
        return out

    def add_negotiation(self, code, cycle_id, amount, data, serial, pdf):
        cur = self.con.execute("INSERT INTO negotiations(code, cycle_id, created, amount, data, serial, pdf, user) "
                               "VALUES(?,?,?,?,?,?,?,?)",
                               (code, cycle_id, now(), amount, json.dumps(data, ensure_ascii=False), serial, pdf,
                                self.user))
        self.con.commit()
        return cur.lastrowid

    def close_negotiation(self, nid, status, note=""):
        self.con.execute("UPDATE negotiations SET status=?, closed=?, note=? WHERE id=?", (status, now(), note, nid))
        self.con.commit()
