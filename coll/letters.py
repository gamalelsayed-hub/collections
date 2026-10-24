"""Merging letter templates and writing them as A4 PDFs on the company letterhead."""
import html
import os
import re

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QTextBlockFormat, QTextCursor,
                           QTextDocument, QTextOption)

from . import templates as T
from .tafqeet import riyal_words

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
FIELD = re.compile(r"\{([^{}\s]+)\}")
DPI = 300
MM = DPI / 25.4


def money(v):
    return f"{v:,.2f}" if isinstance(v, (int, float)) else (v or "")


def fmt_date(iso):
    """2026-10-19 → 19/10/2026"""
    if iso and re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso):
        y, m, d = iso.split("-")
        return f"{d}/{m}/{y}"
    return iso or ""


def merge(template_html, values, images=None):
    """Replace {field} with values (escaped). images: field → image path, inserted as pictures."""
    images = images or {}

    def rep(m):
        key = m.group(1)
        if key in images:
            p = images[key]
            return f'<img src="{html.escape(p)}" width="150"/>' if p and os.path.exists(p) else ""
        if key in values:
            return html.escape(str(values[key] if values[key] is not None else ""))
        return m.group(0)
    return FIELD.sub(rep, template_html)


def missing_fields(merged_html):
    return sorted({m for m in FIELD.findall(merged_html) if m in T.FIELDS})


def letter_values(db, cust, amount, serial, date_iso, prev=None, extra=None):
    """Values for the template fields. cust: customer master dict merged with cycle data."""
    pn_value = cust.get("pn_value")
    v = {
        "اسم_العميل": cust.get("name", ""), "رقم_العميل": cust.get("code", ""),
        "السجل_التجاري": cust.get("cr_no") or "________", "المندوب": cust.get("rep_name", ""),
        "المبلغ": money(amount), "المبلغ_كتابة": riyal_words(amount), "التاريخ": fmt_date(date_iso),
        "رقم_الخطاب": serial,
        "رقم_الخطاب_السابق": (prev or {}).get("serial", "—"),
        "تاريخ_الخطاب_السابق": fmt_date((prev or {}).get("date", "")) or "—",
        "رقم_السند": cust.get("pn_no") or "________", "قيمة_السند": money(pn_value) if pn_value else "________",
        "قيمة_السند_كتابة": riyal_words(pn_value) if pn_value else "________",
        "تاريخ_السند": fmt_date(cust.get("pn_date", "")),
        "اسم_الشركة": db.setting("company"), "سجل_الشركة": db.setting("company_cr"),
        "جوال_التواصل": db.setting("contact_mobile") or "____________",
        "ايميل_التواصل": db.setting("contact_email") or "____________",
        "المحاسب": db.user,
        "الرقم_الضريبي": cust.get("vat_no") or "", "العنوان_المختصر": cust.get("address") or "",
        "الهاتف1": cust.get("phone") or "", "الهاتف2": cust.get("phone2") or "",
        "البريد_الإلكتروني": cust.get("email") or "",
    }
    v.update(extra or {})
    return v


def make_rtl(doc):
    """Force right-to-left on every paragraph and table of a document (Qt ignores dir="rtl" on tables)."""
    opt = doc.defaultTextOption()
    opt.setTextDirection(Qt.RightToLeft)
    doc.setDefaultTextOption(opt)
    cur = QTextCursor(doc)
    cur.select(QTextCursor.Document)
    fmt = QTextBlockFormat()
    fmt.setLayoutDirection(Qt.RightToLeft)
    cur.mergeBlockFormat(fmt)

    def walk(frame):
        f = frame.frameFormat()
        f.setLayoutDirection(Qt.RightToLeft)
        frame.setFrameFormat(f)
        for child in frame.childFrames():
            walk(child)
    walk(doc.rootFrame())
    return doc


class Letterhead:
    """Either the company's letterhead page (a full A4 image: header and footer as printed on the paper), or
    the built-in layout: logo top-left, company name top-right, faded logo watermark, optional footer line.
    top / bottom: where the letter text starts and ends (mm from the page edges)."""

    def __init__(self, company, logo=None, footer="", watermark=True, page=None, top=46, bottom=24):
        self.company = company
        self.footer = footer
        self.watermark = watermark
        self.page = QImage(page) if page and os.path.exists(page) else None
        if self.page is not None and self.page.isNull():
            self.page = None
        self.top, self.bottom = (top, bottom) if self.page is not None else (46, 24)
        path = logo if logo and os.path.exists(logo) else os.path.join(RES, "logo.png")
        self.logo = QImage(path)

    def paint(self, p, page_w, page_h):
        if self.page is not None:
            p.drawImage(QRectF(0, 0, page_w, page_h), self.page)
            return
        if not self.logo.isNull():
            if self.watermark:
                w = 150 * MM
                h = w * self.logo.height() / self.logo.width()
                p.setOpacity(0.07)
                p.drawImage(QRectF((page_w - w) / 2, (page_h - h) / 2 + 20 * MM, w, h), self.logo)
                p.setOpacity(1.0)
            w = 42 * MM
            h = w * self.logo.height() / self.logo.width()
            p.drawImage(QRectF(14 * MM, 8 * MM, w, h), self.logo)
        f = QFont("Arial")
        f.setPointSizeF(14)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(page_w / 2, 12 * MM, page_w / 2 - 16 * MM, 12 * MM),
                   int(Qt.AlignRight | Qt.AlignVCenter), self.company)
        if self.footer:
            f.setPointSizeF(9)
            f.setBold(False)
            p.setFont(f)
            p.drawLine(QPointF(16 * MM, page_h - 16 * MM), QPointF(page_w - 16 * MM, page_h - 16 * MM))
            p.drawText(QRectF(16 * MM, page_h - 15 * MM, page_w - 32 * MM, 10 * MM), int(Qt.AlignCenter), self.footer)


def page_image(path, dpi=200):
    """The company's letter paper as a full A4 image (white background): first page of a PDF, or a picture."""
    from PySide6.QtCore import QSize
    size = QSize(round(210 / 25.4 * dpi), round(297 / 25.4 * dpi))
    if path.lower().endswith(".pdf"):
        from PySide6.QtPdf import QPdfDocument
        doc = QPdfDocument()
        doc.load(path)
        if doc.pageCount() < 1:
            return QImage()
        src = doc.render(0, size)
        doc.close()
    else:
        src = QImage(path)
    if src.isNull():
        return src
    out = QImage(size, QImage.Format_RGB32)
    out.fill(Qt.white)
    p = QPainter(out)
    p.drawImage(QRectF(0, 0, size.width(), size.height()), src)
    p.end()
    return out


def write_pdf(pages_html, out_path, letterhead, title=""):
    """pages_html: list of merged HTML documents; each starts on a new page."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    writer = QPdfWriter(out_path)
    writer.setResolution(DPI)
    writer.setTitle(title)
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    page_w, page_h = 210 * MM, 297 * MM
    top, bottom, side = letterhead.top * MM, letterhead.bottom * MM, 20 * MM
    box_w, box_h = page_w - 2 * side, page_h - top - bottom
    p = QPainter(writer)
    first = True
    try:
        for body in pages_html:
            doc = QTextDocument()
            doc.documentLayout().setPaintDevice(writer)
            font = QFont("Arial")
            font.setPointSizeF(12)
            doc.setDefaultFont(font)
            opt = QTextOption()
            opt.setTextDirection(Qt.RightToLeft)
            opt.setAlignment(Qt.AlignRight)
            doc.setDefaultTextOption(opt)
            doc.setHtml(f'<html><body dir="rtl">{body}</body></html>')
            make_rtl(doc)
            # a letter that just spills onto a second page is scaled down (to 85% at most) to stay on one page
            scale = 1.0
            doc.setPageSize(QSizeF(box_w, box_h))
            if doc.pageCount() > 1:
                for s in (0.95, 0.9, 0.85):
                    doc.setPageSize(QSizeF(box_w / s, box_h / s))
                    if doc.pageCount() == 1:
                        scale = s
                        break
                else:
                    doc.setPageSize(QSizeF(box_w, box_h))
            w, h = box_w / scale, box_h / scale
            for i in range(max(1, doc.pageCount())):
                if not first:
                    writer.newPage()
                first = False
                letterhead.paint(p, page_w, page_h)
                p.save()
                p.translate(side, top)
                p.scale(scale, scale)
                p.translate(0, -i * h)
                doc.drawContents(p, QRectF(0, i * h, w, h))
                p.restore()
    finally:
        p.end()
    return out_path
