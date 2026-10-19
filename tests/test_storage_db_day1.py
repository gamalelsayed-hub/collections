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
