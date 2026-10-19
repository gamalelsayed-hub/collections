"""Amounts in Arabic words (Saudi riyals and halalas): 1250.5 → "ألف ومائتان وخمسون ريالًا وخمسون هللة"."""

ONES = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة", "عشرة",
        "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر", "خمسة عشر", "ستة عشر", "سبعة عشر", "ثمانية عشر", "تسعة عشر"]
TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
HUNDREDS = ["", "مائة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة", "سبعمائة", "ثمانمائة", "تسعمائة"]
# (one, two, 3-10 plural, 11+ singular)
SCALES = [None, ("ألف", "ألفان", "آلاف", "ألف"), ("مليون", "مليونان", "ملايين", "مليون"),
          ("مليار", "ملياران", "مليارات", "مليار")]


def _below_1000(n):
    parts = []
    h, rest = divmod(n, 100)
    if h:
        parts.append(HUNDREDS[h])
    if rest < 20:
        if rest:
            parts.append(ONES[rest])
    else:
        t, o = divmod(rest, 10)
        parts.append(f"{ONES[o]} و{TENS[t]}" if o else TENS[t])
    return " و".join(parts)


def number_words(n):
    n = int(n)
    if n == 0:
        return "صفر"
    groups = []
    i = 0
    while n:
        n, g = divmod(n, 1000)
        if g:
            if i == 0:
                groups.append(_below_1000(g))
            else:
                one, two, plural, single = SCALES[i]
                if g == 1:
                    groups.append(one)
                elif g == 2:
                    groups.append(two)
                elif 3 <= g <= 10:
                    groups.append(f"{_below_1000(g)} {plural}")
                else:
                    groups.append(f"{_below_1000(g)} {single}")
        i += 1
    return " و".join(reversed(groups))


def _unit(n, one, two, plural, single):
    if n == 1:
        return one
    if n == 2:
        return two
    r = n % 100
    return plural if 3 <= r <= 10 else single


def riyal_words(amount):
    """Amount in words with currency, for letters: "فقط ... ريال سعودي لا غير" is added by the template."""
    amount = round(abs(float(amount or 0)) + 1e-9, 2)
    riyals = int(amount)
    halalas = int(round((amount - riyals) * 100))
    out = []
    if riyals:
        unit = _unit(riyals, "ريال", "ريالان", "ريالات", "ريال")
        out.append(unit if riyals in (1, 2) else f"{number_words(riyals)} {unit}")
    if halalas:
        unit = _unit(halalas, "هللة", "هللتان", "هللات", "هللة")
        out.append(unit if halalas in (1, 2) else f"{number_words(halalas)} {unit}")
    return " و".join(out) if out else "صفر ريال"
