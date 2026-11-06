"""Delivery receipt -> fields with provenance.

Two routes into the same schema the rules read:
  PDF with a text layer   parsed directly from the page (no OCR, no AI). Every value keeps its
                          real page number and word box, so a reviewer can be shown exactly where
                          it came from. Confidence is 1.0: the text is exact.
  Image                   read by the vision model (live), or replayed from a cached reading
                          (mock, the default). No coordinates: a vision model's boxes would be
                          guesses, so none are invented.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pymupdf

from slipcheck.extract import ExtractionError, add_provenance, extract_live
from slipcheck.receiving.reference import RECEIVING_DIR

READINGS = RECEIVING_DIR / "readings"
HEADER = ("receipt_number", "po_number", "date", "vendor", "received_by")
ITEM = ("part_number", "part_name", "qty", "unit")
LABELS = {"receipt_number": "Receipt #:", "po_number": "PO #:", "date": "Date:",
          "vendor": "Vendor:", "received_by": "Received by:"}

PROMPT = """You are reading a delivery receipt (a packing slip from a vendor) for a storeroom.

Transcribe what is printed or written. Do NOT correct, normalize, look up, or infer anything:
if a unit is missing, return unit null. If a part number is missing, return null for it; do
not guess one from the description.

For every field return {"value": ..., "raw": "<characters as shown>", "confidence": 0.0-1.0},
where confidence is how sure you are that you read it correctly. If a field is blank, value
is null and confidence is 1.0. If a field is present but unreadable, value is null, raw is your
best attempt (use ? for unreadable characters) and confidence is below 0.5.

Return ONLY a JSON object of this shape, no prose:
{
  "receipt_number": F, "po_number": F, "date": F, "vendor": F, "received_by": F,
  "items": [ {"part_number": F, "part_name": F, "qty": F, "unit": F} ]
}
where F is the field object above and part_name is the item description. If the image is not
a delivery receipt, return {"not_a_slip": true}."""


# ---------------------------------------------------------------- PDF text layer


def _lines(words: list[tuple]) -> list[list[tuple]]:
    """Group words into visual lines by baseline, each line left to right."""
    out, current, last = [], [], None
    for w in sorted(words, key=lambda w: (round(w[3], 1), w[0])):
        if last is not None and abs(w[3] - last) > 2.0:
            out.append(sorted(current, key=lambda x: x[0]))
            current = []
        current.append(w)
        last = w[3]
    if current:
        out.append(sorted(current, key=lambda x: x[0]))
    return out


def _cell(words: list[tuple], document: str, page_size, name: str, line: int | None) -> dict:
    src = {"document": document, "page": 1, "page_size": page_size, "method": "pdf_text", "field": name,
           "line": line, "review_status": "unreviewed", "bbox": None}
    if not words:
        return {"value": None, "raw": None, "confidence": 1.0, "source": src}
    text = " ".join(w[4] for w in words)
    src["bbox"] = [round(min(w[0] for w in words), 1), round(min(w[1] for w in words), 1),
                   round(max(w[2] for w in words), 1), round(max(w[3] for w in words), 1)]
    return {"value": text, "raw": text, "confidence": 1.0, "source": src}


def parse_pdf(path: Path) -> dict:
    try:
        doc = pymupdf.open(path)
    except Exception as e:  # noqa: BLE001 - PyMuPDF raises several unrelated types for bad files
        raise ExtractionError(f"Could not open '{path.name}' as a PDF: {e}") from e
    with doc:
        if not len(doc):
            raise ExtractionError(f"'{path.name}' has no pages.")
        page = doc[0]
        words = page.get_text("words")
        size = [round(page.rect.width, 1), round(page.rect.height, 1)]
    if not words:
        raise ExtractionError(f"'{path.name}' has no text layer (a scan). Render it to an image and use the vision path.")

    rows = _lines(words)
    out: dict = {"_provenance": {"kind": "pdf text layer", "method": "pdf_text", "document": path.name,
                                 "extracted_on": date.today().isoformat()}}
    found = 0
    for name, label in LABELS.items():
        start = len(label.split())
        row = next((r for r in rows if " ".join(w[4] for w in r[:start]) == label), None)
        found += row is not None
        out[name] = _cell(row[start:] if row else [], path.name, size, name, None)

    header = next((r for r in rows if {"Part", "Description", "Qty", "Unit"} <= {w[4] for w in r}), None)
    if not found or header is None:
        raise ExtractionError(f"'{path.name}' does not look like a delivery receipt (no labelled fields or item table).")
    x = {w[4]: w[0] for w in header}
    cuts = [x["Part"] - 5, x["Description"] - 5, x["Qty"] - 5, x["Unit"] - 5]
    out["items"] = []
    below = rows[rows.index(header) + 1:]
    for n, row in enumerate(below, start=1):
        if not (row[0][4].isdigit() and row[0][0] < cuts[0]):
            break  # the footer, not an item row
        cols = {k: [w for w in row if lo <= w[0] < hi] for k, (lo, hi) in {
            "part_number": (cuts[0], cuts[1]), "part_name": (cuts[1], cuts[2]),
            "qty": (cuts[2], cuts[3]), "unit": (cuts[3], 1e9)}.items()}
        out["items"].append({k: _cell(v, path.name, size, k, n) for k, v in cols.items()})
    return out


# ---------------------------------------------------------------- image, vision path


def reading_path(photo: Path) -> Path:
    return READINGS / f"{photo.stem}.json"


def read_image(photo: Path, live: bool = False, save: bool = True) -> dict:
    path = reading_path(photo)
    if path.exists() and not live:
        return add_provenance(json.loads(path.read_text(encoding="utf-8")), photo.name, HEADER, ITEM)
    if not live:
        raise ExtractionError(
            f"No cached reading for '{photo.name}' (looked for {path}). Run with --live once "
            "(needs ANTHROPIC_API_KEY) to read it and save the reading.")
    data = extract_live(photo, prompt=PROMPT, header=HEADER, items=ITEM)
    if data.get("not_a_slip"):
        raise ExtractionError(f"'{photo.name}' does not look like a delivery receipt.")
    if save:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def read_receipt(path: Path, live: bool = False) -> dict:
    if not path.exists():
        raise ExtractionError(f"File not found: {path}")
    if path.suffix.lower() == ".pdf":
        return parse_pdf(path)
    return read_image(path, live=live)
