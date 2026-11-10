"""Evaluate photo reading + validation on labeled handwritten slips. EXPLORATORY, small sample.

For every labeled slip the real validator runs twice: on the TRUE transcription (the oracle,
from data/eval/labels.csv) and on the model's reading. A model mistake matters only if the
system fails to notice it, so the question per wrong field is: did the reading's report carry
a flag that the correct reading's report would not have, or a low-confidence review request
on that field? If not, it is a *silent* misread. Silent misreads of critical fields are the
dangerous ones (the slip could be posted with a wrong entry).

Definitions (also written into EVAL.md):
  field correct      reading equals the paper after trimming, case and numeric normalisation.
                     W/O numbers, dates and part numbers compare by meaning (a missing "WO-"
                     prefix is not a misread: the validator treats them as the same).
                     Fields blank on the paper and read as blank are not counted.
  critical field     W/O number, signature, part number, quantity, unit, and the part name
                     when the paper has no part number.
  flagged            an issue of severity block/warn pinned to the field that is NEW relative
                     to the oracle report, or a HUMAN_REVIEW (confidence below the threshold).
  absorbed           the field carries a BLOCK that is also in the oracle report and makes a
                     person choose or type that field's value (closed/unknown W/O, ambiguous part,
                     unit question). The misread cannot reach the entry unnoticed. Assumes the
                     clerk picks the right option; every absorbed case is listed in the misread log.
  silent misread     a wrong field that is neither flagged nor absorbed.
  stopped            the wrong field cannot post without a person settling that field: a review
                     request, a new BLOCK on it, or an absorbing block. A new WARNING is not a
                     stop: it is shown, and the slip still posts.
  reaches posting    a wrong field that is stored in the posted entry (every critical field, plus
                     date, taken-by and location; not a description beside a part number, which
                     is replaced by the catalog name) and is not stopped. Assumes the clerk settles every stop
                     correctly from the paper and posts past warnings (the pessimistic reading).
  not caught (slip)  a slip with at least one silent misread of a critical field.
  unnecessary review a correctly read field that was sent to review.
The model's confidence is reported against observed correctness; it is not treated as a
calibrated probability.
"""

from __future__ import annotations

import csv
import json
import math
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from slipcheck.extract import ExtractionError, add_provenance, extract_live
from slipcheck.impact import TODAY
from slipcheck.reference import DATA_DIR, Reference, load_reference
from slipcheck.validate import InvalidSlip, as_field, normalize_wo, parse_date, validate

ROOT = DATA_DIR.parent
EVAL_DIR = DATA_DIR / "eval"
LABELS = EVAL_DIR / "labels.csv"
READINGS = EVAL_DIR / "readings"
LOCK = EVAL_DIR / ".heldout_run.json"
CORRECTIONS = EVAL_DIR / "corrections.json"  # data-handling errors found after a run, applied only with --corrected

HEADER = ("wo_number", "date", "taken_by", "location", "signature")
ITEM = ("part_number", "part_name", "qty", "unit")
BINS = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.0001)]

# A flag on one field is also evidence about a neighbouring field it was derived from.
EXTRA_PINS = {
    "NAME_NUMBER_MISMATCH": ("part_name",),
    "UNIT_AMBIGUOUS": ("qty",), "UNIT_REMAINDER": ("qty",), "UNIT_ASSUMED": ("qty",),
    "UNIT_MISMATCH": ("qty",), "UNIT_CONVERTED": ("qty",),
    "LOCATION_MISMATCH": ("wo_number",), "NOT_ON_CREW": ("wo_number",),
    "BEFORE_WO_OPENED": ("wo_number",),
}


# ---------------------------------------------------------------- small statistics


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion; (0, 1) when there is nothing to measure."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom)


def prop(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci95": [round(lo, 3), round(hi, 3)]}


# ---------------------------------------------------------------- truth and readings


def norm(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = " ".join(str(value).split()).casefold().rstrip(".")
    try:
        number = float(text)
        return str(int(number)) if number == int(number) else text
    except ValueError:
        return text


def _signed(value) -> str:
    return "yes" if value is True or str(value).strip().casefold() in ("true", "yes", "signed") else "no"


def load_labels(split: str) -> list[dict]:
    with open(LABELS, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["split"] == split]


def truth_slip(row: dict) -> dict:
    items = []
    for n in (1, 2, 3):
        vals = {k: row.get(f"line{n}_{k}", "") for k in ("part_number", "description", "qty", "unit")}
        if any(vals.values()):
            items.append({"part_number": vals["part_number"], "part_name": vals["description"],
                          "qty": vals["qty"], "unit": vals["unit"]})
    return {"wo_number": row["wo_number"], "date": row["date"], "taken_by": row["taken_by"],
            "location": row["location"], "signature": row["signed"].strip().casefold() == "yes", "items": items}


def reading_path(row: dict) -> Path:
    if Path(row["photo"]).parts[:2] == ("data", "photos"):  # the two earlier photos live with the app's samples
        return DATA_DIR / "extractions" / f"{Path(row['photo']).stem}.json"
    return READINGS / f"{row['slip_id']}.json"


@dataclass
class Budget:
    calls_left: int
    calls: int = 0


def load_reading(row: dict, live: bool, budget: Budget) -> tuple[dict | None, str]:
    path = reading_path(row)
    if path.exists():
        return add_provenance(json.loads(path.read_text(encoding="utf-8")), Path(row["photo"]).name), "cached"
    photo = ROOT / row["photo"]
    if not live:
        return None, "no reading yet (run with --live)"
    if not photo.exists():
        return None, f"photo missing: {row['photo']}"
    if budget.calls_left <= 0:
        return None, "call cap reached"
    try:
        data = extract_live(photo)
    except ExtractionError as e:
        return None, f"extraction failed: {e}"
    budget.calls_left -= 1
    budget.calls += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data, "live"


def load_corrections(path: Path | None = None) -> dict:
    path = path or CORRECTIONS
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def photo_for(slip_id: str, corrections: dict) -> str:
    """Which slip's photo (and reading) actually shows this slip, after any recorded swaps."""
    for swap in corrections.get("photo_swaps", []):
        a, b = swap["slips"]
        if slip_id in (a, b):
            return b if slip_id == a else a
    return slip_id


# ---------------------------------------------------------------- comparing one slip


def same_value(name: str, paper: str, read: str) -> bool:
    """Equality by meaning where the validator itself would treat two spellings as one value."""
    if paper == read:
        return True
    if not paper or not read:
        return False
    if name == "wo_number":
        return normalize_wo(paper, TODAY.year) == normalize_wo(read, TODAY.year)
    if name == "date":
        a, b = parse_date(paper), parse_date(read)
        return a is not None and a == b
    if name == "part_number":
        return paper.replace(" ", "") == read.replace(" ", "")
    return False


@dataclass
class FieldResult:
    slip_id: str
    line: int | None
    name: str
    truth: str
    read: str
    confidence: float | None
    correct: bool
    critical: bool
    review: bool = False
    new_flag: bool = False
    new_block: bool = False  # the new flag is a block, not just a warning
    absorbed: bool = False
    source: dict | None = None

    @property
    def flagged(self) -> bool:
        return self.review or self.new_flag

    @property
    def covered(self) -> bool:
        return self.flagged or self.absorbed

    @property
    def silent(self) -> bool:
        return not self.correct and not self.covered

    @property
    def stopped(self) -> bool:
        """Posting needs a person to settle this field. A warning alone does not stop posting."""
        return self.review or self.new_block or self.absorbed

    @property
    def stored(self) -> bool:
        """Written into the posted entry. A description next to a part number is not: the entry
        carries the catalog name for that number."""
        return self.critical or self.name in ("date", "taken_by", "location")

    @property
    def reaches_posting(self) -> bool:
        return not self.correct and not self.stopped and self.stored


@dataclass
class SlipResult:
    slip_id: str
    split: str
    style: str
    scenario: str
    condition: str
    oracle_status: str
    actual_status: str
    outcome: str
    review_requested: bool
    fields: list[FieldResult] = field(default_factory=list)
    person_needed: bool = False  # any block in the reading's report that the truth's report doesn't have


def _pins(issue) -> set[tuple[int | None, str]]:
    return {(issue.line, k) for k in (issue.key, *EXTRA_PINS.get(issue.code, ())) if k}


def _pairs(truth: dict, reading: dict):
    """Yield (line, name, truth_text, read_text, read_field, critical) for each comparable field."""
    for name in HEADER:
        read = as_field(reading.get(name))
        if name == "signature":
            yield None, name, norm(truth["signature"]), _signed(read.value), read, True
        else:
            yield None, name, norm(truth.get(name)), norm(read.value), read, name == "wo_number"
    t_items = truth["items"]
    r_items = [i for i in (reading.get("items") or []) if isinstance(i, dict)]
    for n in range(1, max(len(t_items), len(r_items)) + 1):
        t = t_items[n - 1] if n <= len(t_items) else {}
        r = r_items[n - 1] if n <= len(r_items) else {}
        number_on_paper = bool(norm(t.get("part_number")))
        for name in ITEM:
            read = as_field(r.get(name)) if name in r else None
            critical = name in ("part_number", "qty", "unit") or (name == "part_name" and not number_on_paper)
            yield n, name, norm(t.get(name)), norm(read.value if read else None), read, critical


def evaluate_slip(row: dict, reading: dict, ref: Reference, ruleset: str = "v1") -> SlipResult:
    truth = truth_slip(row)
    oracle = validate(truth, ref, TODAY, ruleset=ruleset)
    try:
        actual = validate(reading, ref, TODAY, ruleset=ruleset)
    except InvalidSlip:
        actual = None  # the whole slip is rejected, which a person sees; every wrong field counts as flagged
    expected = {(i.code, i.line, i.key) for i in oracle.issues}

    fields = []
    for line, name, truth_text, read_text, read, critical in _pairs(truth, reading):
        if truth_text == "" and read_text == "":
            continue  # blank on the paper and read as blank: nothing to score
        correct = same_value(name, truth_text, read_text)
        result = FieldResult(row["slip_id"], line, name, truth_text, read_text,
                             read.confidence if read else None, correct, critical,
                             source=read.source if read else None)
        if actual is None:
            result.new_flag = result.new_block = True
        else:
            for issue in actual.issues:
                if issue.severity == "info" or (line, name) not in _pins(issue):
                    continue
                if issue.code == "HUMAN_REVIEW":
                    result.review = True
                elif (issue.code, issue.line, issue.key) not in expected:
                    result.new_flag = True
                    result.new_block = result.new_block or issue.severity == "block"
                elif issue.severity == "block" and (issue.line, issue.key) == (line, name):
                    result.absorbed = True  # a direct block on this very field: a person must settle it
        fields.append(result)

    wrong = [f for f in fields if not f.correct]
    if not wrong:
        outcome = "read_correctly"
    elif any(f.critical and f.silent for f in wrong):
        outcome = "misread_not_caught"
    elif any(f.covered for f in wrong):
        outcome = "misread_caught"
    else:
        outcome = "misread_noncritical_unflagged"
    new_blocks = actual is None or any(i.severity == "block" and (i.code, i.line, i.key) not in expected
                                       for i in actual.issues)
    return SlipResult(row["slip_id"], row["split"], row["style"], row["scenario"], row["condition"],
                      oracle.status, actual.status if actual else "REJECTED", outcome,
                      any(f.review for f in fields) or (actual is not None and any(i.code == "HUMAN_REVIEW" for i in actual.issues)),
                      fields, new_blocks)


# ---------------------------------------------------------------- summary


def _bin_label(lo: float, hi: float) -> str:
    return f"{lo:.1f}-{min(hi, 1.0):.1f}"


def summarize(results: list[SlipResult], slips_total: int | None = None) -> dict:
    fields = [f for r in results for f in r.fields]
    correct = [f for f in fields if f.correct]
    wrong = [f for f in fields if not f.correct]
    critical = [f for f in fields if f.critical]
    n = len(results)
    out = {n_: sum(r.outcome == n_ for r in results) for n_ in
           ("read_correctly", "misread_caught", "misread_not_caught", "misread_noncritical_unflagged")}

    bins = []
    for lo, hi in BINS:
        in_bin = [f for f in fields if f.confidence is not None and lo <= f.confidence < hi]
        k = sum(f.correct for f in in_bin)
        bins.append({"confidence": _bin_label(lo, hi), "fields": len(in_bin), "correct": k,
                     "accuracy": (k / len(in_bin)) if in_bin else None,
                     "interpretable": len(in_bin) >= 10})

    by_style = {}
    for r in results:
        s = by_style.setdefault(r.style, {"slips": 0, "fields": 0, "correct": 0, "not_caught": 0})
        s["slips"] += 1
        s["fields"] += len(r.fields)
        s["correct"] += sum(f.correct for f in r.fields)
        s["not_caught"] += r.outcome == "misread_not_caught"

    return {
        "slips": n, "slips_labeled": slips_total if slips_total is not None else n,
        "fields_correct": prop(len(correct), len(fields)),
        "critical_fields_correct": prop(sum(f.correct for f in critical), len(critical)),
        "outcomes": {k: prop(v, n) for k, v in out.items()},
        "wrong_fields": {
            "total": len(wrong),
            "caught_by_review": sum(f.review for f in wrong),
            "caught_by_new_flag": sum(f.new_flag and not f.review for f in wrong),
            "absorbed_by_existing_block": sum(f.absorbed and not f.flagged for f in wrong),
            "silent_critical": sum(f.critical and f.silent for f in wrong),
            "silent_noncritical": sum((not f.critical) and f.silent for f in wrong),
        },
        "detection_recall": prop(sum(f.covered for f in wrong), len(wrong)),
        # The stricter question: would a wrong value end up in a posted entry?
        "reaches_posting": {
            "slips_with_wrong_critical_value": prop(sum(any(f.critical and f.reaches_posting for f in r.fields)
                                                        for r in results), n),
            "slips_with_any_wrong_value": prop(sum(any(f.reaches_posting for f in r.fields) for r in results), n),
            "wrong_fields": sum(f.reaches_posting for f in wrong),
            "wrong_critical_fields": sum(f.critical and f.reaches_posting for f in wrong),
            "warned_only": sum(f.new_flag and not f.stopped for f in wrong),
            "by_field": {name: sum(f.reaches_posting and f.name == name for f in wrong)
                         for name in sorted({f.name for f in wrong if f.reaches_posting})},
            "stopped": prop(sum(f.stopped for f in wrong), len(wrong)),
        },
        "unnecessary_review": prop(sum(f.review for f in correct), len(correct)),
        "review_rate": prop(sum(r.review_requested for r in results), n),
        # stricter than review_rate: also counts quantity confirmations and other new blocks
        "person_needed_rate": prop(sum(r.person_needed for r in results), n),
        "confidence_bins": bins,
        "by_style": by_style,
    }


def misread_log(results: list[SlipResult]) -> list[dict]:
    rows = []
    for r in results:
        for f in r.fields:
            if not f.correct:
                caught = ("review" if f.review else "rules (block)" if f.new_block
                          else "absorbed by an existing block" if f.absorbed
                          else "rules (warning only: still posts)" if f.new_flag else "NOT CAUGHT")
                rows.append({"slip": r.slip_id, "style": r.style, "condition": r.condition,
                             "field": f"line {f.line} {f.name}" if f.line else f.name,
                             "paper": f.truth, "read": f.read,
                             "confidence": f.confidence, "critical": f.critical, "caught_by": caught})
    return rows


# ---------------------------------------------------------------- running a split


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


class EvalRefused(RuntimeError):
    pass


def run(split: str = "dev", live: bool = False, max_calls: int = 12, confirm_frozen: bool = False,
        rerun: bool = False, ref: Reference | None = None, corrected: bool = False, rescore: bool = False,
        ruleset: str = "v1") -> dict:
    """corrected=True re-scores the CACHED readings with data/eval/corrections.json applied (no API
    calls, no lock, a separate results file). The locked results are never touched.

    rescore=True re-scores the locked run's cached readings as they are, to report a metric added
    after the run (no API calls, results_<split>_rescored.json). It also checks that every number
    the locked run reported comes out the same, which holds only while rules and labels are unchanged.

    ruleset="v2" scores the same cached readings with the rules written after the adversarial suite.
    Results go to *_v2.json files. On held-out it is allowed only as a re-score, and is labelled: the
    v2 rules were written after these slips were seen, so it is not a held-out result."""
    ref = ref or load_reference()
    commit = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    corrections = load_corrections() if corrected else {}
    if ruleset not in ("v1", "v2"):
        raise EvalRefused(f"Unknown rule set '{ruleset}'.")
    if ruleset == "v2" and split == "heldout" and not (rescore or corrected):
        raise EvalRefused("Rules v2 were written after the held-out set was seen. They can be scored on it only "
                          "as a labelled re-score (--rescore or --corrected), never as the held-out run.")
    if ruleset == "v2":
        live = False
    if rescore:
        if corrected:
            raise EvalRefused("Use --corrected or --rescore, not both.")
        if split == "heldout" and not LOCK.exists():
            raise EvalRefused("Nothing to re-score: the held-out set has not been run.")
        live = False
    elif corrected:
        if split == "heldout" and not LOCK.exists():
            raise EvalRefused("Corrections apply to a run that already happened. Run the held-out set first.")
        if not corrections:
            raise EvalRefused(f"No corrections recorded ({CORRECTIONS.name} is missing or empty).")
        live = False
    elif split == "heldout" and not rerun:
        if not confirm_frozen:
            raise EvalRefused("The held-out set is run once, after the rules and thresholds are frozen. "
                              "Pass --confirm-frozen to say that is true.")
        if LOCK.exists():
            raise EvalRefused(f"The held-out set was already run ({LOCK.name}). Running it again after "
                              "looking at the results is tuning, not evaluation. Use --rerun only to reproduce it.")
        if dirty:
            raise EvalRefused("Tracked files have uncommitted changes. Commit the frozen code first, so the "
                              "commit hash recorded with the results is the code that was evaluated.")

    rows = load_labels(split)
    by_id = {r["slip_id"]: r for r in rows}
    budget = Budget(max_calls)
    results, missing, tokens = [], [], {"input": 0, "output": 0, "readings": 0}
    for row in rows:
        source = by_id.get(photo_for(row["slip_id"], corrections), row)  # the row whose photo shows this slip
        reading, status = load_reading(source, live, budget)
        if reading is None:
            missing.append({"slip": row["slip_id"], "why": status})
            continue
        usage = (reading.get("_provenance") or {}).get("usage") or {}
        tokens["input"] += usage.get("input_tokens", 0)
        tokens["output"] += usage.get("output_tokens", 0)
        tokens["readings"] += 1
        results.append(evaluate_slip(row, reading, ref, ruleset))

    report = {
        "split": split, "ruleset": ruleset, "run_at": datetime.now().isoformat(timespec="seconds"), "commit": commit,
        "uncommitted_tracked_changes": dirty, "live_calls_this_run": budget.calls,
        "tokens_across_all_readings": tokens, "missing": missing,
        "summary": summarize(results, len(rows)), "misreads": misread_log(results),
        "slips": [asdict(r) | {"fields": [asdict(f) for f in r.fields]} for r in results],
    }
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    v = "" if ruleset == "v1" else f"_{ruleset}"
    if ruleset != "v1" and split == "heldout":
        report["ruleset_note"] = ("Rules v2 were written after these held-out slips were seen (they fix gaps the "
                                  "adversarial suite found). This is not a held-out measurement of v2; a new held-out "
                                  "set is needed for that.")
    if rescore:
        locked_path = EVAL_DIR / f"results_{split}.json"
        locked = json.loads(locked_path.read_text(encoding="utf-8"))["summary"] if locked_path.exists() else None
        report["split"] = f"{split} (re-scored from the cached readings)"
        report["locked_summary_reproduced"] = (None if locked is None or ruleset != "v1" else
                                               {k: report["summary"].get(k) == val for k, val in locked.items()})
        (EVAL_DIR / f"results_{split}_rescored{v}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    if corrected:
        report["split"] = f"{split} (corrected: see {CORRECTIONS.name})"
        report["corrections"] = corrections
        report["locked_run"] = json.loads(LOCK.read_text(encoding="utf-8")) if LOCK.exists() else None
        (EVAL_DIR / f"results_{split}_corrected{v}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    (EVAL_DIR / f"results_{split}{v}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if split == "heldout" and not rerun and ruleset == "v1":
        LOCK.write_text(json.dumps({"commit": commit, "run_at": report["run_at"], "slips": len(results)}, indent=2) + "\n",
                        encoding="utf-8")
    return report


# ---------------------------------------------------------------- threshold sweep (development only)


def sweep_thresholds(split: str = "dev", thresholds=(0.75, 0.80, 0.85, 0.90, 0.95),
                     ref: Reference | None = None) -> list[dict]:
    """Re-score cached readings at several review thresholds. No API calls.

    Choosing a threshold is tuning, so this refuses to run on the held-out set.
    """
    if split == "heldout":
        raise EvalRefused("Thresholds are chosen on development data only. Sweeping the held-out set is tuning on it.")
    import importlib

    # the package re-exports the validate() function under the same name as the module
    validator = importlib.import_module("slipcheck.validate")

    ref = ref or load_reference()
    readings = []
    for row in load_labels(split):
        path = reading_path(row)
        if path.exists():
            readings.append((row, add_provenance(json.loads(path.read_text(encoding="utf-8")), Path(row["photo"]).name)))
    original, table = validator.REVIEW_THRESHOLD, []
    try:
        for t in thresholds:
            validator.REVIEW_THRESHOLD = t
            s = summarize([evaluate_slip(row, reading, ref) for row, reading in readings])
            table.append({"threshold": t, "slips": s["slips"], "slips_needing_review": s["review_rate"],
                          "unnecessary_reviews": s["unnecessary_review"],
                          "slips_with_silent_critical_misread": s["outcomes"]["misread_not_caught"],
                          "wrong_fields_covered": s["detection_recall"]})
    finally:
        validator.REVIEW_THRESHOLD = original
    return table


def format_sweep(table: list[dict]) -> str:
    lines = ["Review-threshold sweep on the DEVELOPMENT set (no API calls; a threshold is chosen here, then tested once on held-out)",
             f"{'threshold':>9}  {'slips needing review':>22}  {'unnecessary reviews':>22}  {'silent critical (slips)':>24}  {'wrong fields covered':>22}"]
    for r in table:
        def cell(p): return f"{p['k']}/{p['n']} ({p['rate']:.0%})" if p["rate"] is not None else "n/a"
        lines.append(f"{r['threshold']:>9.2f}  {cell(r['slips_needing_review']):>22}  {cell(r['unnecessary_reviews']):>22}  "
                     f"{cell(r['slips_with_silent_critical_misread']):>24}  {cell(r['wrong_fields_covered']):>22}")
    lines.append("A higher threshold sends more reads to a person (review load) and leaves fewer silent misreads.")
    return "\n".join(lines)


# ---------------------------------------------------------------- printing


def _pct(p: dict) -> str:
    if p["rate"] is None:
        return "n/a"
    lo, hi = p["ci95"]
    return f"{p['k']}/{p['n']} = {p['rate']:.0%}  (95% CI {lo:.0%}-{hi:.0%})"


def format_report(report: dict) -> str:
    s = report["summary"]
    lines = [f"EXPLORATORY evaluation, split={report['split']}, {s['slips']} of {s['slips_labeled']} slips read "
             f"(small sample: intervals are wide)", f"commit {report['commit'][:10] or 'unknown'}"
             + ("  (tracked files have uncommitted changes)" if report["uncommitted_tracked_changes"] else ""), ""]
    if report["missing"]:
        lines += ["Not evaluated: " + ", ".join(f"{m['slip']} ({m['why']})" for m in report["missing"]), ""]
    lines += ["Reading accuracy (fields blank on the paper and read as blank are not counted)",
              f"  all fields        {_pct(s['fields_correct'])}",
              f"  critical fields   {_pct(s['critical_fields_correct'])}", "",
              "What happened to each slip",
              f"  read correctly                      {_pct(s['outcomes']['read_correctly'])}",
              f"  misread, caught (flag/review/block) {_pct(s['outcomes']['misread_caught'])}",
              f"  misread, NOT caught (critical)      {_pct(s['outcomes']['misread_not_caught'])}",
              f"  misread, minor and unflagged        {_pct(s['outcomes']['misread_noncritical_unflagged'])}", ""]
    rp = s.get("reaches_posting")
    if rp:
        lines += ["Would a wrong value reach a posted entry? (stopped = review, a block on that field; a warning is not a stop.",
                  " Assumes the clerk settles every stop correctly and posts past warnings.)",
                  f"  slips posting a wrong critical value  {_pct(rp['slips_with_wrong_critical_value'])}",
                  f"  slips posting any wrong value         {_pct(rp['slips_with_any_wrong_value'])}",
                  f"  wrong fields stopped before posting   {_pct(rp['stopped'])}",
                  f"  wrong fields that were only warned    {rp['warned_only']}", ""]
    if report.get("locked_summary_reproduced"):
        same = report["locked_summary_reproduced"]
        bad = [k for k, ok in same.items() if not ok]
        lines += ["Every number in the locked run reproduced exactly." if not bad
                  else "WARNING: these locked numbers did NOT reproduce: " + ", ".join(bad), ""]
    w = s["wrong_fields"]
    lines += [f"Wrong fields: {w['total']}  (caught by review {w['caught_by_review']}, by a new rule flag "
              f"{w['caught_by_new_flag']}, absorbed by an existing block {w['absorbed_by_existing_block']}, "
              f"silent critical {w['silent_critical']}, silent minor {w['silent_noncritical']})",
              f"  error-detection recall   {_pct(s['detection_recall'])}",
              f"  unnecessary reviews      {_pct(s['unnecessary_review'])}   (correct fields sent to review)",
              f"  slips needing review     {_pct(s['review_rate'])}", "",
              "Confidence vs observed correctness (reliability, not calibration)"]
    for b in s["confidence_bins"]:
        acc = "n/a" if b["accuracy"] is None else f"{b['accuracy']:.0%}"
        note = "" if b["interpretable"] else "   n<10: not interpretable"
        lines.append(f"  {b['confidence']:>8}   fields {b['fields']:>3}   correct {b['correct']:>3}   {acc:>5}{note}")
    if report["misreads"]:
        lines += ["", "Every misread"]
        for m in report["misreads"]:
            conf = "-" if m["confidence"] is None else f"{m['confidence']:.2f}"
            lines.append(f"  {m['slip']:>14} style {m['style']} {m['condition']:<10} {m['field']:<18} paper '{m['paper']}' "
                         f"read '{m['read']}'  conf {conf}  {'CRITICAL ' if m['critical'] else ''}{m['caught_by']}")
    t = report["tokens_across_all_readings"]
    lines += ["", "Fields within one slip are not independent, so the field-level intervals are optimistic; "
              "the slip-level ones are the honest ones.",
              f"Live calls this run: {report['live_calls_this_run']}   tokens across all {t['readings']} readings: "
              f"{t['input']:,} in, {t['output']:,} out"]
    return "\n".join(lines)
