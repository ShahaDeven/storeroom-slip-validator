"""Evidence for each discrepancy: what was read, what the system of record says, and which rule fired.

Built AFTER validation, from the report and the reference data, so it explains decisions without
taking part in them (the slip rules stay exactly as frozen for the evaluation). One entry per
issue, in the same order as report.issues:

  rule        the check in plain words, what it compares against, and what the outcome does
  extracted   the field as it was read: value, raw text, confidence, and its provenance
              (document, line, method, model; a real word box only for PDF text)
  reference   the record it was compared with (work order, catalog part, PO line, receipt history)

The human correction is recorded by the UI as answers are applied, and the posted entry keeps the
answers given (ledger postings / receipts).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from slipcheck.reference import Part, Reference
from slipcheck.validate import BLOCK, INFO, REVIEW_THRESHOLD, WARN, as_field, normalize_wo

# code -> (the rule in plain words, what it is checked against)
RULES: dict[str, tuple[str, str]] = {
    # slips: work order
    "MISSING_WO": ("Every pull is charged to a work order; a slip without one can't post.", "work orders"),
    "UNKNOWN_WO": ("The W/O number must exist in the work-order system.", "work orders"),
    "CLOSED_WO": ("Parts can't be recorded against a closed work order.", "work orders"),
    "NOT_ON_CREW": ("The person who took the parts must be on the crew that owns the work order, or a person "
                    "confirms they are helping on it (rules v2; a warning in v1).", "work orders"),
    "CREW_CONFIRMED": ("Someone from another crew, confirmed by a person as working on this job.", "work orders"),
    "LOCATION_MISMATCH": ("The building on the slip should match the work order's location.", "work orders"),
    "LOCATION_FROM_WO": ("No building written, so the work order's location is used.", "work orders"),
    "BEFORE_WO_OPENED": ("A slip can't be dated before its work order was opened.", "work orders"),
    # slips: header
    "MISSING_SIGNATURE": ("A slip must be signed by the person taking the parts.", "the slip itself"),
    "MISSING_TAKEN_BY": ("A slip must name who took the parts.", "the slip itself"),
    "MISSING_DATE": ("A slip should be dated; today's date is used if not.", "the slip itself"),
    "BAD_DATE": ("The date must be a readable date.", "the slip itself"),
    "FUTURE_DATE": ("A slip can't be dated after today.", "today's date"),
    "NO_ITEMS": ("A slip must list at least one part.", "the slip itself"),
    "BAD_LINE": ("Each line must be a readable part line.", "the slip itself"),
    # slips: parts
    "UNKNOWN_PART": ("A written part number must exist in the catalog.", "parts catalog"),
    "NAME_NUMBER_MISMATCH": ("The description must fit the part number written next to it.", "parts catalog"),
    "PART_AMBIGUOUS": ("A description with no number is matched only when one catalog part clearly wins "
                       "(score 88+ and 12+ ahead of the next).", "parts catalog"),
    "NAME_MATCHED": ("A description with no number matched one catalog part clearly (score 88+, 12+ ahead).",
                     "parts catalog"),
    "NO_PART": ("A line needs a part number or a description.", "the slip itself"),
    "DUPLICATE_PART": ("The same part on two lines is flagged, so both pulls are confirmed.", "the slip itself"),
    # slips: quantity and unit
    "MISSING_QTY": ("Every line needs a quantity.", "the slip itself"),
    "BAD_QTY": ("A quantity must be a whole positive number.", "the slip itself"),
    "UNIT_AMBIGUOUS": ("A bare number on a part tracked in pairs or boxes is never converted silently: "
                       "the crew says which they meant.", "parts catalog (unit of issue)"),
    "UNIT_REMAINDER": ("Pieces must make whole units of issue (3 gloves is not a whole number of pairs).",
                       "parts catalog (unit of issue)"),
    "UNIT_CONVERTED": ("Pieces that make whole units are converted to the unit of issue.", "parts catalog (unit of issue)"),
    "UNIT_ASSUMED": ("An odd bare number on a pair-tracked part can only mean pairs.", "parts catalog (unit of issue)"),
    "UNIT_MISMATCH": ("The written unit should match how the part is issued.", "parts catalog (unit of issue)"),
    "EXCEEDS_ON_HAND": ("A pull can't be larger than the stock the system shows: the slip or the count is wrong.",
                        "inventory on hand"),
    "UNUSUAL_QTY": ("A pull above the usual maximum for that part is flagged.", "parts catalog (max per pull)"),
    "CONFIRM_QTY": ("A quantity read by the model is confirmed by a person against the paper before posting: a "
                    "plausible misread passes every other rule, however confident the model is (rules v2).",
                    "the paper slip (a person)"),
    # both
    "HUMAN_REVIEW": (f"A field read with confidence below {REVIEW_THRESHOLD:.2f} is never trusted: a person "
                     "checks the paper. Illegible is not the same as blank.", "the reading's own confidence"),
    # receiving
    "MISSING_PO": ("A receipt must name the purchase order it delivers against.", "purchase orders"),
    "UNKNOWN_PO": ("The PO number must exist.", "purchase orders"),
    "PO_CLOSED": ("Nothing can be received against a PO that is closed or fully received.", "purchase orders"),
    "VENDOR_MISMATCH": ("The receipt's vendor must be the PO's vendor.", "purchase orders"),
    "MISSING_RECEIVED_BY": ("Someone must sign for a delivery.", "the receipt itself"),
    "BEFORE_PO_DATE": ("A delivery can't be dated before its PO was ordered.", "purchase orders"),
    "MISSING_RECEIPT_NUMBER": ("Without a receipt number a repeat of this delivery can't be detected.", "the receipt itself"),
    "DUPLICATE_RECEIPT": ("A receipt number can be received only once.", "receiving history"),
    "POSSIBLE_DUPLICATE": ("Same PO, date and quantities as a receipt already received means a likely double count.",
                           "receiving history"),
    "SEPARATE_DELIVERY": ("Confirmed by a person as a separate delivery, not a duplicate.", "receiving history"),
    "UNORDERED_ITEM": ("Every line must match a line on the PO.", "purchase order lines"),
    "OVER_SHIPMENT": ("More than is still open on the PO needs a decision: receive the open amount, accept, or return.",
                      "purchase order lines (received to date)"),
    "OVER_ACCEPTED": ("An over-shipment was accepted by a person.", "purchase order lines"),
    "SHORT_SHIPMENT": ("Less than is open is a partial delivery: the line stays open.", "purchase order lines (received to date)"),
    "LINE_NOT_DELIVERED": ("A PO line missing from the receipt stays open.", "purchase order lines"),
    "DUPLICATE_LINE": ("The same part on two receipt lines is added together, and shown.", "the receipt itself"),
    "LINE_RETURNED": ("A line marked for return is left out of the receipt.", "the clerk's decision"),
    "LINE_HELD": ("A line held for the buyer is left out of the receipt.", "the clerk's decision"),
    "BLIND_COUNT": ("A quantity read from an image is received only after a person counts the goods.",
                    "the delivered goods (a count)"),
    "BAD_COUNT": ("A count must be a whole number.", "the delivered goods (a count)"),
    "COUNT_MISMATCH": ("A count that differs from the reading stops the receipt: receive what was counted, or recount.",
                       "the delivered goods (a count)"),
    "COUNT_MATCHES": ("The count agreed with the reading.", "the delivered goods (a count)"),
}
OUTCOME = {BLOCK: "Blocks posting until a person answers.", WARN: "Warning only: shown, and the entry can still post.",
           INFO: "Information: done automatically and recorded."}
FIELD_LABEL = {"wo_number": "W/O number", "date": "Date", "taken_by": "Taken by", "location": "Location",
               "signature": "Signature", "part_number": "Part number", "part_name": "Description", "qty": "Quantity",
               "unit": "Unit", "po_number": "PO number", "vendor": "Vendor", "received_by": "Received by",
               "receipt_number": "Receipt number"}


def _rule(issue) -> dict:
    text, against = RULES.get(issue.code, ("", ""))
    return {"code": issue.code, "text": text, "checks_against": against, "outcome": OUTCOME.get(issue.severity, "")}


def _extracted(doc: dict, issue) -> dict | None:
    key = "qty" if issue.key == "counted" else issue.key  # a count is checked against the quantity read
    if not key or key in ("items",):
        return None
    if issue.line is not None:
        items = doc.get("items") or []
        if not (0 < issue.line <= len(items)) or not isinstance(items[issue.line - 1], dict):
            return None
        container = items[issue.line - 1]
    else:
        container = doc
    if key not in container:
        return None
    f = as_field(container.get(key))
    return {"field": FIELD_LABEL.get(key, key), "line": issue.line, "value": f.value, "raw": f.raw,
            "confidence": f.confidence, "source": f.source}


def _rows(*pairs: tuple[str, Any]) -> list[list[str]]:
    return [[k, "" if v is None else str(v)] for k, v in pairs]


def _part_rows(p: Part, on_hand: int | None = None) -> list[list[str]]:
    return _rows(("Part", p.part_number), ("Catalog name", p.name), ("Also written as", ", ".join(p.aliases) or "-"),
                 ("Issued in", f"{p.unit}" + (f" ({p.unit_size} pieces each)" if p.unit_size > 1 else "")),
                 ("Aisle", p.aisle), ("On hand now", p.on_hand if on_hand is None else on_hand),
                 ("Usual max per pull", p.max_per_pull))


# ---------------------------------------------------------------- slips

WO_CODES = {"MISSING_WO", "UNKNOWN_WO", "CLOSED_WO", "NOT_ON_CREW", "CREW_CONFIRMED", "LOCATION_MISMATCH", "LOCATION_FROM_WO",
            "BEFORE_WO_OPENED"}
PART_CODES = {"UNKNOWN_PART", "NAME_NUMBER_MISMATCH", "PART_AMBIGUOUS", "NAME_MATCHED", "NO_PART", "DUPLICATE_PART",
              "UNIT_AMBIGUOUS", "UNIT_REMAINDER", "UNIT_CONVERTED", "UNIT_ASSUMED", "UNIT_MISMATCH",
              "EXCEEDS_ON_HAND", "UNUSUAL_QTY", "MISSING_QTY", "BAD_QTY", "CONFIRM_QTY"}


def _slip_reference(slip: dict, report, ref: Reference, issue, today: date) -> dict | None:
    if issue.code in WO_CODES:
        number = normalize_wo(as_field(slip.get("wo_number")).value, today.year) if slip.get("wo_number") else None
        wo = ref.work_orders.get(number) if number else None
        if wo is None:
            return {"title": f"No work order {number} in the work-order system" if number else "Work-order system",
                    "rows": [], "candidates": issue.suggestions}
        return {"title": f"Work order {wo.wo_number}, as the work-order system has it",
                "rows": _rows(("Status", wo.status), ("Crew", wo.crew), ("Members", ", ".join(wo.members)),
                              ("Location", wo.location), ("Opened", wo.opened), ("Closed", wo.closed or "-")),
                "candidates": issue.suggestions}
    if issue.code in PART_CODES and issue.line:
        line = next((ln for ln in report.lines if ln.line == issue.line), None)
        items = slip.get("items") or []
        item = items[issue.line - 1] if 0 < issue.line <= len(items) and isinstance(items[issue.line - 1], dict) else {}
        written = re.sub(r"\s+", "", str(as_field(item.get("part_number")).value or "")).upper()
        part = ref.parts.get(line.part_number) if line and line.part_number else ref.parts.get(written)
        if part is None:
            title = f"No part {written} in the catalog" if written else "Parts catalog"
            return {"title": title, "rows": [], "candidates": issue.suggestions}
        return {"title": f"Catalog record for {part.part_number}", "rows": _part_rows(part),
                "candidates": issue.suggestions}
    if issue.code == "HUMAN_REVIEW":
        return {"title": "Review threshold", "rows": _rows(("Trusted from", f"confidence {REVIEW_THRESHOLD:.2f}")),
                "candidates": []}
    if issue.code == "FUTURE_DATE":
        return {"title": "Today", "rows": _rows(("Date", today)), "candidates": []}
    return None


def slip_evidence(slip: dict, report, ref: Reference, today: date | None = None) -> list[dict]:
    today = today or date.today()
    return [{"rule": _rule(i), "extracted": _extracted(slip, i),
             "reference": _slip_reference(slip, report, ref, i, today)} for i in report.issues]


# ---------------------------------------------------------------- receipts

PO_CODES = {"MISSING_PO", "UNKNOWN_PO", "PO_CLOSED", "VENDOR_MISMATCH", "BEFORE_PO_DATE"}
HISTORY_CODES = {"DUPLICATE_RECEIPT", "POSSIBLE_DUPLICATE", "SEPARATE_DELIVERY"}


def _receipt_reference(reading: dict, report, ref, issue) -> dict | None:
    from slipcheck.receiving.reference import normalize_po, norm_receipt_no

    number = normalize_po(as_field(reading.get("po_number")).value)
    po = ref.pos.get(report.po_number or number or "")
    if issue.code in PO_CODES:
        if po is None:
            return {"title": f"No purchase order {number}" if number else "Purchase orders", "rows": [],
                    "candidates": issue.suggestions}
        return {"title": f"Purchase order {po.po_number}",
                "rows": _rows(("Vendor", po.vendor), ("Status", "CLOSED" if po.is_closed else "OPEN"),
                              ("Ordered on", po.ordered_on),
                              ("Lines", "; ".join(f"{ln.part_number} x{ln.qty_ordered} {ln.unit}" for ln in po.lines))),
                "candidates": issue.suggestions}
    if issue.code in HISTORY_CODES:
        rn = norm_receipt_no(as_field(reading.get("receipt_number")).value)
        m = re.search(r"\b(R-\d+)\b", issue.message)
        twin = rn if issue.code == "DUPLICATE_RECEIPT" else (m.group(1) if m else None)
        seen = ref.known_receipts.get(twin or "")
        if not seen:
            return {"title": "Receiving history", "rows": [], "candidates": []}
        return {"title": f"Receipt {twin} in the receiving history",
                "rows": _rows(("PO", seen["po_number"]), ("Received on", seen["received_on"]), ("Where", seen["source"])),
                "candidates": []}
    if issue.code == "HUMAN_REVIEW":
        return {"title": "Review threshold", "rows": _rows(("Trusted from", f"confidence {REVIEW_THRESHOLD:.2f}")),
                "candidates": []}
    if po is None:
        return None
    m = re.match(r"PO line (\d+)", issue.where)
    pol = None
    if m:
        pol = next((ln for ln in po.lines if ln.line == int(m.group(1))), None)
    elif issue.line:
        row = next((r for r in report.lines if r["line"] == issue.line), None)
        if row and row.get("part_number"):
            pol = po.line_for(row["part_number"])
    if pol is None:
        if issue.code == "UNORDERED_ITEM":
            return {"title": f"What {po.po_number} ordered",
                    "rows": [[ln.part_number, f"{ln.description}, {ln.qty_ordered} {ln.unit}"] for ln in po.lines],
                    "candidates": issue.suggestions}
        return None
    before = po.received.get(pol.part_number, 0)
    return {"title": f"{po.po_number} line {pol.line}",
            "rows": _rows(("Part", f"{pol.part_number} {pol.description}"),
                          ("Ordered", f"{pol.qty_ordered} {pol.unit}" + (f" ({pol.unit_size} pieces each)" if pol.unit_size > 1 else "")),
                          ("Received before this receipt", f"{before} {pol.unit}"),
                          ("Still open", f"{max(0, pol.qty_ordered - before)} {pol.unit}")),
            "candidates": issue.suggestions}


def receipt_evidence(reading: dict, report, ref) -> list[dict]:
    return [{"rule": _rule(i), "extracted": _extracted(reading, i),
             "reference": _receipt_reference(reading, report, ref, i)} for i in report.issues]
