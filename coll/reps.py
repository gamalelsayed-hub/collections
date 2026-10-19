"""Reps list import and matching the short names used in the aging report to the reps."""
from .aging import read_table
from .textutil import code_text, norm

HEADERS = {"emp_no": ("رقم الموظف", "الرقم الوظيفي", "رقم"), "name": ("الاسم", "اسم"),
           "email": ("الايميل", "الإيميل", "البريد", "email"), "branch": ("الفرع",),
           "title": ("المسمى", "الوظيفة")}


def import_reps(path):
    rows = read_table(path)
    for i, r in enumerate(rows[:20]):
        cells = [str(v or "").strip().lower() for v in r]
        cols = {}
        for key, words in HEADERS.items():
            c = next((k for k, t in enumerate(cells) for w in words if w.lower() in t and k not in cols.values()), None)
            if c is not None:
                cols[key] = c
        if "name" in cols and "email" in cols:
            out = []
            for row in rows[i + 1:]:
                rec = {k: (code_text(row[c]) if k == "emp_no" else str(row[c] or "").strip()) for k, c in cols.items()}
                if rec.get("name"):
                    rec["email"] = rec.get("email", "").lower()
                    out.append(rec)
            return out
    raise ValueError("لم أجد صف العناوين (الاسم، الإيميل) في الملف.")


def _tokens(s):
    s = norm(s).replace("عبد ال", "عبدال")
    return [t for t in s.replace("-", " ").split() if t not in ("بن", "ابن", "ال")]


def suggest_rep(alias, reps):
    """Best rep for a short name (e.g. "عارف باكرموم" → "عارف محمد عبدالله باكرموم"), or None."""
    a = _tokens(alias)
    if not a:
        return None
    matches = []
    for r in reps:
        t = _tokens(r["name"])
        # every word of the short name must be in the full name, starting with the first name
        if t and a[0] == t[0] and all(x in t for x in a):
            matches.append(r)
    return matches[0] if len(matches) == 1 else None
