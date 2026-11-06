"""Posted receipts and the receiving shift summary. MOCKED: a local SQLite file, no ERP.

Posting a receipt raises each purchase-order line's received-to-date, so the next receipt
against the same PO is checked against what is still open. Every step also lands in the
audit trail (ledger.events): what was found, what the clerk answered, and when it posted.
"""

from __future__ import annotations

import json
from contextlib import closing

from slipcheck import ledger
from slipcheck.receiving.reference import ReceivingReference, load_receiving, norm_receipt_no
from slipcheck.receiving.validate import ReceivingReport, receipt_fingerprint
from slipcheck.validate import BLOCK


class AlreadyReceived(Exception):
    def __init__(self, receipt: dict):
        super().__init__(f"Receipt {receipt['receipt_number']} was already posted as entry #{receipt['id']}.")
        self.receipt = receipt


class NotPostable(Exception):
    pass


def _receipt(row) -> dict:
    d = dict(row)
    for key in ("lines", "held", "answers"):
        d[key] = json.loads(d[key])
    return d


def posted_receipts() -> list[dict]:
    with closing(ledger._connect()) as conn:
        rows = conn.execute("SELECT * FROM receipts ORDER BY id").fetchall()
    return [_receipt(r) for r in rows]


def current_reference() -> ReceivingReference:
    """POs with everything received so far: seed history plus receipts posted this session."""
    return load_receiving(posted=posted_receipts())


def find_posted(receipt_number: str) -> dict | None:
    key = norm_receipt_no(receipt_number)
    return next((r for r in posted_receipts() if norm_receipt_no(r["receipt_number"]) == key), None)


def record_check(name: str, report: ReceivingReport) -> None:
    now = ledger._now()
    first = json.dumps(sorted({(i.severity, i.code) for i in report.issues if i.severity != "info"}))
    open_codes = json.dumps(sorted({i.code for i in report.issues if i.severity == BLOCK}))
    with closing(ledger._connect()) as conn, conn:
        seen = conn.execute("SELECT 1 FROM receipt_checks WHERE name = ?", (name,)).fetchone()
        conn.execute(
            """INSERT INTO receipt_checks (name, first_seen, last_seen, first_codes, status, open_codes, po_number, receipt_number)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET last_seen = excluded.last_seen, status = excluded.status,
                   open_codes = excluded.open_codes, po_number = excluded.po_number, receipt_number = excluded.receipt_number""",
            (name, now, now, first, report.status, open_codes, report.po_number, report.receipt_number))
    if not seen:
        ledger.log_event("receipt_checked", name, {"status": report.status, "found": json.loads(first),
                                                   "po_number": report.po_number})


def post(name: str, report: ReceivingReport, answers: list[str]) -> dict:
    if report.status == "BLOCKED":
        raise NotPostable(f"{len(report.blocking)} problem(s) still block this receipt.")
    existing = find_posted(report.receipt_number or "") if report.receipt_number else None
    if existing:
        raise AlreadyReceived(existing)
    counted = [{"part_number": r["part_number"], "qty": r["qty"], "unit": r["unit"]} for r in report.lines if r["counts"]]
    held = [f"line {r['line']}: {r['disposition']}" for r in report.lines if r["disposition"] in ("return", "hold")]
    with closing(ledger._connect()) as conn, conn:
        cur = conn.execute(
            """INSERT INTO receipts (name, receipt_number, po_number, fingerprint, posted_at, received_on, received_by,
                                     vendor, lines, held, answers) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, report.receipt_number or "", report.po_number, receipt_fingerprint(report), ledger._now(),
             report.received_on, report.received_by, report.vendor, json.dumps(counted), json.dumps(held), json.dumps(answers)))
        row = conn.execute("SELECT * FROM receipts WHERE id = ?", (cur.lastrowid,)).fetchone()
    ledger.log_event("receipt_posted", name, {"entry": row["id"], "po_number": report.po_number, "lines": len(counted),
                                              "held": held, "answers": answers})
    return _receipt(row)


def summary(ref: ReceivingReference) -> dict:
    with closing(ledger._connect()) as conn:
        checks = [dict(r) for r in conn.execute("SELECT * FROM receipt_checks ORDER BY last_seen DESC")]
    receipts = posted_receipts()
    posted_names = {r["name"] for r in receipts}
    caught: dict[str, int] = {}
    for c in checks:
        for _severity, code in json.loads(c["first_codes"]):
            caught[code] = caught.get(code, 0) + 1
    pending = [{"name": c["name"], "status": c["status"], "open_codes": json.loads(c["open_codes"]),
                "po_number": c["po_number"], "receipt_number": c["receipt_number"]}
               for c in checks if c["name"] not in posted_names]
    return {
        "counts": {"checked": len(checks), "posted": len(receipts),
                   "on_hold": sum(p["status"] == "BLOCKED" for p in pending),
                   "problems_caught": sum(caught.values())},
        "receipts": list(reversed(receipts)),
        "pending": pending,
        "caught": sorted(({"code": k, "count": v} for k, v in caught.items()), key=lambda c: (-c["count"], c["code"])),
        "pos": [po_view(po) for po in sorted(ref.pos.values(), key=lambda p: p.po_number)],
    }


def po_view(po) -> dict:
    return {"po_number": po.po_number, "vendor": po.vendor, "status": "CLOSED" if po.is_closed else "OPEN",
            "ordered_on": po.ordered_on.isoformat(),
            "lines": [{"line": ln.line, "part_number": ln.part_number, "description": ln.description, "unit": ln.unit,
                       "ordered": ln.qty_ordered, "received": po.received.get(ln.part_number, 0),
                       "open": po.open_qty(ln.part_number)} for ln in po.lines]}
