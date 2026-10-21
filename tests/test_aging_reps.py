from coll import aging
from coll.reps import suggest_rep

HEADER = ["المنطقة", "الفرع", "المندوب", "رقم العميل", "اسم العميل", "تصنيف العميل", "نوع العميل",
          "0 - 30", "31 - 60", "61 - 90", "91 - 120", "أكثر من 120"]


def sample_rows():
    return [["تقرير أعمار"], [], HEADER,
            ["الغربية", "جدة", "سالم", "90000001", "عميل أ", "A", "آجل", 100, 0, 500, 0, 0],      # credit 61-90 → due
            ["الغربية", "جدة", "سالم", "90000002", "عميل ب", "A", "آجل", 100, 400, 0, 0, 0],      # credit 31-60 → not due
            ["الغربية", "جدة", "خالد", "90000003", "عميل ج", "B", "عهدة", 100, 50, 0, 0, 0],      # custody 31-60 → due
            ["الغربية", "جدة", "سالم", "90000004", "عميل د", "A", "آجل", 0, 0, 0, 0, 300],
            ["الغربية", "جدة", "خالد", "90000004", "عميل د", "A", "عهدة", 0, 70, 0, 0, 0]]


def test_group_and_required():
    rows = sample_rows()
    first, mapping = aging.guess_columns(rows)
    assert first == 3 and mapping["code"] == 3 and mapping["b4"] == 11
    recs = aging.read_rows(rows, first, mapping)
    g = {r["code"]: r for r in aging.group_customers(recs, 30, 60)}
    assert g["90000001"]["required"] and g["90000001"]["overdue"] == 500
    assert not g["90000002"]["required"]
    assert g["90000003"]["overdue"] == 50
    d = g["90000004"]
    assert d["overdue"] == 370 and d["types"] == "آجل + عهدة" and d["rep_name"] == "سالم"
    assert "أكثر من مندوب" in d["warning"]
    # minimum overdue: 90000003 (50) and 90000004 (370) drop out above 400
    g = {r["code"]: r for r in aging.group_customers(recs, 30, 60, 400)}
    assert g["90000001"]["required"] and not g["90000003"]["required"] and not g["90000004"]["required"]
    # only the 2 largest overdue customers
    g = aging.group_customers(recs, 30, 60, 0, 2)
    assert [r["code"] for r in g if r["required"]] == ["90000001", "90000004"]
    # stricter credit rule
    g = {r["code"]: r for r in aging.group_customers(recs, 30, 30)}
    assert g["90000002"]["required"]


def test_suggest_rep():
    reps = [{"id": 1, "name": "محمد حسن"}, {"id": 2, "name": "محمد اشرف علي"},
            {"id": 3, "name": "عارف محمد عبدالله باكرموم"}]
    assert suggest_rep("عارف باكرموم", reps)["id"] == 3
    assert suggest_rep("محمد حسن", reps)["id"] == 1
    assert suggest_rep("محمد", reps) is None          # ambiguous
    assert suggest_rep("سالم", reps) is None


def test_skip_rules():
    rows = sample_rows()
    first, mapping = aging.guess_columns(rows)
    recs = aging.read_rows(rows, first, mapping)
    recs[0]["guarantee"] = 1000.0                     # 90000001: bank guarantee covers its 500 overdue
    g = {r["code"]: r for r in aging.group_customers(
        recs, 30, 60, 0, 0, {"skip_codes": {"90000004": "استثناء دائم: شقيق"}, "skip_reps": ["خالد"],
                             "skip_classes": [], "guarantee": True})}
    assert not g["90000001"]["required"] and "ضمان بنكي" in g["90000001"]["skip"]
    assert not g["90000003"]["required"] and g["90000003"]["skip"] == "مندوب مستثنى: خالد"
    assert not g["90000004"]["required"] and g["90000004"]["skip"].startswith("استثناء دائم")
    # the top-N limit counts only customers that were not excluded
    g = aging.group_customers(recs, 30, 60, 0, 1, {"skip_reps": ["سالم"]})
    assert [r["code"] for r in g if r["required"]] == ["90000003"]
