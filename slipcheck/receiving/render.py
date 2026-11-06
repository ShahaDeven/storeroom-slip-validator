"""Plain-text rendering of a ReceivingReport for the terminal."""

from __future__ import annotations

from slipcheck.receiving.validate import ReceivingReport
from slipcheck.validate import BLOCK, INFO, WARN

TAG = {BLOCK: "[BLOCK]", WARN: "[WARN] ", INFO: "[INFO] "}


def render_receipt(report: ReceivingReport, source: str = "") -> str:
    out = [f"Receipt: {source}" if source else "Receipt", f"Status: {report.status}",
           f"{report.receipt_number or '?'} | {report.po_number or '?'} | {report.vendor or '?'} | "
           f"{report.received_on or '?'} | received by {report.received_by or '?'}"]
    if report.po_lines:
        out += ["", "The purchase order after this receipt:",
                f"  {'line':<5}{'part':<9}{'ordered':>8}{'before':>8}{'this':>6}{'open':>6}  state"]
        for p in report.po_lines:
            out.append(f"  {p['line']:<5}{p['part_number']:<9}{p['ordered']:>8}{p['received_before']:>8}"
                       f"{p['this_receipt']:>6}{p['open_after']:>6}  {p['state']}  ({p['unit']})")
    if report.issues:
        out += ["", "Issues:"]
        for i in sorted(report.issues, key=lambda i: (BLOCK, WARN, INFO).index(i.severity)):
            out.append(f"  {TAG[i.severity]} {i.code:<20} {i.where}: {i.message}")
            if i.fixes:
                out.append(f"           options: {' | '.join(f['label'] for f in i.fixes)}")
    elif report.status == "READY":
        out += ["", "Nothing to resolve."]
    return "\n".join(out)
