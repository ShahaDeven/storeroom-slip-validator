"""Purchase orders and receiving history: synthetic CSVs standing in for the buyer's ERP."""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from slipcheck.reference import DATA_DIR, Part, load_reference
from slipcheck.validate import parse_date

RECEIVING_DIR = DATA_DIR / "receiving"


@dataclass(frozen=True)
class POLine:
    line: int
    part_number: str
    description: str
    qty_ordered: int
    unit: str  # EA / BX / PR / RL
    unit_size: int  # pieces per unit (a box of 100 = 100)


@dataclass
class PurchaseOrder:
    po_number: str
    vendor: str
    status: str  # OPEN | CLOSED, as the system has it
    ordered_on: date
    lines: list[POLine]
    received: dict[str, int] = field(default_factory=dict)  # part number -> received to date, in the PO's unit

    def line_for(self, part_number: str) -> POLine | None:
        return next((ln for ln in self.lines if ln.part_number == part_number), None)

    def open_qty(self, part_number: str) -> int:
        ln = self.line_for(part_number)
        return max(0, ln.qty_ordered - self.received.get(part_number, 0)) if ln else 0

    @property
    def fully_received(self) -> bool:
        return all(self.received.get(ln.part_number, 0) >= ln.qty_ordered for ln in self.lines)

    @property
    def is_closed(self) -> bool:
        return self.status.upper() == "CLOSED" or self.fully_received


@dataclass
class ReceivingReference:
    pos: dict[str, PurchaseOrder]
    parts: dict[str, Part]
    known_receipts: dict[str, dict] = field(default_factory=dict)  # receipt number -> where it was seen
    fingerprints: dict[str, str] = field(default_factory=dict)  # content fingerprint -> receipt number


def norm_receipt_no(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def normalize_po(raw) -> str | None:
    """'po 26 1101', 'PO-26-1101' -> 'PO-26-1101'; None if no number is present."""
    digits = re.findall(r"\d+", str(raw or ""))
    if len(digits) < 2:
        return None
    return f"PO-{digits[-2][-2:]}-{digits[-1]}"


def fingerprint(po_number: str, received_on: str | None, lines: list[tuple[str, int, str]]) -> str:
    """Same PO, date and quantities = the same delivery, whatever number it was given."""
    key = f"{po_number}|{received_on}|" + ";".join(f"{p}:{q}:{u}" for p, q, u in sorted(lines))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _iso(text: str) -> str | None:
    d = parse_date(text)
    return d.isoformat() if d else None


def load_receiving(posted: list[dict] | tuple = (), data_dir: Path = RECEIVING_DIR) -> ReceivingReference:
    """POs with what has been received so far: seed history plus anything posted this session.

    `posted` items: {"receipt_number", "po_number", "received_on" (ISO), "lines": [{"part_number", "qty", "unit"}]}.
    """
    parts = load_reference().parts
    pos: dict[str, PurchaseOrder] = {}
    with open(data_dir / "purchase_orders.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            po = pos.setdefault(row["po_number"], PurchaseOrder(
                row["po_number"], row["vendor"], row["status"], parse_date(row["ordered_on"]), []))
            po.lines.append(POLine(int(row["line"]), row["part_number"], row["description"],
                                   int(row["qty_ordered"]), row["unit"], int(row["unit_size"])))
    ref = ReceivingReference(pos, parts)

    seed: dict[str, dict] = {}
    with open(data_dir / "receipts_seed.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            r = seed.setdefault(row["receipt_number"], {
                "receipt_number": row["receipt_number"], "po_number": row["po_number"],
                "received_on": _iso(row["received_on"]), "lines": [], "source": "history"})
            r["lines"].append({"part_number": row["part_number"], "qty": int(row["qty"]), "unit": row["unit"]})
    for receipt in [*seed.values(), *({**p, "source": "posted this session"} for p in posted)]:
        po = pos.get(receipt["po_number"])
        for ln in receipt["lines"]:
            if po:
                po.received[ln["part_number"]] = po.received.get(ln["part_number"], 0) + int(ln["qty"])
        key = norm_receipt_no(receipt["receipt_number"])
        ref.known_receipts[key] = {"po_number": receipt["po_number"], "received_on": receipt["received_on"],
                                   "source": receipt["source"]}
        ref.fingerprints[fingerprint(receipt["po_number"], receipt["received_on"],
                                     [(ln["part_number"], int(ln["qty"]), ln["unit"]) for ln in receipt["lines"]])] = key
    return ref
