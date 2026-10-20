import os
import zipfile

import pytest
from pypdf import PdfReader, PdfWriter

from coll import aging, day1
from coll import statements as ST
from coll.db import DB
from coll.storage import DataFolder, LockedError
from tests.test_aging_reps import sample_rows


def blank_pdf(path, pages):
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=595, height=842)
    with open(path, "wb") as f:
        w.write(f)
    return str(path)


def test_lock_and_backup(tmp_path):
    folder = DataFolder(str(tmp_path / "data"))
    folder.acquire("أحمد")
    lock = folder.read_lock()
    assert lock["user"] == "أحمد"
    lock["machine"] = "OTHER-PC"
    import json
    with open(folder.lock_path, "w", encoding="utf-8") as f:
        json.dump(lock, f)
    with pytest.raises(LockedError):
        folder.acquire("محمد")
    folder.force_unlock()
    folder.acquire("محمد")
    db = DB(folder.db_path, "محمد")
    db.log("test")
    db.close()
    folder.backup("open")
    assert len(folder.backups()) == 1


def test_day1_flow(tmp_path, monkeypatch):
    folder = DataFolder(str(tmp_path / "data"))
    db = DB(folder.db_path, "tester")
    db.save_rep({"name": "سالم عبدالله", "email": "salem@example.com", "emp_no": "1", "branch": "", "title": ""})
    rep = db.reps()[0]
    db.set_alias("سالم", rep["id"])
    rows = sample_rows()
    first, mapping = aging.guess_columns(rows)
    recs = aging.read_rows(rows, first, mapping)
    grouped = aging.group_customers(recs, 30, 60)
    db.upsert_from_aging(recs)
    db.create_cycle("2026-10", "aging.xlsx", "2026-10-01", grouped)
    cycle = db.cycle("2026-10")

    credit = blank_pdf(tmp_path / "credit.pdf", 4)
    custody = blank_pdf(tmp_path / "custody.pdf", 1)
    fake = {
        credit: [ST.Section("90000001", "عميل أ", "1140101", "العملاء", credit, [0], 600.0),
                 ST.Section("90000002", "عميل ب", "1140101", "العملاء", credit, [1], 500.0),   # not required
                 ST.Section("90000004", "عميل د", "1140101", "العملاء", credit, [2, 3], 300.0)],
        custody: [ST.Section("90000004", "عميل د", "1140120", "عهدة مبيعات خالد", custody, [0], 70.0)],
    }
    monkeypatch.setattr(ST, "read_pdf", lambda p: (fake[p], []))
    r = day1.attach_file(db, folder, cycle, credit, "credit")
    assert len(r.attached) == 2 and r.ignored == ["90000002"]
    day1.attach_file(db, folder, cycle, custody, "custody", "خالد")
    # stored paths are relative to the data folder (Drive paths differ per PC)
    assert not os.path.isabs(db.sections(cycle["id"])["90000001"][0]["source"])

    rev = {c["code"]: c for c in day1.review(db, cycle)}
    assert rev["90000003"]["status"] == "كشف ناقص"
    d = rev["90000004"]
    assert d["status"] == "كشف جاهز" and d["stmt_balance"] == 370
    assert "دمجهما" in d["warning"]

    packages = day1.build_packages(db, folder, cycle)
    salem = next(p for p in packages if p["email"] == "salem@example.com")
    assert len(salem["customers"]) == 2
    merged = [f for f in os.listdir(salem["dir"]) if f.startswith("90000004")][0]
    assert len(PdfReader(os.path.join(salem["dir"], merged)).pages) == 3
    names = zipfile.ZipFile(salem["zip"]).namelist()
    assert "قائمة العملاء.xlsx" in names and len(names) == 3


def test_next_month_statements(tmp_path, monkeypatch):
    """October from 1/1, November only 1/11–30/11: opening checked for matched customers, October's statement
    attached for customers who did not reconcile."""
    folder = DataFolder(str(tmp_path / "data"))
    db = DB(folder.db_path, "tester")
    rows = sample_rows()
    first, mapping = aging.guess_columns(rows)
    recs = aging.read_rows(rows, first, mapping)
    grouped = aging.group_customers(recs, 30, 60)
    for month in ("2026-10", "2026-11"):
        db.create_cycle(month, "aging.xlsx", f"{month}-01", grouped)
    octo, nov = db.cycle("2026-10"), db.cycle("2026-11")

    oct_pdf = blank_pdf(tmp_path / "oct.pdf", 3)
    nov_pdf = blank_pdf(tmp_path / "nov.pdf", 2)

    def sec(code, src, pages, balance, opening, start, end):
        return ST.Section(code, "", "1140101", "العملاء", src, pages, balance, opening, start, end)
    fake = {oct_pdf: [sec("90000001", oct_pdf, [0], 600.0, 0.0, "2026-01-01", "2026-10-31"),
                      sec("90000003", oct_pdf, [1, 2], 150.0, 0.0, "2026-01-01", "2026-10-31")],
            nov_pdf: [sec("90000001", nov_pdf, [0], 650.0, 590.0, "2026-11-01", "2026-11-30"),
                      sec("90000003", nov_pdf, [1], 150.0, 150.0, "2026-11-01", "2026-11-30")]}
    monkeypatch.setattr(ST, "read_pdf", lambda p: (fake[p], []))
    day1.attach_file(db, folder, octo, oct_pdf, "credit")
    day1.build_packages(db, folder, octo)
    db.update_cycle_customer(octo["id"], "90000001", matched=1)   # 90000003 did not reconcile

    day1.attach_file(db, folder, nov, nov_pdf, "credit")
    day1.build_packages(db, folder, nov)
    c1 = db.cycle_customer(nov["id"], "90000001")
    assert "الرصيد الافتتاحي 590.00" in c1["warning"] and "600.00" in c1["warning"]
    c3 = db.cycle_customer(nov["id"], "90000003")
    assert "يُرفق كشف الشهر السابق" in c3["warning"]
    merged = os.path.join(folder.path, c3["statement"])
    assert len(PdfReader(merged).pages) == 3   # October's 2 pages + November's 1 page
