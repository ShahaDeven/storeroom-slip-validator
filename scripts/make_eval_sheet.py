"""Build the evaluation writing sheet and the transcription-truth file.

    python scripts/make_eval_sheet.py

Writes data/eval/WRITE_THESE.md (what to handwrite and photograph) and data/eval/labels.csv
(what each slip says). Slip content comes from the real catalog and work orders, and each slip
is checked with the real validator so it contains the problem it is meant to contain.

Protocol: commit labels.csv BEFORE photographing or running the held-out slips. The held-out
set is run once, after rules and thresholds are frozen on the development set.
"""

from __future__ import annotations

import csv
import random
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from slipcheck import load_reference, validate  # noqa: E402
from slipcheck.impact import TODAY, UNIT_WORD  # noqa: E402

OUT = ROOT / "data" / "eval"
ref = load_reference()
PARTS = list(ref.parts.values())
OPEN = [w for w in ref.work_orders.values() if w.is_open]
CLOSED = [w for w in ref.work_orders.values() if not w.is_open]

STYLES = {
    "A": "your normal handwriting",
    "B": "fast and slanted, the way you write when in a hurry",
    "C": "ALL CAPITALS, small and tight",
    "D": "your non-dominant hand (or a very different pen and grip)",
}
NOTES = {
    "clear": "",
    "compressed": "write small and tight, letters close together",
    "poor_light": "photograph it in dim light",
    "skewed": "photograph it at an angle, not straight on",
    "abbrev": "",
    "crossout": "",
}

# id, split, style, scenario, condition, options. Existing photos slip_clean / slip_hard_case
# are the other two development slips, so 8 new development slips + 20 held-out = 28 to write.
ROWS = [
    ("D01", "dev", "A", "clean_2line", "clear", {}),
    ("D02", "dev", "A", "closed_wo", "clear", {}),
    ("D03", "dev", "A", "pairs_no_unit", "clear", {}),
    ("D04", "dev", "A", "name_only_unique", "abbrev", {}),
    ("D05", "dev", "B", "clean_3line", "clear", {}),
    ("D06", "dev", "B", "missing_signature", "clear", {}),
    ("D07", "dev", "B", "name_only_ambiguous", "crossout", {}),
    ("D08", "dev", "B", "similar_digits", "clear", {}),
    ("H01", "heldout", "A", "clean_2line", "clear", {}),
    ("H02", "heldout", "A", "closed_wo", "compressed", {}),
    ("H03", "heldout", "A", "pairs_no_unit", "poor_light", {}),
    ("H04", "heldout", "A", "unknown_wo", "clear", {}),
    ("H05", "heldout", "A", "clean_3line", "skewed", {}),
    ("H06", "heldout", "B", "closed_wo", "crossout", {}),
    ("H07", "heldout", "B", "name_only_unique", "abbrev", {}),
    ("H08", "heldout", "B", "similar_digits", "compressed", {}),
    ("H09", "heldout", "B", "missing_field", "clear", {"missing": "date"}),
    ("H10", "heldout", "B", "big_pull", "poor_light", {}),
    ("H11", "heldout", "C", "clean_2line", "clear", {}),
    ("H12", "heldout", "C", "pairs_no_unit", "compressed", {}),
    ("H13", "heldout", "C", "name_only_ambiguous", "clear", {}),
    ("H14", "heldout", "C", "similar_digits", "skewed", {}),
    ("H15", "heldout", "C", "missing_signature", "abbrev", {}),
    ("H16", "heldout", "D", "clean_3line", "clear", {}),
    ("H17", "heldout", "D", "closed_wo", "crossout", {}),
    ("H18", "heldout", "D", "similar_digits", "clear", {}),
    ("H19", "heldout", "D", "box_units", "compressed", {}),
    ("H20", "heldout", "D", "missing_field", "poor_light", {"missing": "location"}),
]


# ---------------------------------------------------------------- building blocks


def mmddyy(d) -> str:
    return d.strftime("%m/%d/%y")


def pick_date(rng, start):
    start = max(start, TODAY - timedelta(days=20))
    return start + timedelta(days=rng.randint(0, (TODAY - start).days))


def header(rng, wo, closed=False):
    start = wo.closed if closed else wo.opened
    return {"wo_number": wo.wo_number, "date": mmddyy(pick_date(rng, start)),
            "taken_by": rng.choice(wo.members), "location": wo.location, "signature": True}


def qty_for(rng, p, hi=6):
    return rng.randint(1, max(1, min(p.max_per_pull, p.on_hand, hi)))


def line(rng, p, qty, unit=True, number=True, name=None):
    return {"part_number": p.part_number if number else "",
            "part_name": name or rng.choice(p.aliases or (p.name,)),
            "qty": str(qty), "unit": UNIT_WORD[p.unit] if unit else ""}


def some(rng, n, units=("EA", "RL", "BX"), exclude=()):
    pool = [p for p in PARTS if p.unit in units and p.part_number not in exclude]
    return rng.sample(pool, n)


def by_number(pn):
    return ref.parts[pn]


def s_clean(rng, n):
    slip = header(rng, rng.choice(OPEN))
    slip["items"] = [line(rng, p, qty_for(rng, p)) for p in some(rng, n)]
    return slip


def s_closed(rng):
    slip = header(rng, rng.choice(CLOSED), closed=True)
    slip["items"] = [line(rng, p, qty_for(rng, p)) for p in some(rng, rng.choice([1, 2]))]
    return slip


def s_pairs(rng):
    slip = header(rng, rng.choice(OPEN))
    pair = rng.choice([p for p in PARTS if p.unit == "PR"])
    slip["items"] = [line(rng, pair, rng.choice([2, 4]), unit=False)]
    if rng.random() < 0.5:
        extra = some(rng, 1, exclude={pair.part_number})[0]
        slip["items"].append(line(rng, extra, qty_for(rng, extra)))
    return slip


UNIQUE = [("wax ring", "PL-1020"), ("flapper", "PL-1021"), ("teflon tape", "PL-1040"),
          ("p-trap", "PL-1050"), ("door closer", "GN-4011"), ("safety glasses", "GN-4070"),
          ("mop head", "JN-5010")]
AMBIGUOUS = [("duplex outlet", "EL-2010"), ("ball valve", "PL-1010"),
             ("air filter", "HV-3001"), ("v-belt", "HV-3010")]


def s_name_only(rng, table):
    slip = header(rng, rng.choice(OPEN))
    phrase, pn = rng.choice(table)
    p = by_number(pn)
    slip["items"] = [line(rng, p, qty_for(rng, p, hi=4), number=False, name=phrase)]
    if rng.random() < 0.5:
        extra = some(rng, 1, exclude={pn})[0]
        slip["items"].append(line(rng, extra, qty_for(rng, extra)))
    return slip


def s_unsigned(rng):
    slip = s_clean(rng, 2)
    slip["signature"] = False
    return slip


def s_unknown_wo(rng):
    wo = rng.choice(OPEN)
    slip = header(rng, wo)
    digits = wo.wo_number[-4:]
    for i in (1, 2, 0):
        swapped = list(digits)
        swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        candidate = f"WO-26-{''.join(swapped)}"
        if candidate not in ref.work_orders:
            slip["wo_number"] = candidate
            break
    slip["items"] = [line(rng, p, qty_for(rng, p)) for p in some(rng, 2)]
    return slip


def s_big(rng):
    slip = header(rng, rng.choice(OPEN))
    p = by_number(rng.choice(["EL-2030", "JN-5003", "EL-2060", "PL-1004"]))
    qty = min(p.max_per_pull + rng.randint(6, 16), p.on_hand)
    slip["items"] = [line(rng, p, qty)]
    return slip


FAMILIES = [(("PL-1001", 17), ("PL-1002", 14)), (("PL-1001", 11), ("PL-1002", 7)),
            (("EL-2060", 19), ("EL-2061", 16)), (("EL-2060", 10), ("EL-2061", 6)),
            (("EL-2010", 10), ("EL-2011", 7))]


def s_similar(rng):
    slip = header(rng, rng.choice(OPEN))
    first, second = rng.choice(FAMILIES)
    slip["items"] = [line(rng, by_number(pn), q) for pn, q in (first, second)]
    return slip


def s_box(rng):
    slip = header(rng, rng.choice(OPEN))
    boxed = rng.sample([p for p in PARTS if p.unit == "BX"], 2)
    slip["items"] = [line(rng, p, rng.randint(1, min(3, p.max_per_pull))) for p in boxed]
    return slip


def s_missing(rng, missing):
    slip = s_clean(rng, 2)
    slip[missing] = ""
    return slip


BUILD = {
    "clean_2line": lambda r, o: s_clean(r, 2), "clean_3line": lambda r, o: s_clean(r, 3),
    "closed_wo": lambda r, o: s_closed(r), "pairs_no_unit": lambda r, o: s_pairs(r),
    "name_only_unique": lambda r, o: s_name_only(r, UNIQUE),
    "name_only_ambiguous": lambda r, o: s_name_only(r, AMBIGUOUS),
    "missing_signature": lambda r, o: s_unsigned(r), "unknown_wo": lambda r, o: s_unknown_wo(r),
    "big_pull": lambda r, o: s_big(r), "similar_digits": lambda r, o: s_similar(r),
    "box_units": lambda r, o: s_box(r), "missing_field": lambda r, o: s_missing(r, o["missing"]),
}

# Each slip must really contain the problem it is named for (checked with the real validator).
CHECK = {
    "clean_2line": lambda c, b: not b, "clean_3line": lambda c, b: not b,
    "closed_wo": lambda c, b: "CLOSED_WO" in c, "pairs_no_unit": lambda c, b: "UNIT_AMBIGUOUS" in c,
    "name_only_unique": lambda c, b: "NAME_MATCHED" in c and "PART_AMBIGUOUS" not in c and not b,
    "name_only_ambiguous": lambda c, b: "PART_AMBIGUOUS" in c,
    "missing_signature": lambda c, b: "MISSING_SIGNATURE" in c, "unknown_wo": lambda c, b: "UNKNOWN_WO" in c,
    "big_pull": lambda c, b: "UNUSUAL_QTY" in c and not b, "similar_digits": lambda c, b: not b,
    "box_units": lambda c, b: not b,
    "missing_field": lambda c, b: bool({"MISSING_DATE", "LOCATION_FROM_WO", "MISSING_TAKEN_BY"} & c),
}

PLACE = {"Library": "Lib", "Residence": "Res", "Administration": "Admin", "Science Center": "Sci Ctr",
         "Dining Hall": "Dining", "Parking Ramp": "Ramp"}


def apply_condition(slip, cond):
    """Change how the slip is WRITTEN (the truth is what ends up on the paper). Returns a note."""
    if cond == "abbrev":
        for long, short in PLACE.items():
            slip["location"] = slip["location"].replace(long, short)
        slip["wo_number"] = slip["wo_number"].removeprefix("WO-")
        for it in slip["items"]:
            it["unit"] = {"box": "bx", "roll": "rl"}.get(it["unit"], it["unit"])
        return "write the W/O number without the WO- prefix, and abbreviate as shown"
    if cond == "crossout":
        it = slip["items"][0]
        q = int(it["qty"])
        wrong = q - 1 if q > 1 else q + 1
        return f"line 1: write {wrong} as the quantity, cross it out, then write {q}"
    return NOTES[cond]


def build_row(slip_id, split, style, scenario, cond, opts):
    for attempt in range(80):
        rng = random.Random(f"eval-{slip_id}-{attempt}")
        slip = BUILD[scenario](rng, opts)
        note = apply_condition(slip, cond)
        report = validate(slip, ref, TODAY)
        codes = {i.code for i in report.issues}
        blocks = {i.code for i in report.issues if i.severity == "block"}
        if CHECK[scenario](codes, blocks):
            return slip, note, report
    raise RuntimeError(f"could not build {slip_id} ({scenario})")


# ---------------------------------------------------------------- outputs

COLUMNS = ["slip_id", "split", "style", "scenario", "condition", "photo", "wo_number", "date",
           "taken_by", "location", "signed"] + [f"line{n}_{f}" for n in (1, 2, 3)
                                                 for f in ("part_number", "description", "qty", "unit")] + [
          "note", "expected_status", "expected_issues"]


def csv_row(slip_id, split, style, scenario, cond, photo, slip, note, report):
    row = {"slip_id": slip_id, "split": split, "style": style, "scenario": scenario, "condition": cond,
           "photo": photo, "wo_number": slip["wo_number"], "date": slip["date"], "taken_by": slip["taken_by"],
           "location": slip["location"], "signed": "yes" if slip["signature"] else "no", "note": note,
           "expected_status": report.status if report else "",
           "expected_issues": ";".join(sorted({i.code for i in report.issues if i.severity != "info"})) if report else ""}
    for n, it in enumerate(slip["items"], 1):
        row.update({f"line{n}_part_number": it["part_number"], f"line{n}_description": it["part_name"],
                    f"line{n}_qty": it["qty"], f"line{n}_unit": it["unit"]})
    return row


EXISTING = [  # the two photos already taken; intended content, to be CONFIRMED against the paper
    ("slip_clean", "A", "clean_2line", "clear", "data/photos/slip_clean.jpeg",
     {"wo_number": "WO-26-0412", "date": "10/22/26", "taken_by": "J. Rivera", "location": "Harlow Hall", "signature": True,
      "items": [{"part_number": "PL-1001", "part_name": "3/4 PVC elbow", "qty": "6", "unit": "ea"},
                {"part_number": "PL-1010", "part_name": "3/4 ball valve", "qty": "2", "unit": "ea"}]}),
    ("slip_hard_case", "A", "closed_wo", "clear", "data/photos/slip_hard_case.jpeg",
     {"wo_number": "26-0390", "date": "10/26/26", "taken_by": "A. Okafor", "location": "Pierce Lib", "signature": True,
      "items": [{"part_number": "", "part_name": "duplex outlet", "qty": "4", "unit": ""},
                {"part_number": "GN-4010", "part_name": "hinges", "qty": "2", "unit": ""}]}),
]


def sheet_block(slip_id, split, style, scenario, cond, slip, note):
    def v(x):
        return f"`{x}`" if x else "(leave blank)"
    out = [f"### {slip_id}  |  style {style}" + (f"  |  {NOTES[cond] or cond}" if cond in NOTES and NOTES[cond] else ""),
           f"- W/O #: {v(slip['wo_number'])}    Date: {v(slip['date'])}",
           f"- Taken by: {v(slip['taken_by'])}    Location: {v(slip['location'])}",
           "", "| Part # | Description | Qty | Unit |", "|---|---|---|---|"]
    for it in slip["items"]:
        out.append(f"| {v(it['part_number'])} | {v(it['part_name'])} | {v(it['qty'])} | {v(it['unit'])} |")
    out += ["", f"- Signature: {'sign it' if slip['signature'] else 'leave the signature BLANK'}"]
    if note and cond in ("abbrev", "crossout"):
        out.append(f"- Writing note: {note}")
    return "\n".join(out) + "\n"


def main():
    (OUT / "photos").mkdir(parents=True, exist_ok=True)
    csv_rows, blocks = [], {"dev": [], "heldout": []}
    for slip_id, split, style, scenario, cond, opts in ROWS:
        slip, note, report = build_row(slip_id, split, style, scenario, cond, opts)
        csv_rows.append(csv_row(slip_id, split, style, scenario, cond, f"data/eval/photos/{slip_id}.jpeg", slip, note, report))
        blocks[split].append(sheet_block(slip_id, split, style, scenario, cond, slip, note))
    for slip_id, style, scenario, cond, photo, slip in EXISTING:
        csv_rows.append(csv_row(slip_id, "dev", style, scenario, cond, photo, slip,
                                "CONFIRM against the photo: label what the paper says, not what you meant to write", None))

    with open(OUT / "labels.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(csv_rows)

    sheet = ["# Slips to write and photograph", "",
             "28 new slips: **8 development** (D01-D08) and **20 held-out** (H01-H20). The two photos you already took "
             "count as the other two development slips. Everything is synthetic; the work orders and parts exist in the sample data.", "",
             "## How to write them", "",
             "One sheet of paper per slip, laid out like the earlier ones: title, `W/O #`, `Date`, `Taken by`, `Location`, then "
             "the columns **Part # | Description | Qty | Unit**, then `Signature`. Write the labels and draw the column lines, "
             "as you did before. Use a dark pen.", "",
             "**Write exactly what each block says.** A blank is a blank: don't write `none` or a dash. If you make a real mistake "
             "on the paper, leave it, and correct the matching row in `labels.csv` to **what the paper actually says**.", "",
             "**Styles** (this is one writer in four deliberate styles, and the evaluation will say so):", ""]
    sheet += [f"- **{k}**: {v}" for k, v in STYLES.items()]
    sheet += ["", "**Photos:** flat on a table, whole page in frame, JPEG, saved as `data/eval/photos/<ID>.jpeg` "
              "(for example `D03.jpeg`), unless the block says dim light or an angle.", "",
              "**Order:** write the 8 development slips first. Write the held-out slips in a separate sitting. "
              "Don't open the model's readings of the held-out set until we agree the rules are frozen.", "",
              "---", "", "## Development slips (D01-D08)", ""] + blocks["dev"] + ["", "---", "",
              "## Held-out slips (H01-H20)", ""] + blocks["heldout"]
    (OUT / "WRITE_THESE.md").write_text("\n".join(sheet), encoding="utf-8")

    print(f"{'id':5}{'split':8}{'sty':4}{'scenario':22}{'condition':12}{'expected':22}issues")
    for r in csv_rows:
        print(f"{r['slip_id']:5}{r['split']:8}{r['style']:4}{r['scenario']:22}{r['condition']:12}{r['expected_status']:22}{r['expected_issues']}")


if __name__ == "__main__":
    main()
