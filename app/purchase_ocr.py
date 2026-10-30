"""Local OCR helpers for pre-filling purchase entries from supplier bills."""

from datetime import datetime
from pathlib import Path
import re
import tempfile

_OCR_ENGINE = None


def _normalize(value):
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _ocr_image(engine, image_path):
    result = engine(str(image_path))
    return list(getattr(result, "txts", ()) or ())


def read_bill_text(file_path):
    """Read the first three pages of a bill photo or PDF using local OCR."""
    global _OCR_ENGINE
    from rapidocr import RapidOCR

    path = Path(file_path)
    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()
    engine = _OCR_ENGINE
    if path.suffix.lower() != ".pdf":
        return "\n".join(_ocr_image(engine, path))

    import pymupdf as fitz

    pages_text = []
    temp_root = Path(__file__).resolve().parent.parent
    with fitz.open(path) as document, tempfile.TemporaryDirectory(prefix="purchase-ocr-", dir=temp_root) as temp_dir:
        for index, page in enumerate(document[:3]):
            image_path = Path(temp_dir) / f"page-{index + 1}.png"
            page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(image_path)
            pages_text.extend(_ocr_image(engine, image_path))
    return "\n".join(pages_text)


def suggest_purchase_fields(text, suppliers, products):
    """Return only conservative matches; uncertain fields stay for manual entry."""
    normalized_text = _normalize(text)
    suggestions = {}

    for supplier in suppliers:
        name = _normalize(supplier.name)
        if len(name) >= 4 and name in normalized_text:
            suggestions["supplier_id"] = supplier.id
            break

    number_patterns = (
        r"(?:invoice|bill)\s*(?:no\.?|number|#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]{2,})",
        r"(?:inv\.?\s*no\.?|bill\s*#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]{2,})",
    )
    for pattern in number_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            suggestions["invoice_number"] = match.group(1).strip("-/:#")
            break

    date_match = re.search(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})\b", text)
    if date_match:
        raw_date = date_match.group(1).replace(".", "/").replace("-", "/")
        formats = ("%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d")
        for date_format in formats:
            try:
                suggestions["purchase_date"] = datetime.strptime(raw_date, date_format).date()
                break
            except ValueError:
                continue

    for product in products:
        for candidate in (product.sku, product.name):
            normalized_candidate = _normalize(candidate)
            if len(normalized_candidate) >= 3 and normalized_candidate in normalized_text:
                suggestions["product_id"] = product.id
                break
        if "product_id" in suggestions:
            break

    quantity_match = re.search(r"\b(?:qty|quantity)\s*[:#-]?\s*(\d+(?:\.\d{1,3})?)\b", text, re.IGNORECASE)
    if quantity_match:
        suggestions["quantity"] = float(quantity_match.group(1))

    cost_match = re.search(r"\b(?:unit\s*(?:price|cost)|purchase\s*rate)\s*[:#-]?\s*₹?\s*([\d,]+(?:\.\d{1,2})?)\b", text, re.IGNORECASE)
    if not cost_match:
        cost_match = re.search(r"(?<!gst )(?<!tax )\brate\s*[:#-]?\s*₹?\s*([\d,]+(?:\.\d{1,2})?)\b", text, re.IGNORECASE)
    if cost_match:
        suggestions["unit_cost"] = float(cost_match.group(1).replace(",", ""))

    return suggestions
