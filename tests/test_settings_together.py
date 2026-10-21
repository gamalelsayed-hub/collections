"""The settings combined: no rule contradicts another (synthetic data)."""
from coll import aging, receipts, stages
from tests.test_aging_reps import sample_rows
from tests.test_stages import setup_cycle


def rec(code, amount, day="2026-10-05", v=None):
    return receipts.Receipt(v or f"{code}-{amount}-{day}", day, "1140101", "", code, amount)


def next_month(db, month="2026-11", **rules):
    rows = sample_rows()
    first, mapping = aging.guess_columns(rows)
    recs = aging.read_rows(rows, first, mapping)
    grouped = aging.group_customers(recs, 30, 60, rules.get("min_overdue", 0), rules.get("max_customers", 0),
                                    rules.get("skip"))
    db.create_cycle(month, "aging.xlsx", f"{month}-01", grouped)
    return db.cycle(month)


def test_customer_in_stages_continues_outside_the_limits(tmp_path, qapp):
    folder, db, cyc = setup_cycle(tmp_path)
    db.update_cycle_customer(cyc["id"], "90000003", level=2)          # legal letter sent, nothing paid
    # next month: only the top customer, and a minimum above 90000003's overdue (50)
    nov = next_month(db, max_customers=1, min_overdue=100)
    c = db.cycle_customer(nov["id"], "90000003")
    assert c["required"] == 1 and c["level"] == 2 and "مستمر" in c["carried"]
    assert db.carried_forced == ["90000003"]
    # ...but a permanent exclusion still wins
    db2_folder, db2, cyc2 = setup_cycle(tmp_path / "b")
    db2.update_cycle_customer(cyc2["id"], "90000003", level=2)
    nov2 = next_month(db2, skip={"skip_codes": {"90000003": "استثناء دائم: شقيق"}})
    assert db2.cycle_customer(nov2["id"], "90000003")["required"] == 0


def test_carry_over_uses_all_receipts_of_the_month(tmp_path, qapp):
    folder, db, cyc = setup_cycle(tmp_path)
    db.update_cycle_customer(cyc["id"], "90000001", level=1)          # finance letter, overdue 500
    f = tmp_path / "r.pdf"
    f.write_bytes(b"x")
    stages.add_receipts(db, folder, cyc, [rec("90000001", 450, "2026-10-20")], str(f))   # 90% paid late
    stages.recompute_paid(db, cyc, "2026-10-01", "2026-10-07")          # screen last showed the Day 7 period
    assert db.cycle_customer(cyc["id"], "90000001")["pct"] == 0
    nov = next_month(db)
    assert db.cycle_customer(nov["id"], "90000001")["level"] == 0      # paid → does not continue


def test_stop_sale_matches_status_with_different_thresholds(tmp_path, qapp):
    folder, db, cyc = setup_cycle(tmp_path)
    db.set_setting("pay_threshold_legal", "0.5")
    db.set_setting("pay_threshold_action", "1.0")
    db.update_cycle_customer(cyc["id"], "90000001", level=2)          # legal letter sent
    f = tmp_path / "r.pdf"
    f.write_bytes(b"x")
    stages.add_receipts(db, folder, cyc, [rec("90000001", 400)], str(f))  # 80%
    c = db.cycle_customer(cyc["id"], "90000001")
    in_stop = "90000001" in {x["code"] for x in stages.stop_sale(db, cyc)}
    assert c["status"] == "خطاب قانوني — إيقاف بيع" and in_stop
    stages.add_receipts(db, folder, cyc, [rec("90000001", 100)], str(f))  # 100%
    c = db.cycle_customer(cyc["id"], "90000001")
    in_stop = "90000001" in {x["code"] for x in stages.stop_sale(db, cyc)}
    assert c["status"].startswith("سدد") and not in_stop


def test_thresholds_per_stage_and_letter_amount(tmp_path, qapp):
    folder, db, cyc = setup_cycle(tmp_path)
    db.set_setting("pay_threshold_legal", "0.9")
    f = tmp_path / "r.pdf"
    f.write_bytes(b"x")
    stages.add_receipts(db, folder, cyc, [rec("90000001", 400)], str(f))  # 80% of 500
    fin = {c["code"]: c for c in stages.candidates(db, cyc, "finance")}
    assert not fin["90000001"]["eligible"]                              # 80% ≥ 70%: no finance letter
    db.update_cycle_customer(cyc["id"], "90000001", level=1)
    legal = {c["code"]: c for c in stages.candidates(db, cyc, "legal")}
    assert legal["90000001"]["eligible"] and legal["90000001"]["amount"] == 200.0   # 80% < 90%; balance 600 − 400

    def amount(mode):
        db.set_setting("letter_amount", mode)
        return {c["code"]: c for c in stages.candidates(db, cyc, "legal")}["90000001"]["amount"]
    assert (amount("overdue_paid"), amount("balance_full"), amount("overdue_full")) == (100.0, 600.0, 500.0)
    db.set_setting("letter_amount", "balance_paid")
    db.set_setting("min_letter", "250")                                  # 200 left < 250 → no letter
    row = {c["code"]: c for c in stages.candidates(db, cyc, "legal")}["90000001"]
    assert not row["eligible"] and "حد الخطاب" in row["reason"]


def test_rest_month_never_skips_a_customer_inside_the_stages(tmp_path, qapp):
    from coll.ui.cycle_page import CyclePage

    class Win:
        pass
    folder, db, cyc = setup_cycle(tmp_path)
    db.set_setting("rest_matched", "1")
    f = tmp_path / "r.pdf"
    f.write_bytes(b"x")
    stages.add_receipts(db, folder, cyc, [rec("90000001", 500), rec("90000003", 50)], str(f))
    db.update_cycle_customer(cyc["id"], "90000001", matched=1)           # matched and paid → rests
    db.update_cycle_customer(cyc["id"], "90000003", matched=1, level=1)  # paid but already had a letter
    win = Win()
    win.db = db
    rules = CyclePage.skip_rules(type("P", (), {"win": win})(), "2026-11")
    assert "90000001" in rules["skip_codes"] and "90000003" not in rules["skip_codes"]


def test_weekend_every_day_does_not_hang(tmp_path):
    folder, db, cyc = setup_cycle(tmp_path)
    db.set_setting("weekend", "0,1,2,3,4,5,6")
    assert stages.stage_end(db, cyc, "finance") == "2026-10-07"
