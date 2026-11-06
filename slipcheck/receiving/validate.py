"""Receiving rules: does this delivery receipt match its purchase order? No AI here.

Same output shape as the slip checker (Issue with line/key pins and one-click fixes), different
domain. Two ideas the slip checker doesn't have:
  * A short delivery is a legitimate partial delivery. It is a warning, the line stays open, and
    it is never a failure by itself.
  * Several problems need a decision, not a value: return the item, hold it for the buyer, or
    accept an over-shipment. A fix can therefore set `disposition` on a line.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from rapidfuzz import fuzz

from slipcheck.receiving.reference import (
    POLine, PurchaseOrder, ReceivingReference, fingerprint, norm_receipt_no, normalize_po,
)
from slipcheck.validate import (
    BLOCK, DESK, INFO, WARN, InvalidSlip, Issue, _fix, _norm, _review, as_field, parse_date, parse_qty,
    PIECE_WORDS, UNIT_WORDS,
)

NAME_MATCH = 85  # a name-only line is matched to a PO line at this score and this lead over the runner-up
NAME_GAP = 12
EXCLUDING = {"return": "Return to vendor", "hold": "Hold for the buyer"}


@dataclass
class ReceivingReport:
    status: str
    receipt_number: str | None
    po_number: str | None
    vendor: str | None
    received_on: str | None
    received_by: str | None
    lines: list[dict]  # what the receipt says, each tied to a PO line
    po_lines: list[dict]  # the PO as it stands after this receipt
    issues: list[Issue] = field(default_factory=list)

    @property
    def blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == BLOCK]

    def to_dict(self) -> dict:
        return asdict(self)


def _clean_part(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def _open_pos(ref: ReceivingReference, vendor: str | None, exclude: str | None = None) -> list[PurchaseOrder]:
    pos = [p for p in ref.pos.values() if not p.is_closed and p.po_number != exclude]
    if vendor:
        same = [p for p in pos if fuzz.token_set_ratio(_norm(vendor), _norm(p.vendor)) >= 80]
        pos = same or []
    return sorted(pos, key=lambda p: p.po_number)[:4]


def _po_label(po: PurchaseOrder) -> str:
    return f"{po.po_number}, {po.vendor}"


def _po_fixes(pos: list[PurchaseOrder]) -> tuple[list[str], list[dict]]:
    return [_po_label(p) for p in pos], [_fix(_po_label(p), po_number=p.po_number) for p in pos]


# ---------------------------------------------------------------- header


def _check_po(f_po, f_vendor, ref: ReceivingReference, issues: list[Issue]) -> tuple[PurchaseOrder | None, bool]:
    vendor = f_vendor.value if not f_vendor.empty else None
    if f_po.empty and f_po.unsure:
        issues.append(_review("po_number", f_po))
        return None, False
    if f_po.empty:
        s, fx = _po_fixes(_open_pos(ref, vendor))
        issues.append(Issue(BLOCK, "MISSING_PO", "po_number", "No PO number on the receipt.", DESK, s, fx))
        return None, False
    if f_po.unsure:
        issues.append(_review("po_number", f_po))
    number = normalize_po(f_po.value)
    po = ref.pos.get(number) if number else None
    if po is None:
        near = sorted((p for p in ref.pos.values() if not p.is_closed),
                      key=lambda p: (not (vendor and fuzz.token_set_ratio(_norm(vendor), _norm(p.vendor)) >= 80),
                                     -fuzz.ratio(number or str(f_po.value), p.po_number)))
        near = [p for p in near if fuzz.ratio(number or str(f_po.value), p.po_number) >= 75][:3]
        s, fx = _po_fixes(near)
        issues.append(Issue(BLOCK, "UNKNOWN_PO", "po_number", f"PO '{f_po.value}' does not exist in the system.", DESK, s, fx))
        return None, False
    closed = po.is_closed
    if closed:
        reason = "already fully received" if po.fully_received and po.status.upper() != "CLOSED" else "closed"
        s, fx = _po_fixes(_open_pos(ref, po.vendor, exclude=po.po_number))
        issues.append(Issue(BLOCK, "PO_CLOSED", "po_number",
                            f"{po.po_number} is {reason}. Goods can't be received against it.", DESK, s, fx))
    return po, closed


def _check_header(f_vendor, f_date, f_by, po: PurchaseOrder | None, today: date, issues: list[Issue]) -> str | None:
    if po and not f_vendor.empty and fuzz.token_set_ratio(_norm(str(f_vendor.value)), _norm(po.vendor)) < 80:
        issues.append(Issue(WARN, "VENDOR_MISMATCH", "vendor",
                            f"Receipt says '{f_vendor.value}' but {po.po_number} is with {po.vendor}.", DESK,
                            fixes=[_fix(f"Use {po.vendor}", vendor=po.vendor)]))
    if f_by.unsure:
        issues.append(_review("received_by", f_by))
    elif f_by.empty:
        issues.append(Issue(BLOCK, "MISSING_RECEIVED_BY", "received_by",
                            "Nobody is named as having received this delivery. Someone must sign for it.", DESK))
    if f_date.empty:
        issues.append(Issue(WARN, "MISSING_DATE", "date", f"No date on the receipt; using today ({today}).", DESK))
        return today.isoformat()
    if f_date.unsure:
        issues.append(_review("date", f_date))
    d = parse_date(f_date.value)
    if d is None:
        issues.append(Issue(WARN, "BAD_DATE", "date", f"Could not read date '{f_date.value}'.", DESK))
        return None
    if d > today:
        issues.append(Issue(WARN, "FUTURE_DATE", "date", f"Receipt is dated {d}, after today.", DESK))
    if po and d < po.ordered_on:
        issues.append(Issue(WARN, "BEFORE_PO_DATE", "date",
                            f"Receipt date {d} is before {po.po_number} was ordered ({po.ordered_on}).", DESK))
    return d.isoformat()


# ---------------------------------------------------------------- lines


def _candidates(text: str, po: PurchaseOrder, ref: ReceivingReference) -> list[tuple[POLine, float]]:
    scored = []
    for pol in po.lines:
        part = ref.parts.get(pol.part_number)
        texts = [pol.description, *( [part.name, *part.aliases] if part else [])]
        scored.append((pol, max(fuzz.token_set_ratio(_norm(text), _norm(t)) for t in texts)))
    return sorted(scored, key=lambda s: -s[1])


def _decision_fixes() -> list[dict]:
    return [_fix(label, disposition=key) for key, label in EXCLUDING.items()]


def _resolve_line(item: dict, n: int, po: PurchaseOrder, ref: ReceivingReference, issues: list[Issue],
                  listed: frozenset[str] = frozenset()) -> POLine | None:
    """`listed`: part numbers already written on other lines of this receipt (not offered as corrections)."""
    pn_f, name_f = as_field(item.get("part_number")), as_field(item.get("part_name"))
    for label, f in (("part_number", pn_f), ("part_name", name_f)):
        if f.unsure:
            issues.append(_review(f"line {n} {label}", f))
    pn = _clean_part(pn_f.value)
    if pn:
        pol = po.line_for(pn)
        if pol:
            return pol
        cands = ([(p, s) for p, s in _candidates(str(name_f.value), po, ref)
                  if s >= 70 and p.part_number not in listed][:2] if not name_f.empty else [])
        hint = f" The description looks like {cands[0][0].part_number}." if cands else ""
        issues.append(Issue(BLOCK, "UNORDERED_ITEM", f"line {n} part_number", f"{pn} is not on {po.po_number}.{hint}",
                            DESK, [f"{p.part_number} {p.description}" for p, _ in cands],
                            [_fix(f"Change to {p.part_number}", part_number=p.part_number) for p, _ in cands] + _decision_fixes()))
        return None
    if name_f.empty:
        if not (pn_f.unsure or name_f.unsure):
            issues.append(Issue(BLOCK, "NO_PART", f"line {n} part_number", "Line has no part number or description.", DESK,
                                fixes=_decision_fixes()))
        return None
    cands = _candidates(str(name_f.value), po, ref)
    (top, score), runner = cands[0], (cands[1][1] if len(cands) > 1 else 0)
    if score >= NAME_MATCH and score - runner >= NAME_GAP:
        issues.append(Issue(INFO, "NAME_MATCHED", f"line {n} part_name",
                            f"Description only: '{name_f.value}' matched to {top.part_number} {top.description} "
                            f"(match {score:.0f}, next best {runner:.0f}).", DESK))
        return top
    plausible = [(p, s) for p, s in cands if s >= 50]
    issues.append(Issue(BLOCK, "UNORDERED_ITEM", f"line {n} part_name",
                        f"Description only: '{name_f.value}' does not clearly match one line on {po.po_number}.", DESK,
                        [f"{p.part_number} {p.description}" for p, _ in plausible],
                        [_fix(f"Match to {p.part_number}", part_number=p.part_number) for p, _ in plausible] + _decision_fixes()))
    return None


def _reconcile_unit(qty: float, written: str | None, pol: POLine, open_qty: int):
    """(quantity in the PO's unit or None, [(severity, code, message, suggestions, fixes)])."""
    unit, size = pol.unit, pol.unit_size
    w = (written or "").strip().lower().rstrip(".")
    kind = None if not w else ("PIECE" if w in PIECE_WORDS else UNIT_WORDS.get(w, "OTHER"))

    def opt(q: int) -> dict:
        return _fix(f"{q} {unit}" + (f" ({q * size} pieces)" if size > 1 else ""), qty=q, unit=unit)

    if kind is None:
        if size == 1:
            return qty, []
        if qty % size:  # as pieces it would not be whole packs, so it must be packs
            return qty, [(WARN, "UNIT_ASSUMED", f"No unit written; read as {qty:g} {unit} because {qty:g} pieces "
                                                f"would not be a whole {unit}.", [], [])]
        q = int(qty)
        return None, [(BLOCK, "UNIT_AMBIGUOUS",
                       f"'{q}' with no unit, and {pol.part_number} is ordered in {unit} of {size}. Did the delivery bring "
                       f"{q} {unit} ({q * size} pieces) or {q // size} {unit} ({q} pieces)?",
                       [f"{q} {unit}", f"{q // size} {unit}"], [opt(q), opt(q // size)])]
    if kind == unit or (kind == "PIECE" and size == 1):
        return qty, []
    if kind == "PIECE":
        if qty % size == 0:
            return qty // size, [(INFO, "UNIT_CONVERTED",
                                  f"{qty:g} pieces converted to {int(qty // size)} {unit} ({size} per {unit}).", [], [])]
        options = [int(qty)] if qty <= open_qty else []
        options += [n for n in (int(qty // size), int(qty // size) + 1) if n and n not in options]
        return None, [(BLOCK, "UNIT_REMAINDER",
                       f"{qty:g} pieces of {pol.part_number}, which is ordered in {unit} of {size}. That is not a whole {unit}.",
                       [f"{n} {unit}" for n in options], [opt(n) for n in options] + [_fix(EXCLUDING["hold"], disposition="hold")])]
    return None, [(BLOCK, "UNIT_MISMATCH", f"Receipt says {qty:g} {written}, but {pol.part_number} was ordered in {unit}.",
                   [f"{qty:g} {unit}"], [opt(int(qty))] + [_fix(EXCLUDING["hold"], disposition="hold")])]


# ---------------------------------------------------------------- entry point


def validate_receipt(reading: Any, ref: ReceivingReference, today: date | None = None) -> ReceivingReport:
    if not isinstance(reading, dict):
        raise InvalidSlip(f"Expected a receipt object, got {type(reading).__name__}.")
    known = {"receipt_number", "po_number", "vendor", "date", "received_by", "items"}
    if not known & reading.keys():
        raise InvalidSlip(f"Input has none of the receipt fields ({', '.join(sorted(known))}). Is this a delivery receipt?")
    today = today or date.today()
    issues: list[Issue] = []
    f_no, f_po, f_vendor, f_date, f_by = (as_field(reading.get(k)) for k in
                                          ("receipt_number", "po_number", "vendor", "date", "received_by"))

    po, closed = _check_po(f_po, f_vendor, ref, issues)
    received_on = _check_header(f_vendor, f_date, f_by, po, today, issues)

    rn = norm_receipt_no(f_no.value) if not f_no.empty else ""
    duplicate = False
    if f_no.unsure:
        issues.append(_review("receipt_number", f_no))
    if not rn:
        issues.append(Issue(WARN, "MISSING_RECEIPT_NUMBER", "receipt_number",
                            "No receipt number, so a repeat of this delivery could not be detected.", DESK))
    elif rn in ref.known_receipts:
        seen = ref.known_receipts[rn]
        duplicate = True
        issues.append(Issue(BLOCK, "DUPLICATE_RECEIPT", "receipt_number",
                            f"Receipt {rn} was already received on {seen['received_on']} ({seen['source']}). "
                            "Receiving it again would count the goods twice.", DESK))

    items = reading.get("items") or []
    if not isinstance(items, list) or not items:
        issues.append(Issue(BLOCK, "NO_ITEMS", "items", "No items listed on the receipt.", DESK))
        items = []

    lines: list[dict] = []
    mapped: dict[int, list[dict]] = {}  # PO line -> receipt lines that count toward it
    on_receipt = {n: _clean_part(as_field(i.get("part_number")).value) for n, i in enumerate(items, 1) if isinstance(i, dict)}
    for n, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            issues.append(Issue(BLOCK, "BAD_LINE", f"line {n}", f"Unreadable line: {item!r}", DESK))
            continue
        row = {"line": n, "part_number": None, "description": None, "po_line": None, "written": None,
               "qty": None, "unit": None, "counts": False, "disposition": item.get("disposition")}
        name_f, qty_f, unit_f = as_field(item.get("part_name")), as_field(item.get("qty")), as_field(item.get("unit"))
        row["description"] = None if name_f.empty else str(name_f.value)
        row["written"] = " ".join(x for x in (None if qty_f.empty else str(qty_f.value),
                                              None if unit_f.empty else str(unit_f.value)) if x)
        lines.append(row)
        if po is None:
            continue
        if row["disposition"] in EXCLUDING:
            issues.append(Issue(INFO, "LINE_RETURNED" if row["disposition"] == "return" else "LINE_HELD",
                                f"line {n} part_number", f"Line {n} is excluded from this receipt: "
                                f"{EXCLUDING[row['disposition']].lower()}.", DESK))
            continue
        pol = _resolve_line(item, n, po, ref, issues, frozenset(p for k, p in on_receipt.items() if k != n and p))
        if pol is None:
            continue
        row.update(part_number=pol.part_number, po_line=pol.line, unit=pol.unit)
        if qty_f.unsure:
            issues.append(_review(f"line {n} qty", qty_f))
        if qty_f.empty:
            if not qty_f.unsure:
                issues.append(Issue(BLOCK, "MISSING_QTY", f"line {n} qty", "No quantity written.", DESK))
            continue
        qty = parse_qty(qty_f.value)
        if qty is None or qty <= 0 or qty != int(qty):
            issues.append(Issue(BLOCK, "BAD_QTY", f"line {n} qty", f"Quantity '{qty_f.value}' is not a whole positive number.", DESK))
            continue
        norm_qty, specs = _reconcile_unit(qty, None if unit_f.empty else str(unit_f.value), pol, po.open_qty(pol.part_number))
        for severity, code, message, suggestions, fixes in specs:
            issues.append(Issue(severity, code, f"line {n} unit" if code != "UNIT_ASSUMED" else f"line {n} qty",
                                message, DESK, suggestions, fixes))
        if norm_qty is None:
            continue
        row.update(qty=int(norm_qty), counts=True)
        mapped.setdefault(pol.line, []).append(row)

    po_lines: list[dict] = []
    # A blocked line may be one of the PO's own lines, so "not delivered" can't be judged yet.
    unsettled = any(not r["counts"] and r["disposition"] not in EXCLUDING for r in lines)
    if po is not None:
        for pol in po.lines:
            rows = mapped.get(pol.line, [])
            got = sum(r["qty"] for r in rows)
            before = po.received.get(pol.part_number, 0)
            open_ = max(0, pol.qty_ordered - before)
            state = ("complete" if open_ == 0 and not got else "pending" if unsettled and not got
                     else "not delivered" if not got else None)
            if len(rows) > 1:
                issues.append(Issue(WARN, "DUPLICATE_LINE", f"line {rows[1]['line']} part_number",
                                    f"{pol.part_number} appears on lines {', '.join(str(r['line']) for r in rows)}; "
                                    "the quantities are added.", DESK))
            if not closed and not duplicate and rows:
                first = rows[0]["line"]
                if got > open_ and not any(r["disposition"] == "accept_over" for r in rows):
                    extra = got - open_
                    fixes = ([_fix(f"Receive {open_} and return {extra}", qty=open_)] if open_ and len(rows) == 1 else [])
                    fixes += [_fix(f"Accept all {got} (over-shipment)", disposition="accept_over"),
                              _fix(EXCLUDING["return"], disposition="return")]
                    issues.append(Issue(BLOCK, "OVER_SHIPMENT", f"line {first} qty",
                                        f"{got} {pol.unit} received but only {open_} still open on {po.po_number} "
                                        f"({pol.qty_ordered} ordered, {before} already received): {extra} too many.",
                                        DESK, [f.get("label") for f in fixes], fixes))
                    state = "over"
                elif got > open_:
                    issues.append(Issue(INFO, "OVER_ACCEPTED", f"line {first} qty",
                                        f"Over-shipment of {got - open_} {pol.unit} accepted.", DESK))
                    state = "over (accepted)"
                elif got < open_:
                    issues.append(Issue(WARN, "SHORT_SHIPMENT", f"line {first} qty",
                                        f"Partial delivery: {got} of {open_} still open for {pol.part_number}; "
                                        f"{open_ - got} {pol.unit} remain on order. The line stays open.", DESK))
                    state = "partial"
                else:
                    state = "complete"
            elif not closed and not duplicate and not unsettled and not got and open_ > 0:
                issues.append(Issue(WARN, "LINE_NOT_DELIVERED", f"PO line {pol.line}",
                                    f"{pol.part_number} ({pol.description}) is not on this delivery; {open_} {pol.unit} "
                                    "remain on order.", DESK))
            po_lines.append({"line": pol.line, "part_number": pol.part_number, "description": pol.description,
                             "unit": pol.unit, "ordered": pol.qty_ordered, "received_before": before, "this_receipt": got,
                             "open_after": max(0, open_ - got), "state": state or "-"})

    severities = {i.severity for i in issues}
    status = "BLOCKED" if BLOCK in severities else "READY_WITH_WARNINGS" if WARN in severities else "READY"
    return ReceivingReport(status, rn or None, po.po_number if po else None, po.vendor if po else None, received_on,
                           None if f_by.empty else str(f_by.value), lines, po_lines, issues)


def receipt_fingerprint(report: ReceivingReport) -> str:
    return fingerprint(report.po_number or "", report.received_on,
                       [(r["part_number"], r["qty"], r["unit"]) for r in report.lines if r["counts"]])
