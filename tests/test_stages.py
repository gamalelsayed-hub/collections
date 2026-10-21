"""Day 7+ flow on synthetic data."""
import os


from coll import aging, receipts, stages
from coll.db import DB
from coll.storage import DataFolder
from coll.tafqeet import riyal_words
from tests.test_aging_reps import sample_rows


def setup_cycle(tmp_path):
    folder = DataFolder(str(tmp_path / "data"))
    db = DB(folder.db_path, "tester")
    db.save_rep({"name": "سالم عبدالله", "email": "salem@example.com", "emp_no": "1", "branch": "", "title": ""})
    db.set_alias("سالم", db.reps()[0]["id"])
    rows = sample_rows()
    first, mapping = aging.guess_columns(rows)
    recs = aging.read_rows(rows, first, mapping)
    db.upsert_from_aging(recs)
    db.create_cycle("2026-10", "aging.xlsx", "2026-10-01", aging.group_customers(recs, 30, 60))
    return folder, db, db.cycle("2026-10")


def test_riyal_words():
    assert riyal_words(1250.5) == "ألف ومائتان وخمسون ريال وخمسون هللة"
    assert riyal_words(3000) == "ثلاثة آلاف ريال"
    assert riyal_words(2) == "ريالان"


def test_receipt_lines():
    toks = ["357", "18/10/2026", "-", "بنكي", "401", "مصرف", "الراجحي", "SAR5553", "1140123", "مؤسسة", "الاختبار",
            "SAR", "90000001", "4,000.00", "8001", "18/10/2026"]
    r = receipts._pdf_line(toks)
    assert (r.code, r.amount, r.date, r.account) == ("90000001", 4000.0, "2026-10-18", "1140123")
    assert receipts.is_customer_line(r.account, r.code)
    internal = receipts._pdf_line(["447", "18/10/2026", "-", "بنكي", "449", "مصرف", "SAR5553", "1110101", "صندوق",
                                   "SAR", "4006", "2,500.00", "8001", "18/10/2026"])
    assert not receipts.is_customer_line(internal.account, internal.code)


def test_full_flow(tmp_path, qapp):
    folder, db, cyc = setup_cycle(tmp_path)
    # signed statement for 90000001
    signed = tmp_path / "90000001 موقع.pdf"
    signed.write_bytes(b"%PDF-1.4")
    matched, unknown = stages.attach_signed(db, folder, cyc, [str(signed), str(tmp_path / "x.pdf")])
    assert matched == [("90000001", "عميل أ")] and unknown == ["x.pdf"]
    # receipts: 90000001 pays 400 of 500 overdue (80%), 90000003 pays 10 of 50
    recs = [receipts.Receipt("1", "2026-10-03", "1140101", "عميل أ", "90000001", 400.0),
            receipts.Receipt("2", "2026-10-04", "1140120", "عميل ج", "90000003", 10.0)]
    res = stages.add_receipts(db, folder, cyc, recs, str(signed))
    assert res["added"] == 2
    assert stages.add_receipts(db, folder, cyc, recs, str(signed))["duplicates"] == 2   # same file twice
    c1 = db.cycle_customer(cyc["id"], "90000001")
    assert abs(c1["pct"] - 0.8) < 1e-9 and c1["status"] == "سدد 80%"

    cands = {c["code"]: c for c in stages.candidates(db, cyc, "finance")}
    assert not cands["90000001"]["eligible"]
    assert cands["90000003"]["eligible"] and cands["90000003"]["amount"] == 140.0   # balance 150 − paid 10
    assert cands["90000004"]["eligible"]
    stages.exclude(db, cyc, "90000004", "اتفاق مع المدير")
    cands = {c["code"]: c for c in stages.candidates(db, cyc, "finance")}
    assert not cands["90000004"]["eligible"]

    db.set_setting("contact_mobile", "0500000000")
    packs = stages.issue(db, folder, cyc, [{"code": "90000003", "kind": "1003", "amount": 40.0}], "2026-10-07")
    assert len(packs) == 1 and os.path.exists(packs[0]["letters"][0]["pdf"]) and os.path.exists(packs[0]["zip"])
    letter = db.letters(code="90000003")[0]
    assert letter["serial"] == "RE-SL-26-1003-0001"
    assert db.cycle_customer(cyc["id"], "90000003")["status"] == "خطاب مالي"

    # legal stage: customer has a promissory note → PN version, then the action stage is 1005
    cust = db.customer("90000003")
    cust.update(has_pn=1, pn_no="PN-1", pn_value=1000.0)
    db.save_customer(cust)
    legal = stages.candidates(db, cyc, "legal")
    assert [c["kind"] for c in legal] == ["1004PN"]
    stages.issue(db, folder, cyc, [{"code": "90000003", "kind": "1004PN", "amount": 40.0}], "2026-10-14")
    assert [c["code"] for c in stages.stop_sale(db, cyc)] == ["90000003"]
    action = stages.candidates(db, cyc, "action")
    assert action[0]["kind"] == "1005"
    legal_serial = db.letters(code="90000003")[0]["serial"]
    assert legal_serial == "RE-SL-26-1004-0001"

    # cancelling keeps the serial and moves the customer back one level
    stages.cancel_letter(db, cyc["id"], legal_serial, "خطأ في المبلغ")
    assert db.letters(code="90000003")[0]["status"] == "ملغي"
    assert db.cycle_customer(cyc["id"], "90000003")["level"] == 1
    stages.issue(db, folder, cyc, [{"code": "90000003", "kind": "1004PN", "amount": 40.0}], "2026-10-14")
    assert db.letters(code="90000003")[0]["serial"] == "RE-SL-26-1004-0002"

    # negotiation takes the customer out of the stages; «لم يلتزم» brings it back
    stages.start_negotiation(db, folder, cyc, "90000003",
                             {"amount": 40.0, "rep": "أحمد", "title": "مالك", "id_no": "1",
                              "option": 1, "inst": [(20.0, "2026-10-20"), (20.0, "2026-10-27")]})
    assert db.cycle_customer(cyc["id"], "90000003")["status"] == "تحت التفاوض"
    assert stages.candidates(db, cyc, "action")[0]["eligible"] is False
    from datetime import date
    late = stages.late_instalments(db, date(2026, 10, 21))
    assert late and late[0]["due"] == 20.0
    nid = db.negotiations(active_only=True)[0]["id"]
    stages.close_negotiation(db, cyc, nid, kept=False)
    assert stages.candidates(db, cyc, "action")[0]["eligible"] is True

    # next month: still inside the stages → continues from its last letter
    rows = sample_rows()
    first, mapping = aging.guess_columns(rows)
    recs = aging.read_rows(rows, first, mapping)
    db.create_cycle("2026-11", "aging.xlsx", "2026-11-01", aging.group_customers(recs, 30, 60))
    nov = db.cycle("2026-11")
    c = db.cycle_customer(nov["id"], "90000003")
    assert c["level"] == 2 and c["pn_letter"] == 1 and "مستمر" in c["carried"]


def test_receipts_period(tmp_path):
    folder, db, cyc = setup_cycle(tmp_path)          # October cycle, aging uploaded 1 October
    # working days (default): 1 Oct 2026 is a Thursday; Fridays and holidays are skipped
    assert stages.stage_end(db, cyc, "finance") == "2026-10-08"
    db.set_setting("holidays", "05/10/2026")
    assert stages.stage_end(db, cyc, "finance") == "2026-10-10"
    db.set_setting("weekend", "4,5")                 # Friday and Saturday
    assert stages.stage_end(db, cyc, "finance") == "2026-10-12"
    db.set_setting("workdays", "0")                  # calendar days
    assert stages.cycle_start(db, cyc) == "2026-10-01"
    assert stages.stage_end(db, cyc, "finance") == "2026-10-07"
    assert stages.stage_end(db, cyc, "legal") == "2026-10-14"
    f = tmp_path / "r.pdf"
    f.write_bytes(b"x")
    recs = [receipts.Receipt("1", "2026-09-30", "1140101", "", "90000001", 50.0),    # before Day 1
            receipts.Receipt("2", "2026-10-05", "1140101", "", "90000001", 100.0),   # Day 7 period
            receipts.Receipt("3", "2026-10-10", "1140101", "", "90000001", 300.0)]   # next stage
    res = stages.add_receipts(db, folder, cyc, recs, str(f), "2026-10-01", "2026-10-07")
    assert (res["before"], res["after"], res["added"]) == (1, 1, 1)
    assert db.cycle_customer(cyc["id"], "90000001")["paid"] == 100.0
    # the same file again in the Day 14 stage: only the new voucher is added, cumulative from Day 1
    res = stages.add_receipts(db, folder, cyc, recs, str(f), "2026-10-01", "2026-10-14")
    assert (res["added"], res["duplicates"]) == (1, 1)
    assert db.cycle_customer(cyc["id"], "90000001")["paid"] == 400.0
    # the Day 7 decision is still based on receipts up to the 7th
    stages.recompute_paid(db, cyc, "2026-10-01", "2026-10-07")
    assert db.cycle_customer(cyc["id"], "90000001")["paid"] == 100.0
    # the cycle month is the collection month, whenever the aging report was uploaded
    db.set_setting("workdays", "0")
    db.create_cycle("2026-09", "aging.xlsx", "2026-10-20", [])
    sep = db.cycle("2026-09")
    assert stages.cycle_start(db, sep) == "2026-09-01" and stages.stage_end(db, sep, "finance") == "2026-09-07"
    db.set_cycle_start(sep["id"], "2026-09-03")
    assert stages.stage_end(db, sep, "finance") == "2026-09-09"
