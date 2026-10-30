from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, portrait
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from sqlalchemy import select

from .db import SessionLocal, BusinessSettings, Invoice, InvoiceItem, Customer


NAVY = colors.HexColor("#17365D")
BLUE = colors.HexColor("#2563EB")
PALE = colors.HexColor("#F1F5F9")
LINE = colors.HexColor("#D8E1EC")
MUTED = colors.HexColor("#64748B")
INK = colors.HexColor("#172033")


def _inr(value):
    """Use an ASCII currency label so every PDF viewer renders money correctly."""
    return f"INR {float(value or 0):,.2f}"


def _p(value, style):
    return Paragraph(escape(str(value or "")).replace("\n", "<br/>"), style)


def _company_mark(name, styles):
    initials = "".join(part[:1] for part in str(name or "Business").split()[:2]).upper() or "B"
    mark = Table([[Paragraph(escape(initials), ParagraphStyle(
        "BrandMark", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=17,
        textColor=colors.white, alignment=TA_CENTER, leading=20,
    ))]], colWidths=[23 * mm], rowHeights=[23 * mm])
    mark.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLUE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return mark


def _logo_or_mark(path, name, styles):
    if path:
        try:
            logo_path = Path(path)
            if logo_path.is_file():
                return Image(str(logo_path), width=25 * mm, height=23 * mm, kind="proportional", hAlign="LEFT")
        except Exception:
            pass
    return _company_mark(name, styles)


def generate_invoice_pdf(invoice_id, output_path):
    output_path = Path(output_path)
    with SessionLocal() as session:
        invoice = session.get(Invoice, int(invoice_id))
        if not invoice:
            raise ValueError("Invoice not found.")
        customer = session.get(Customer, invoice.customer_id)
        settings = session.scalar(select(BusinessSettings).limit(1))
        if not customer or not settings:
            raise ValueError("Customer or business settings not found.")
        items = list(session.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)))
        seller = {
            "name": settings.legal_name or "Business",
            "gstin": settings.gstin or "Not provided",
            "state": settings.state_code or "—",
            "address": settings.address or "",
            "phone": settings.phone or "",
            "logo": settings.logo_path or "",
        }
        buyer = {
            "name": customer.name or "",
            "gstin": customer.gstin or "Unregistered",
            "state": customer.state_code or "—",
            "address": customer.address or "",
            "phone": customer.phone or "",
        }
        data = {
            "number": invoice.invoice_number,
            "date": invoice.invoice_date.strftime("%d %b %Y"),
            "taxable": invoice.taxable_total,
            "cgst": invoice.cgst_total,
            "sgst": invoice.sgst_total,
            "igst": invoice.igst_total,
            "total": invoice.grand_total,
            "paid": invoice.amount_paid,
            "interstate": invoice.is_interstate,
            "items": items,
        }

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("InvoiceCompany", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=INK, spaceAfter=3))
    styles.add(ParagraphStyle("InvoiceBody", parent=styles["Normal"], fontSize=8.5, leading=12, textColor=INK))
    styles.add(ParagraphStyle("InvoiceMuted", parent=styles["Normal"], fontSize=7.5, leading=10, textColor=MUTED))
    styles.add(ParagraphStyle("InvoiceLabel", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=MUTED))
    styles.add(ParagraphStyle("InvoiceCardTitle", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.white))
    styles.add(ParagraphStyle("InvoiceCardText", parent=styles["Normal"], fontSize=8.5, leading=12, textColor=colors.white))
    styles.add(ParagraphStyle("InvoiceItem", parent=styles["Normal"], fontSize=7, leading=9, textColor=INK))
    styles.add(ParagraphStyle("InvoiceItemHead", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=6.5, leading=8, textColor=colors.white))
    styles.add(ParagraphStyle("InvoicePanelTitle", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=BLUE, spaceAfter=4))

    doc = SimpleDocTemplate(str(output_path), pagesize=A4,
                            rightMargin=8 * mm, leftMargin=8 * mm,
                            topMargin=9 * mm, bottomMargin=17 * mm,
                            title=f"Tax Invoice {data['number']}", author=seller["name"])
    usable_width = A4[0] - 16 * mm

    company_lines = [_p(seller["name"], styles["InvoiceCompany"]),
                     _p(f"GSTIN: {seller['gstin']}   |   State code: {seller['state']}", styles["InvoiceBody"])]
    if seller["address"]:
        company_lines.append(_p(seller["address"], styles["InvoiceMuted"]))
    if seller["phone"]:
        company_lines.append(_p(f"Phone: {seller['phone']}", styles["InvoiceMuted"]))
    invoice_card = Table([
        [Paragraph("TAX INVOICE", styles["InvoiceCardTitle"])],
        [Paragraph(f"<b>Invoice no.</b>  {escape(data['number'])}", styles["InvoiceCardText"])],
        [Paragraph(f"<b>Issue date</b>  {escape(data['date'])}", styles["InvoiceCardText"])],
    ], colWidths=[64 * mm])
    invoice_card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY), ("BOX", (0, 0), (-1, -1), 0, NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    header = Table([[_logo_or_mark(seller["logo"], seller["name"], styles), company_lines, invoice_card]],
                   colWidths=[27 * mm, usable_width - 27 * mm - 67 * mm, 67 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    buyer_panel = [Paragraph("BILL TO", styles["InvoicePanelTitle"]),
                   _p(buyer["name"], styles["InvoiceCompany"]),
                   _p(f"GSTIN: {buyer['gstin']}", styles["InvoiceBody"]),
                   _p(f"State code: {buyer['state']}", styles["InvoiceBody"])]
    if buyer["address"]: buyer_panel.append(_p(buyer["address"], styles["InvoiceMuted"]))
    if buyer["phone"]: buyer_panel.append(_p(f"Phone: {buyer['phone']}", styles["InvoiceMuted"]))
    supply_type = "Interstate - IGST" if data["interstate"] else "Intrastate - CGST + SGST"
    supply_panel = [Paragraph("SUPPLY DETAILS", styles["InvoicePanelTitle"]),
                    _p(f"Place of supply: State code {buyer['state']}", styles["InvoiceBody"]),
                    _p(f"Supply type: {supply_type}", styles["InvoiceBody"])]
    bill_supply = Table([[buyer_panel, supply_panel]], colWidths=[usable_width * .60, usable_width * .40])
    bill_supply.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE), ("BOX", (0, 0), (-1, -1), .6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), .5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))

    headers = ["Description", "HSN/SAC", "Qty", "Rate", "Disc.", "Taxable", "GST %", "CGST", "SGST", "IGST", "Total"]
    item_data = [[Paragraph(escape(label), styles["InvoiceItemHead"]) for label in headers]]
    for row in data["items"]:
        item_data.append([
            _p(row.description_snapshot, styles["InvoiceItem"]),
            _p(row.hsn_sac_snapshot or "—", styles["InvoiceItem"]),
            f"{float(row.quantity):,.3f}", f"{float(row.unit_price):,.2f}", f"{float(row.discount_amount):,.2f}",
            f"{float(row.taxable_value):,.2f}", f"{float(row.gst_rate_snapshot):g}%",
            f"{float(row.cgst_amount):,.2f}", f"{float(row.sgst_amount):,.2f}", f"{float(row.igst_amount):,.2f}", f"{float(row.line_total):,.2f}",
        ])
    widths = [40, 15, 11, 17, 13, 19, 12, 15, 15, 15, 22]
    item_table = Table(item_data, colWidths=[width * mm for width in widths], repeatRows=1, hAlign="LEFT")
    item_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), .35, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"), ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for row_index in range(1, len(item_data)):
        if row_index % 2 == 0: item_commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#F8FAFC")))
    item_table.setStyle(TableStyle(item_commands))

    paid = float(data["paid"] or 0); total = float(data["total"] or 0); due = total - paid
    status = "PAID" if due <= 0 else ("PARTIALLY PAID" if paid > 0 else "UNPAID")
    tax_rows = [["Taxable value", _inr(data["taxable"])]]
    if data["interstate"]:
        tax_rows.append(["IGST", _inr(data["igst"])])
    else:
        tax_rows.extend([["CGST", _inr(data["cgst"])], ["SGST", _inr(data["sgst"])]] )
    tax_rows.extend([["Invoice total", _inr(total)], ["Amount received", _inr(paid)], ["Balance due", _inr(due)]])
    totals = Table([[Paragraph(escape(label), styles["InvoiceBody"]),
                     Paragraph(escape(value), ParagraphStyle("MoneyRight", parent=styles["InvoiceBody"], alignment=TA_RIGHT))]
                    for label, value in tax_rows], colWidths=[47 * mm, 39 * mm], hAlign="RIGHT")
    total_style = [
        ("LINEBELOW", (0, 0), (-1, -1), .45, LINE), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, -1), (-1, -1), PALE), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BOX", (0, -1), (-1, -1), .7, LINE),
    ]
    if len(tax_rows) >= 3:
        total_style.append(("FONTNAME", (0, len(tax_rows) - 3), (-1, len(tax_rows) - 3), "Helvetica-Bold"))
    totals.setStyle(TableStyle(total_style))
    status_style = ParagraphStyle("InvoiceStatus", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=9, textColor=BLUE)
    payment_note = [Paragraph("PAYMENT STATUS", styles["InvoicePanelTitle"]),
                    Paragraph(escape(status), status_style),
                    _p("Please retain this invoice for your records.", styles["InvoiceMuted"])]
    summary = Table([[payment_note, totals]], colWidths=[usable_width - 86 * mm, 86 * mm])
    summary.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                 ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))

    def draw_footer(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE); canvas.setLineWidth(.5)
        canvas.line(8 * mm, 13 * mm, A4[0] - 8 * mm, 13 * mm)
        canvas.setFont("Helvetica", 7); canvas.setFillColor(MUTED)
        canvas.drawString(8 * mm, 8 * mm, f"{seller['name']}  |  {data['number']}")
        canvas.drawRightString(A4[0] - 8 * mm, 8 * mm, f"Page {_doc.page}")
        canvas.restoreState()

    currency_note = Paragraph("All amounts are in INR", ParagraphStyle("CurrencyNote", parent=styles["InvoiceMuted"], alignment=TA_RIGHT))
    story = [header, Spacer(1, 7 * mm), bill_supply, Spacer(1, 6 * mm), currency_note, item_table,
             Spacer(1, 5 * mm), summary, Spacer(1, 8 * mm),
             _p("This is a computer-generated tax invoice. Please verify the details and tax treatment.", styles["InvoiceMuted"])]
    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return str(output_path)


def generate_thermal_receipt(invoice_id, output_path, width_mm=80):
    """Generate a compact receipt with printer-safe ASCII currency labels."""
    if width_mm not in (58, 80): width_mm = 80
    output_path = Path(output_path)
    with SessionLocal() as session:
        invoice = session.get(Invoice, int(invoice_id))
        if not invoice: raise ValueError("Invoice not found.")
        customer = session.get(Customer, invoice.customer_id)
        settings = session.scalar(select(BusinessSettings).limit(1))
        if not customer or not settings: raise ValueError("Customer or business settings not found.")
        lines = list(session.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)))
        data = {"seller": settings.legal_name or "Business", "gstin": settings.gstin or "",
                "phone": settings.phone or "", "invoice": invoice.invoice_number,
                "date": invoice.invoice_date.strftime("%d-%m-%Y"), "customer": customer.name or "",
                "items": [(line.description_snapshot, line.quantity, line.line_total) for line in lines],
                "taxable": invoice.taxable_total, "cgst": invoice.cgst_total, "sgst": invoice.sgst_total,
                "igst": invoice.igst_total, "total": invoice.grand_total, "paid": invoice.amount_paid,
                "interstate": invoice.is_interstate}

    width = width_mm * mm; usable = width - 8 * mm; styles = getSampleStyleSheet()
    center = ParagraphStyle("ReceiptCenter", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=9, leading=11, alignment=TA_CENTER)
    small = ParagraphStyle("ReceiptSmall", parent=styles["Normal"], fontSize=7, leading=9)
    story = [_p(data["seller"], center), _p(f"GSTIN: {data['gstin'] or '-'}", small),
             _p(f"Phone: {data['phone'] or '-'}", small), Spacer(1, 2 * mm),
             _p("TAX INVOICE", center), _p(f"No: {data['invoice']} | {data['date']}", small),
             _p(f"Customer: {data['customer']}", small), Spacer(1, 2 * mm)]
    rows = [["Item / Qty", "Amount"]]
    for name, quantity, amount in data["items"]:
        rows.append([_p(f"{name} x {quantity}", small), _inr(amount)])
    table = Table(rows, colWidths=[usable * .60, usable * .40])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("GRID", (0, 0), (-1, -1), .25, LINE),
                               ("FONTSIZE", (0, 0), (-1, -1), 7), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story.extend([table, Spacer(1, 2 * mm), _p(f"Taxable: {_inr(data['taxable'])}", small)])
    if data["interstate"]:
        story.append(_p(f"IGST: {_inr(data['igst'])}", small))
    else:
        story.extend([_p(f"CGST: {_inr(data['cgst'])}", small), _p(f"SGST: {_inr(data['sgst'])}", small)])
    story.extend([_p(f"TOTAL: {_inr(data['total'])}", center), _p(f"Paid: {_inr(data['paid'])}", small),
                  _p(f"Balance: {_inr(float(data['total']) - float(data['paid']))}", small),
                  Spacer(1, 3 * mm), _p("Thank you", center)])
    height = max(100 * mm, (40 + len(data["items"]) * 12) * mm)
    doc = SimpleDocTemplate(str(output_path), pagesize=(width, height), rightMargin=4 * mm,
                            leftMargin=4 * mm, topMargin=4 * mm, bottomMargin=4 * mm)
    doc.build(story)
    return str(output_path)
