"""Customer attachments: commercial register, tax certificate, national address, promissory note, account opening
file, owner ID ... Each file is copied into the data folder (files/customers/<code>/) so every computer sees it."""
import os
import shutil
from datetime import datetime

from .day1 import safe_name

KINDS = [
    ("cr", "السجل التجاري"),
    ("vat", "شهادة الضريبة"),
    ("address", "العنوان الوطني"),
    ("pn", "سند لأمر"),
    ("account", "ملف فتح حساب العميل"),
    ("owner_id", "هوية المالك"),
    ("update", "نموذج تحديث البيانات (موقع)"),
    ("other", "أخرى"),
]
KIND_NAMES = dict(KINDS)
REQUIRED = ["cr", "vat", "address", "account", "owner_id"]      # the promissory note only if the customer has one


def add(db, folder, code, kind, src):
    """Copy src into the customer's folder and record it. Returns the record id."""
    dest_dir = folder.files_dir("customers", code)
    ext = os.path.splitext(src)[1].lower()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(dest_dir, f"{safe_name(KIND_NAMES.get(kind, kind))} - {stamp}{ext}")
    shutil.copy2(src, dest)
    rel = os.path.relpath(dest, folder.path)
    fid = db.add_customer_file(code, kind, os.path.basename(src), rel)
    db.log("إرفاق مستند", f"{KIND_NAMES.get(kind, kind)}: {os.path.basename(src)}", code=code)
    return fid


def full_path(folder, rec):
    return os.path.join(folder.path, rec["path"])


def remove(db, folder, rec):
    p = full_path(folder, rec)
    try:
        os.remove(p)
    except OSError:
        pass
    db.delete_customer_file(rec["id"])
    db.log("حذف مرفق", f"{KIND_NAMES.get(rec['kind'], rec['kind'])}: {rec['name']}", code=rec["code"])


def missing(db, customer, files=None):
    """Required documents the customer has no file for."""
    have = {f["kind"] for f in (files if files is not None else db.customer_files(customer["code"]))}
    need = REQUIRED + (["pn"] if customer.get("has_pn") else [])
    return [k for k in need if k not in have]
