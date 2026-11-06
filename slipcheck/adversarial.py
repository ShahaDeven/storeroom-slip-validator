"""Adversarial suite: deliberately difficult cases, each with the outcome it SHOULD have.

Every case runs through the real code: the slip or receipt validator, then the real posting
functions, in a throwaway ledger (one SQLite file per case), so nothing touches the shift log.
Earlier steps set the scene (post a partial delivery, post a slip); the last step is the attempt.

A case ends in one of these outcomes:
  posted                 went into the (mock) system with nothing to answer
  posted_with_warnings   went in, with warnings shown to the clerk
  blocked                a rule stopped it until a person answers
  needs_review           only a low-confidence read stopped it (a person checks the paper)
  refused                the posting step itself refused it (already posted)

Verdicts: "as_expected"; "known_gap" (the case documents a failure we know about and have not
fixed; the actual outcome is the honest one); "regression" (a case that should hold no longer
does: the CLI exits 1 and the test suite fails).

  python -m slipcheck adversarial
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from slipcheck import ledger
from slipcheck.reference import load_reference
from slipcheck.validate import BLOCK, INFO, validate

TODAY = date(2026, 11, 6)  # fixed, so dates on the cases never drift into "future" or "stale"
STOPPED = {"blocked", "needs_review", "refused"}


def f(value: Any, confidence: float = 1.0) -> dict:
    """A field as an extraction would deliver it."""
    return {"value": value, "raw": None if value is None else str(value), "confidence": confidence}


@dataclass
class Step:
    kind: str  # "receipt" | "slip"
    name: str  # what the clerk saw it as: a file name or a slip name
    data: dict
    say: str  # one line for the reader
    post: bool = True  # earlier steps post; the last step always attempts to post


@dataclass
class Case:
    id: str
    area: str  # "receiving" | "slips"
    title: str
    attempt: str  # what is being tried, in plain words
    steps: list[Step]
    expect: str  # outcome
    expect_codes: list[str] = field(default_factory=list)
    why: str = ""  # why the expected outcome is the right one
    known_gap: str | None = None  # set when the case documents an unfixed failure
    history: str | None = None  # e.g. "failed when this suite was first run; rule added"


# ---------------------------------------------------------------- the inputs


def receipt(number: str, po: str, vendor: str, items: list[dict], *, when: str = "10/26/26",
            by: str = "K. Haas", **extra: Any) -> dict:
    return {"receipt_number": f(number), "po_number": f(po), "date": f(when), "vendor": f(vendor),
            "received_by": f(by), "items": items, **extra}


def line(part: str | None, name: str, qty: Any, unit: str | None, qty_conf: float = 1.0) -> dict:
    return {"part_number": f(part), "part_name": f(name), "qty": f(qty, qty_conf), "unit": f(unit)}


def slip(items: list[dict], *, wo: str = "WO-26-0412", by: str = "J. Rivera", where: str = "Harlow Hall",
         when: str = "10/22/26", wo_conf: float = 1.0) -> dict:
    return {"wo_number": f(wo, wo_conf), "date": f(when), "taken_by": f(by), "location": f(where),
            "signature": {"value": True, "confidence": 1.0}, "items": items}


OUTLETS_PARTIAL = [line("EL-2010", "20a outlet", 30, "ea"), line("EL-2011", "15a outlet", 18, "ea")]
ELBOWS_30 = [line("PL-1001", "pvc elbow 3/4", 30, "ea")]

CASES: list[Case] = [
    # ------------------------------------------------------------ receiving
    Case("A1", "receiving", "The same receipt, scanned again under a new file name",
         "R-20102 is posted from receiving_scan.pdf. Next day the same paper is scanned again as scan_0042.pdf.",
         [Step("receipt", "receiving_scan.pdf", receipt("R-20102", "PO-26-1102", "Ridgeway Electric", OUTLETS_PARTIAL),
               "Post R-20102: 30 + 18 outlets against PO-26-1102"),
          Step("receipt", "scan_0042.pdf", receipt("R-20102", "PO-26-1102", "Ridgeway Electric", OUTLETS_PARTIAL),
               "Submit the identical receipt as scan_0042.pdf")],
         "refused", [],
         "Duplicates are found by receipt number and content, never by file name. Posting it twice would count 48 "
         "outlets that never arrived."),
    Case("A2", "receiving", "The same delivery, keyed in with a new receipt number",
         "10 of 30 15A outlets are posted as R-20102. The same delivery is keyed in again as R-20199: same PO, "
         "same date, same quantity. 20 are still open, so the quantity alone looks fine.",
         [Step("receipt", "R-20102.pdf", receipt("R-20102", "PO-26-1102", "Ridgeway Electric",
                                                [line("EL-2011", "15a outlet", 10, "ea")]),
               "Post R-20102: 10 of 30 15A outlets against PO-26-1102"),
          Step("receipt", "R-20199.pdf", receipt("R-20199", "PO-26-1102", "Ridgeway Electric",
                                                [line("EL-2011", "15a outlet", 10, "ea")]),
               "Submit R-20199: the same 10 outlets, same PO and date, new receipt number")],
         "blocked", ["POSSIBLE_DUPLICATE"],
         "A new number on identical content is the usual way a double count gets in. It can be a real repeat "
         "delivery, so a person confirms instead of the system deciding.",
         history="This case failed when the suite was first run: the content fingerprint was computed but never "
                 "checked. The POSSIBLE_DUPLICATE rule was added because of it."),
    Case("A3", "receiving", "Right PO number, wrong supplier",
         "A Calder Industrial delivery is booked against PO-26-1101, which is with Northline Supply.",
         [Step("receipt", "R-20301.pdf", receipt("R-20301", "PO-26-1101", "Calder Industrial",
                                                [line("PL-1001", "pvc elbow 3/4", 50, "ea")]),
               "Submit a Calder Industrial receipt quoting Northline's PO-26-1101")],
         "blocked", ["VENDOR_MISMATCH"],
         "Either the PO number is wrong or the goods came from someone we didn't order from. Both need a person "
         "before the PO is marked received.",
         history="This case failed when the suite was first run: a vendor mismatch was only a warning, and the "
                 "receipt posted. It is now a block, with the PO's vendor and that vendor's open POs as answers."),
    Case("A4", "receiving", "One part, written in two units on the same receipt",
         "Yellow wire nuts are ordered in boxes of 100. The receipt lists them twice: 5 BX, and 500 pcs.",
         [Step("receipt", "R-20401.pdf", receipt("R-20401", "PO-26-1105", "Ridgeway Electric",
                                                [line("EL-2001", "wire nut yellow", 5, "bx"),
                                                 line("EL-2001", "wire nuts yellow", 500, "pcs")]),
               "Submit 5 BX + 500 pcs of EL-2001 against 10 BX ordered")],
         "posted_with_warnings", ["DUPLICATE_LINE", "UNIT_CONVERTED"],
         "500 pieces is exactly 5 boxes, so the total is the 10 ordered. The clerk sees that the lines were "
         "combined and converted; nothing is silently merged."),
    Case("A5", "receiving", "A partial delivery, then the rest, then one too many",
         "PO-26-1101 orders 50 elbows. 30 arrive, then 20, then a third receipt for 5 more.",
         [Step("receipt", "R-20501.pdf", receipt("R-20501", "PO-26-1101", "Northline Supply", ELBOWS_30
                                                + [line("PL-1010", "ball valve 3/4", 12, "ea"),
                                                   line("PL-1040", "ptfe tape", 24, "roll")], when="10/20/26"),
               "Post 30 of 50 elbows (and the valves and tape in full): a partial, the PO stays open"),
          Step("receipt", "R-20502.pdf", receipt("R-20502", "PO-26-1101", "Northline Supply",
                                                [line("PL-1001", "pvc elbow 3/4", 20, "ea")], when="10/24/26"),
               "Post the remaining 20: the PO is now fully received"),
          Step("receipt", "R-20503.pdf", receipt("R-20503", "PO-26-1101", "Northline Supply",
                                                [line("PL-1001", "pvc elbow 3/4", 5, "ea")], when="10/27/26"),
               "Submit 5 more elbows against the same PO")],
         "blocked", ["PO_CLOSED"],
         "Received-to-date carries across receipts. Once all 50 are in, nothing more can be received against it."),
    Case("A6", "receiving", "The second delivery is bigger than what is left",
         "30 of 40 elbows are received. The next receipt says 30 more.",
         [Step("receipt", "R-20601.pdf", receipt("R-20601", "PO-26-1111", "Northline Supply", ELBOWS_30
                                                + [line("PL-1002", "pvc elbow 1/2", 40, "ea")], when="10/20/26"),
               "Post 30 of 40 3/4 elbows and all 40 1/2 elbows against PO-26-1111"),
          Step("receipt", "R-20602.pdf", receipt("R-20602", "PO-26-1111", "Northline Supply", ELBOWS_30,
                                                when="10/24/26"),
               "Submit 30 more 3/4 elbows: only 10 are still open")],
         "blocked", ["OVER_SHIPMENT"],
         "Over-shipment is judged against what is still open, not the original order."),
    Case("A7", "receiving", "A wrong quantity read with high confidence",
         "A photographed receipt says 2 ball valves. The vision model reads 12, at confidence 0.97. 12 are on order.",
         [Step("receipt", "R-20701.png", receipt("R-20701", "PO-26-1101", "Northline Supply",
                                                [line("PL-1010", "ball valve 3/4", 12, "ea", qty_conf=0.97)]),
               "Submit the reading: 12 valves at 0.97 (the paper says 2)")],
         "blocked", [],
         "The right outcome is that 10 valves that never arrived are not received.",
         known_gap="Not caught. 12 is a believable quantity: it is exactly what is open on the PO, so no rule "
                   "contradicts it, and the confidence is above the 0.75 review threshold. Six held-out slip fields "
                   "were read wrong at 0.90 or above (EVAL.md). Closing this needs a second source for the count "
                   "(a packing list, an advance ship notice, or a count at put-away), not a better threshold."),
    Case("A8", "receiving", "An unreadable PO number on a photographed receipt",
         "The PO number on a receipt photo is smudged; the model reads 'PO-26-11?1' at confidence 0.41.",
         [Step("receipt", "R-20801.png", receipt("R-20801", "PO-26-11?1", "Northline Supply", ELBOWS_30)
               | {"po_number": f("PO-26-11?1", 0.41)},
               "Submit the reading with a 0.41-confidence PO number")],
         "blocked", ["HUMAN_REVIEW"],
         "A low-confidence read is never guessed: a person checks the paper before the receipt is matched."),
    # ------------------------------------------------------------ slips
    Case("S1", "slips", "A posted slip keyed in again under another name",
         "J. Rivera's pull is posted from the counter. Later the carbon copy is entered again as 'rivera copy'.",
         [Step("slip", "rivera pull", slip([line("PL-1001", "3/4 pvc elbow", 6, "ea")]),
               "Post J. Rivera: 6 elbows on WO-26-0412"),
          Step("slip", "rivera copy", slip([line("PL-1001", "3/4 pvc elbow", 6, "ea")]),
               "Submit the same slip under a different name")],
         "refused", [],
         "Same work order, person, date and parts are the same pull, whatever it is called. Stock would drop twice."),
    Case("S2", "slips", "A wrong quantity read with high confidence",
         "The slip says 6 elbows. The model reads 9, at confidence 0.95.",
         [Step("slip", "rivera 9", slip([line("PL-1001", "3/4 pvc elbow", 9, "ea", qty_conf=0.95)]),
               "Submit the reading: 9 elbows at 0.95 (the paper says 6)")],
         "blocked", [],
         "The right outcome is that 3 elbows are not taken off the shelf that never left it.",
         known_gap="Not caught. 9 is under the 20-per-pull limit and under on-hand, so no rule fires, and 0.95 is "
                   "above the review threshold. This is the same failure as A7. The held-out evaluation measures how "
                   "often it happens (EVAL.md)."),
    Case("S3", "slips", "One wrong digit in the work order makes a real, open work order",
         "WO-26-0412 (Plumbing A, Harlow Hall) is read as WO-26-0462, which exists: Custodial, Pierce Library.",
         [Step("slip", "rivera 0462", slip([line("PL-1001", "3/4 pvc elbow", 6, "ea")], wo="WO-26-0462"),
               "Submit the reading: WO-26-0462, read with full confidence")],
         "blocked", [],
         "The person and building on the slip don't belong to that work order. The pull must not post to it.",
         known_gap="Shown, not stopped. The cross-checks notice (NOT_ON_CREW, LOCATION_MISMATCH), but both are "
                   "warnings, and a warning does not block posting: a clerk who clicks past them books the pull to "
                   "Custodial. EVAL.md counts a warning like this as 'caught'. Making these a block is the obvious "
                   "fix. It is not made yet because the slip rules are frozen for the evaluation; changing them "
                   "means a new round of development data."),
    Case("S4", "slips", "A part number one digit off, pointing at a real neighbouring part",
         "PL-1001 (3/4 elbow) is read as PL-1002 (1/2 elbow). The description still says 3/4.",
         [Step("slip", "rivera 1002", slip([line("PL-1002", "3/4 pvc elbow", 6, "ea")]),
               "Submit PL-1002 with the description '3/4 pvc elbow'")],
         "blocked", ["NAME_NUMBER_MISMATCH"],
         "The number and the description disagree. A person picks which one is right.",
         known_gap="Not caught. '3/4 pvc elbow' and 'PVC Elbow 90 deg 1/2 in' share most of their words, so the "
                   "description check scores them as a match and never compares the sizes. A size-aware "
                   "comparison (3/4 against 1/2) is the fix, held back for the same reason as S3."),
    Case("S5", "slips", "A pair-tracked part with no unit",
         "Gloves are tracked in pairs. The slip says '4 gloves' with no unit.",
         [Step("slip", "rivera gloves", slip([line("GN-4001", "leather gloves l", 4, None)]),
               "Submit 4 gloves, no unit")],
         "blocked", ["UNIT_AMBIGUOUS"],
         "4 pairs or 2 pairs (4 gloves)? This exact error is what used to surface days later at the count."),
]


# ---------------------------------------------------------------- running


@dataclass
class Attempt:
    outcome: str
    status: str | None
    codes: list[str]  # warning and blocking codes, plus info codes worth showing
    message: str | None  # the first blocking (or refusing) message, as the clerk would see it


def _codes(issues) -> list[str]:
    return sorted({i.code for i in issues})


def _first_message(issues) -> str | None:
    blocking = [i for i in issues if i.severity == BLOCK]
    shown = blocking or [i for i in issues if i.severity != INFO] or list(issues)
    return shown[0].message if shown else None


def _outcome(issues, status: str) -> str:
    blocking = [i for i in issues if i.severity == BLOCK]
    if blocking:
        return "needs_review" if all(i.code == "HUMAN_REVIEW" for i in blocking) else "blocked"
    return "posted_with_warnings" if status == "READY_WITH_WARNINGS" else "posted"


def _run_receipt(step: Step) -> Attempt:
    # The same path as POST /api/receiving/post: history without this receipt, then post.
    from slipcheck.receiving import store
    from slipcheck.receiving.api import _reference_for
    from slipcheck.receiving.validate import validate_receipt

    ref, already = _reference_for(step.data)
    report = validate_receipt(step.data, ref, today=TODAY)
    store.record_check(step.name, report)
    if already:
        return Attempt("refused", report.status, _codes(report.issues),
                       f"Receipt {already['receipt_number']} was already posted as entry #{already['id']}.")
    outcome = _outcome(report.issues, report.status)
    if outcome not in STOPPED:
        try:
            store.post(step.name, report, [])
        except (store.NotPostable, store.AlreadyReceived) as e:
            return Attempt("refused", report.status, _codes(report.issues), str(e))
    return Attempt(outcome, report.status, _codes(report.issues), _first_message(report.issues))


def _run_slip(step: Step, ref) -> Attempt:
    report = validate(step.data, ledger.with_posted_stock(ref), today=TODAY)
    ledger.record_check(step.name, report)
    outcome = _outcome(report.issues, report.status)
    if outcome not in STOPPED:
        try:
            ledger.post(step.name, report, [])
        except ledger.AlreadyPosted as e:
            return Attempt("refused", report.status, _codes(report.issues), str(e))
        except ledger.NotPostable as e:
            return Attempt("blocked", report.status, _codes(report.issues), str(e))
    return Attempt(outcome, report.status, _codes(report.issues), _first_message(report.issues))


def run_case(case: Case, ref=None) -> dict:
    ref = ref or load_reference()
    with tempfile.TemporaryDirectory() as tmp, ledger.scratch_db(Path(tmp) / "case.db"):
        setup: list[dict] = []
        for step in case.steps[:-1]:
            a = _run_receipt(step) if step.kind == "receipt" else _run_slip(step, ref)
            setup.append({"say": step.say, "outcome": a.outcome})
        last = case.steps[-1]
        actual = _run_receipt(last) if last.kind == "receipt" else _run_slip(last, ref)

    stopped_ok = (actual.outcome in STOPPED) == (case.expect in STOPPED)
    matches = (actual.outcome == case.expect or (case.expect == "blocked" and actual.outcome in STOPPED)) \
        and set(case.expect_codes) <= set(actual.codes)
    verdict = "as_expected" if matches else "known_gap" if case.known_gap else "regression"
    d = asdict(case)
    d.pop("steps")
    return d | {
        "setup": setup, "attempt_step": last.say,
        "actual": asdict(actual), "verdict": verdict,
        # the question that matters most: did something that shouldn't go in, go in?
        "got_in": actual.outcome not in STOPPED and case.expect in STOPPED,
        "stopped_ok": stopped_ok,
    }


def run_suite() -> dict:
    started = time.perf_counter()
    ref = load_reference()
    results = [run_case(c, ref) for c in CASES]
    counts = {v: sum(r["verdict"] == v for r in results) for v in ("as_expected", "known_gap", "regression")}
    return {"ran_at": datetime.now().isoformat(timespec="seconds"), "today": TODAY.isoformat(),
            "ms": round((time.perf_counter() - started) * 1000), "total": len(results), "counts": counts,
            "got_in": sum(r["got_in"] for r in results), "cases": results}


def format_suite(s: dict) -> str:
    label = {"as_expected": "as expected", "known_gap": "KNOWN GAP", "regression": "REGRESSION"}
    out = [f"Adversarial suite: {s['total']} cases, real validator and posting code, throwaway ledger ({s['ms']} ms)\n"]
    for r in s["cases"]:
        exp = r["expect"] + (f" [{', '.join(r['expect_codes'])}]" if r["expect_codes"] else "")
        got = r["actual"]["outcome"] + (f" [{', '.join(r['actual']['codes'])}]" if r["actual"]["codes"] else "")
        out.append(f"{r['id']:<3} {label[r['verdict']]:<12} {r['title']}")
        out.append(f"      expected {exp}")
        out.append(f"      actual   {got}")
    c = s["counts"]
    out.append(f"\n{c['as_expected']} as expected, {c['known_gap']} known gaps, {c['regression']} regressions. "
               f"{s['got_in']} attempt(s) got into the system that shouldn't have.")
    return "\n".join(out)
