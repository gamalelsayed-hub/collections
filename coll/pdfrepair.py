"""PDFs with a damaged ending (export cut short, Google Drive still syncing) are repaired before reading."""
import os
import tempfile

MESSAGE = ("الملف ناقص أو تالف ولم يمكن إصلاحه. تأكد أنه يفتح كاملًا في قارئ PDF، ولو كان على جوجل درايف "
           "انتظر اكتمال التزامن، أو صدّره من النظام مرة أخرى.")


class DamagedPdf(Exception):
    pass


def readable(path):
    """Return path itself if the PDF opens, otherwise a repaired copy. Raises DamagedPdf if it cannot be repaired."""
    import pdfplumber
    try:
        with pdfplumber.open(path) as pdf:
            len(pdf.pages)
        return path
    except Exception:  # noqa: BLE001 — pdfminer raises many kinds of errors for broken files
        pass
    try:
        import pikepdf
        out = os.path.join(tempfile.mkdtemp(prefix="coll-"), os.path.basename(path))
        with pikepdf.open(path) as pdf:
            pdf.save(out)
        with pdfplumber.open(out) as pdf:
            len(pdf.pages)
        return out
    except Exception as e:  # noqa: BLE001
        raise DamagedPdf(MESSAGE) from e
