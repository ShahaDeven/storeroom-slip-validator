"""Failure analysis: where the photo-reading + rules pipeline goes wrong, from saved eval results.

Reads the results files `python -m slipcheck eval` writes; never calls a model and never re-runs
anything. Same definitions as EVAL.md:
  stopped          review request, a new block on the field, or an existing block on it
  warned only      a new warning, nothing that blocks: the slip still posts
  nothing raised   no flag at all
  would be posted  wrong, stored in the posted entry, and not stopped
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from collections import Counter
from difflib import SequenceMatcher

from slipcheck.eval import EVAL_DIR, wilson

SPLITS = {
    "heldout_corrected": ("Held-out, corrected", ["results_heldout_corrected.json"]),
    "heldout_locked": ("Held-out, locked", ["results_heldout_rescored.json", "results_heldout.json"]),
    "dev": ("Development", ["results_dev.json"]),
    "dev_v2": ("Development, rules v2", ["results_dev_v2.json"]),
    "heldout_corrected_v2": ("Held-out corrected, rules v2", ["results_heldout_corrected_v2.json"]),
}
# What a reader must know before trusting a view.
NOTES = {
    "heldout_locked": "Includes two photos saved under each other's names (H02/H03): their 'misreads' are each "
                      "other's answers. The corrected view fixes only that.",
    "dev_v2": "Rules v2 were written after this development set was used; it is where they were checked.",
    "heldout_corrected_v2": "Not a held-out result: rules v2 were written after these slips were seen (they fix "
                            "gaps the adversarial suite found). It shows what v2 changes on the same readings; "
                            "a new held-out set is needed to measure v2.",
}
RULESET = {"dev_v2": "v2", "heldout_corrected_v2": "v2"}  # every other view is the frozen rules, v1
LABEL = {"wo_number": "W/O number", "date": "Date", "taken_by": "Taken by", "location": "Location",
         "signature": "Signature", "part_number": "Part number", "part_name": "Description", "qty": "Quantity",
         "unit": "Unit"}
STYLE = {"A": "A, normal", "B": "B, fast and slanted", "C": "C, small capitals", "D": "D, non-dominant hand"}
CONDITION = {"clear": "Clear photo", "abbrev": "Abbreviations", "compressed": "Compressed writing",
             "crossout": "Crossed-out quantity", "poor_light": "Dim light", "skewed": "Angled photo"}
BINS = [round(0.5 + 0.05 * i, 2) for i in range(10)]  # 0.50, 0.55 ... 0.95; the last bin includes 1.0
THRESHOLD = 0.75
ALWAYS_CRITICAL = {"wo_number", "signature", "part_number", "qty", "unit"}


class NoResults(LookupError):
    pass


def _prop(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci95": [round(lo, 3), round(hi, 3)]}


def error_kind(truth: str, read: str) -> str:
    """A rough, mechanical label for how a value was misread."""
    if not read:
        return "read as blank"
    if not truth:
        return "read where the paper is blank"
    t, r = re.sub(r"[^0-9a-z]", "", truth.lower()), re.sub(r"[^0-9a-z]", "", read.lower())
    if t == r:
        return "spacing or punctuation only"
    if re.sub(r"\d", "", t) == re.sub(r"\d", "", r) and re.search(r"\d", t + r):
        return "digit misread or dropped"
    if SequenceMatcher(None, t, r).ratio() >= 0.6:
        return "letters misread"
    return "different word"


def _fate(f: dict) -> str:
    if f["review"] or f.get("new_block") or f["absorbed"]:
        return "stopped"
    return "warned_only" if f["new_flag"] else "nothing_raised"


def _stored(f: dict) -> bool:
    return f["critical"] or f["name"] in ("date", "taken_by", "location")


def load(split: str) -> tuple[str, dict]:
    if split not in SPLITS:
        raise NoResults(f"Unknown split '{split}'.")
    title, names = SPLITS[split]
    for name in names:
        path = EVAL_DIR / name
        if path.exists():
            return name, json.loads(path.read_text(encoding="utf-8"))
    raise NoResults(f"No results for {title}. Run python -m slipcheck eval first.")


def analyze(split: str = "heldout_corrected") -> dict:
    source, report = load(split)
    slips = report["slips"]
    strict_known = all("new_block" in f for s in slips for f in s["fields"])
    fields = [f | {"style": s["style"], "condition": s["condition"]} for s in slips for f in s["fields"]]
    wrong = [f for f in fields if not f["correct"]]
    correct = [f for f in fields if f["correct"]]
    posted = [f for f in wrong if _stored(f) and _fate(f) != "stopped"]

    # 1. most misread fields, with what happened to each misread
    by_field = []
    for name in LABEL:
        w = [f for f in wrong if f["name"] == name]
        total = sum(f["name"] == name for f in fields)
        if not total:
            continue
        fates = Counter(_fate(f) for f in w)
        by_field.append({"field": name, "label": LABEL[name], "fields": total, "wrong": len(w),
                         "stopped": fates["stopped"], "warned_only": fates["warned_only"],
                         "nothing_raised": fates["nothing_raised"],
                         "posted": sum(f in posted for f in w),
                         "critical": "always" if name in ALWAYS_CRITICAL else
                                     "when no part number" if name == "part_name" else "no"})
    by_field.sort(key=lambda r: (-r["wrong"], r["label"]))

    # 2. false positives: correct reads that were flagged anyway. Reviews and blocks stop posting until a
    #    person answers; warnings are shown but don't stop anything, so they are counted apart.
    def flagged(n: str) -> dict:
        ff = [f for f in correct if f["name"] == n]
        return {"field": n, "label": LABEL[n],
                "reviews": sum(f["review"] for f in ff),
                "rule_blocks": sum(bool(f.get("new_block")) and not f["review"] for f in ff),
                "rule_warnings": sum(f["new_flag"] and not f.get("new_block") and not f["review"] for f in ff)}
    fp = [flagged(n) for n in LABEL]
    fp = sorted((r for r in fp if r["reviews"] or r["rule_blocks"] or r["rule_warnings"]),
                key=lambda r: (-(r["reviews"] + r["rule_blocks"]), -r["rule_warnings"], r["label"]))
    fp_totals = {k: sum(r[k] for r in fp) for k in ("reviews", "rule_blocks", "rule_warnings")}

    # 3. misses: every wrong value that would be posted, and every wrong value nothing was raised about
    def row(f: dict) -> dict:
        return {"slip": f["slip_id"], "style": f["style"], "condition": f["condition"], "name": f["name"],
                "field": LABEL.get(f["name"], f["name"]), "line": f["line"], "paper": f["truth"], "read": f["read"],
                "confidence": f["confidence"], "critical": f["critical"], "fate": _fate(f),
                "kind": error_kind(f["truth"], f["read"]), "posted": f in posted}
    misses = sorted((row(f) for f in wrong if _fate(f) != "stopped"),
                    key=lambda r: (not r["posted"], not r["critical"], r["slip"]))
    kinds = Counter(r["kind"] for r in misses)

    # 4. confidence distribution, correct vs wrong
    dist = []
    for i, lo in enumerate(BINS):
        hi = BINS[i + 1] if i + 1 < len(BINS) else 1.0001
        in_bin = [f for f in fields if f["confidence"] is not None and lo <= f["confidence"] < hi]
        dist.append({"from": lo, "to": min(hi, 1.0), "correct": sum(f["correct"] for f in in_bin),
                     "wrong": sum(not f["correct"] for f in in_bin)})
    below = sum(f["confidence"] is not None and f["confidence"] < BINS[0] for f in fields)
    confident_wrong = [f for f in wrong if (f["confidence"] or 0) >= 0.9]

    # 5. review frequency
    per_slip = [{"slip": s["slip_id"], "style": s["style"], "reviews": sum(f["review"] for f in s["fields"]),
                 "needless": sum(f["review"] and f["correct"] for f in s["fields"]),
                 "posted_wrong": sum(f in posted for f in fields if f["slip_id"] == s["slip_id"])}
                for s in slips]
    hist = Counter(min(p["reviews"], 3) for p in per_slip)

    # 6. by handwriting style and photo condition (the only "document type" axis evaluated)
    def group(key: str, names: dict) -> list[dict]:
        out = []
        for k in sorted({s[key] for s in slips}):
            ss = [s for s in slips if s[key] == k]
            ff = [f for f in fields if f[key] == k]
            out.append({"key": k, "label": names.get(k, k), "slips": len(ss),
                        "fields_correct": _prop(sum(f["correct"] for f in ff), len(ff)),
                        "slips_reviewed": sum(s["review_requested"] for s in ss),
                        "slips_posting_wrong": len({f["slip_id"] for f in posted if f[key] == k})})
        return out

    top = by_field[0] if by_field and by_field[0]["wrong"] else None
    top_posted = max(by_field, key=lambda r: r["posted"]) if any(r["posted"] for r in by_field) else None
    styles = group("style", STYLE)
    worst = min(styles, key=lambda g: g["fields_correct"]["rate"] or 0) if styles else None
    slips_reviewed = sum(s["review_requested"] for s in slips)
    crit_slips = len({f["slip_id"] for f in posted if f["critical"]})

    findings = []
    if top:
        findings.append(f"{top['label']} is misread most: {top['wrong']} of {top['fields']} reads.")
    if top_posted:
        findings.append(f"{top_posted['label']} carries the most wrong values that would be posted "
                        f"({top_posted['posted']} of {len(posted)}).")
    if kinds:
        k, n = kinds.most_common(1)[0]
        findings.append(f"The commonest unstopped misread is '{k}' ({n} of {len(misses)}).")
    findings.append(f"{len(confident_wrong)} wrong fields were read at confidence 0.90 or above; "
                    "confidence alone would have passed them.")
    findings.append(f"{slips_reviewed} of {len(slips)} slips needed a person, and "
                    f"{sum(f['review'] for f in correct)} correctly read fields were sent to review anyway.")
    if worst:
        findings.append(f"Hardest handwriting: style {worst['label']} ({worst['fields_correct']['k']}/"
                        f"{worst['fields_correct']['n']} fields read correctly).")

    return {
        "split": split, "title": SPLITS[split][0], "source": source, "commit": report.get("commit"),
        "ruleset": RULESET.get(split, "v1"), "note": NOTES.get(split),
        "strict_known": strict_known,
        "splits": [{"key": k, "title": t} for k, (t, names) in SPLITS.items()
                   if any((EVAL_DIR / n).exists() for n in names)],
        "tiles": {
            "slips": len(slips),
            "posting_wrong_critical": _prop(crit_slips, len(slips)),
            "posting_wrong_any": _prop(len({f["slip_id"] for f in posted}), len(slips)),
            "slips_reviewed": _prop(slips_reviewed, len(slips)),
            "person_needed": _prop(sum(bool(s.get("person_needed")) for s in slips), len(slips)),
            "confident_wrong": {"k": len(confident_wrong),
                                "n": sum((f["confidence"] or 0) >= 0.9 for f in fields)},
        },
        "findings": findings,
        "by_field": by_field,
        "false_positives": fp,
        "false_positive_totals": fp_totals,
        "unnecessary_reviews": _prop(sum(f["review"] for f in correct), len(correct)),
        "misses": misses,
        "miss_kinds": [{"kind": k, "count": n} for k, n in kinds.most_common()],
        "confidence": {"bins": dist, "below": below, "threshold": THRESHOLD,
                       "no_confidence": sum(f["confidence"] is None for f in fields)},
        "reviews": {"per_slip": per_slip, "histogram": [{"reviews": k, "slips": hist.get(k, 0)} for k in range(4)]},
        "by_style": styles,
        "by_condition": group("condition", CONDITION),
    }


# ---------------------------------------------------------------- drill-down to one slip


def slip_detail(split: str, slip_id: str) -> dict:
    """Everything needed to inspect one evaluated slip: the photo its reading came from, the cached reading
    (with provenance), the answer key, and every scored field. Nothing is re-read."""
    from slipcheck.eval import load_corrections, load_labels, photo_for, reading_path
    from slipcheck.extract import add_provenance

    _, report = load(split)
    scored = next((s for s in report["slips"] if s["slip_id"] == slip_id), None)
    if scored is None:
        raise NoResults(f"No slip {slip_id} in {SPLITS[split][0]}.")
    rows = {r["slip_id"]: r for r in load_labels("dev" if split.startswith("dev") else "heldout")}
    corrections = load_corrections() if "corrected" in split else {}
    source = rows.get(photo_for(slip_id, corrections), rows[slip_id])  # the row whose photo this reading is
    path = reading_path(source)
    reading = add_provenance(json.loads(path.read_text(encoding="utf-8")), Path(source["photo"]).name)
    return {"split": split, "ruleset": RULESET.get(split, "v1"), "slip": slip_id,
            "style": scored["style"], "condition": scored["condition"], "photo_of": source["slip_id"],
            "photo": f"/api/eval/photo/{source['slip_id']}",
            "swapped": source["slip_id"] != slip_id or (split == "heldout_locked" and slip_id in _swapped()),
            "truth": {k: v for k, v in rows[slip_id].items() if k not in ("photo",)},
            "reading": reading, "fields": scored["fields"], "outcome": scored["outcome"]}


def _swapped() -> set[str]:
    from slipcheck.eval import load_corrections

    return {sid for sw in load_corrections().get("photo_swaps", []) for sid in sw["slips"]}


def photo_path(slip_id: str) -> Path:
    from slipcheck.eval import ROOT, load_labels

    for split in ("dev", "heldout"):
        for r in load_labels(split):
            if r["slip_id"] == slip_id:
                path = (ROOT / r["photo"]).resolve()
                if path.is_file() and path.is_relative_to(ROOT.resolve()):
                    return path
    raise NoResults(f"No photo for {slip_id}.")
