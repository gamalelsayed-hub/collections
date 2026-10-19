"""Text helpers: Arabic words from PDF extraction, numbers, names."""
import re
import unicodedata

ARABIC = re.compile("[\\u0621-\\u064A\\u0671-\\u06D3\\uFB50-\\uFDFF\\uFE70-\\uFEFF]")  # letters only, not digits
AR_DIGITS = str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669\u066b\u066c", "0123456789.,")


def fix_pdf_word(token):
    """The system's PDFs store Arabic words in visual order with presentation forms ("مقر" for "رقم").
    Reverse Arabic tokens and normalize the letter shapes; leave numbers and Latin text as they are."""
    if not ARABIC.search(token):
        return token.translate(AR_DIGITS)
    return unicodedata.normalize("NFKC", token[::-1]).translate(AR_DIGITS)


def norm(s):
    """Loose form for matching Arabic names and labels."""
    s = unicodedata.normalize("NFKC", str(s or "")).strip().lower()
    s = re.sub("[إأآا]", "ا", s).replace("ة", "ه").replace("ى", "ي").replace("ـ", "")
    s = re.sub("[ً-ْ]", "", s)
    return re.sub(r"\s+", " ", s)


def to_number(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().translate(AR_DIGITS)
    if not s or s in ("-", "—"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").replace(" ", "")
    if s.endswith("-"):
        neg, s = True, s[:-1]
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


def code_text(v):
    """Customer/account codes come as numbers from Excel (11020909.0) or text."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip().translate(AR_DIGITS)


AMOUNT = re.compile(r"^-?[\d,]+\.\d{2}$")
