"""Plain-text rendering of a Report for the terminal."""

from __future__ import annotations

from slipcheck.validate import BLOCK, CREW, INFO, WARN, Report

TAG = {BLOCK: "[BLOCK]", WARN: "[WARN] ", INFO: "[INFO] "}
# Suggestions for these are ranked by evidence (same crew, same location); for the
# rest they are a tie the crew has to break, so they are shown as options.
RANKED = {"CLOSED_WO", "UNKNOWN_WO", "MISSING_WO"}


def render(report: Report, source: str = "") -> str:
    out = []
    if source:
        out.append(f"Slip: {source}")
    out.append(f"Status: {report.status}")
    out.append(f"W/O {report.wo_number or '?'} | crew {report.crew or '?'} | "
               f"taken by {report.taken_by or '?'} | {report.location or '?'} | {report.slip_date or '?'}")

    out.append("\nEntry to post:")
    for ln in report.lines:
        part = f"{ln.part_number} {ln.name} [aisle {ln.aisle}]" if ln.part_number else "UNRESOLVED PART"
        qty = f"{ln.qty:g} {ln.unit or ''}".strip() if ln.qty is not None else "? (unresolved)"
        out.append(f"  {ln.line}. {qty:<14} {part}")
    if not report.lines:
        out.append("  (no lines)")

    if report.issues:
        out.append("\nIssues:")
        for i in sorted(report.issues, key=lambda i: (BLOCK, WARN, INFO).index(i.severity)):
            out.append(f"  {TAG[i.severity]} {i.code:<20} {i.where}: {i.message}")
            for s in i.suggestions:
                out.append(f"           -> {s}")

    crew_qs = [i for i in report.issues if i.ask == CREW and i.severity != INFO]
    if crew_qs:
        who = report.taken_by or "the crew"
        out.append(f"\nCall {who}{f' ({report.crew})' if report.crew else ''} now and ask:")
        for n, i in enumerate(crew_qs, 1):
            out.append(f"  {n}. [{i.where}] {i.message}")
            if i.suggestions and i.code in RANKED:
                out.append(f"     Suggested: {i.suggestions[0]}")
            elif i.suggestions:
                out.append(f"     Options: {' | '.join(s.split(' [')[0] for s in i.suggestions)}")
    elif report.status != "BLOCKED":
        out.append("\nNothing to ask the crew. Ready to post.")
    return "\n".join(out)
