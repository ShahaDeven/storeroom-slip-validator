"""What the checker is worth, compared with the manual process. MODELED, not measured.

Two parts, kept separate on purpose:

1. measure_detection: actually runs the validator. Builds clean synthetic slips, injects
   each error type seen at the counter, and records whether the real rules caught it.
   This part is code behaving, not an assumption.

2. model: combines that detection rate with the observed storeroom numbers and the
   labeled assumptions in data/impact_assumptions.json to estimate hours per week and
   year, manual vs checked, plus the break-even share of slip-caused mismatches.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from slipcheck.reference import DATA_DIR, Part, Reference
from slipcheck.validate import validate

ASSUMPTIONS = DATA_DIR / "impact_assumptions.json"
TODAY = date(2026, 10, 27)
UNIT_WORD = {"EA": "ea", "PR": "pr", "BX": "box", "RL": "roll"}

ERROR_LABEL = {
    "closed_wo": "Old, closed W/O number written",
    "pairs_no_unit": "Pieces written for a pair-tracked part, no unit",
    "name_only": "Part name only, no number",
    "illegible": "Field too unclear to read",
    "missing_signature": "Not signed",
    "plausible_wrong_qty": "Wrong but plausible quantity",
    "wrong_part_number": "Neighbouring part number, right name",
}

# Which end of each range is worse for the checker's case. The pessimistic scenario takes
# all of these at once, so "low" savings is a floor, not an average.
WORSE = {"slips_per_week": "high", "mismatches_per_week": "low", "minutes_per_mismatch": "low",
         "slip_caused_share": "low", "minutes_per_flag": "high", "seconds_added_per_slip": "high",
         "unresolved_share": "low", "clerk_hourly_cost": "low", "weeks_per_year": "low"}


# ---------------------------------------------------------------- 1. detection


def _clean_slip(rng: random.Random, ref: Reference) -> dict:
    wo = rng.choice([w for w in ref.work_orders.values() if w.is_open])
    days = max(0, (TODAY - wo.opened).days)
    parts = rng.sample(list(ref.parts.values()), rng.choice([1, 1, 2, 2, 3]))
    return {
        "wo_number": wo.wo_number,
        "date": (wo.opened + timedelta(days=rng.randint(0, days))).strftime("%m/%d/%Y"),
        "taken_by": rng.choice(wo.members),
        "location": wo.location,
        "signature": True,
        "items": [{"part_number": p.part_number, "part_name": rng.choice(p.aliases or (p.name,)),
                   "qty": rng.randint(1, min(p.max_per_pull, p.on_hand)), "unit": UNIT_WORD[p.unit]}
                  for p in parts],
    }


def _neighbour(part: Part, ref: Reference) -> Part:
    family = sorted(pn for pn in ref.parts if pn[:2] == part.part_number[:2])
    i = family.index(part.part_number)
    return ref.parts[family[i + 1] if i + 1 < len(family) else family[i - 1]]


def inject(kind: str, slip: dict, rng: random.Random, ref: Reference) -> tuple[dict, str | None]:
    """Write the slip with one error. Returns (slip, true part number of line 1 if relevant)."""
    line = slip["items"][0]
    truth = line["part_number"]
    if kind == "closed_wo":
        wo = ref.work_orders[slip["wo_number"]]
        closed = [w for w in ref.work_orders.values() if not w.is_open]
        slip["wo_number"] = rng.choice([w for w in closed if w.crew == wo.crew] or closed).wo_number
    elif kind == "pairs_no_unit":
        part = rng.choice([p for p in ref.parts.values() if p.unit == "PR"])
        pairs = rng.randint(1, min(part.max_per_pull, part.on_hand))
        slip["items"][0] = {"part_number": part.part_number, "part_name": part.aliases[0],
                            "qty": pairs * part.unit_size, "unit": None}
        truth = part.part_number
    elif kind == "name_only":
        part = ref.parts[truth]
        line["part_number"] = None
        line["part_name"] = rng.choice((part.name, *part.aliases))
    elif kind == "illegible":
        key = rng.choice(["taken_by", "wo_number", "qty"])
        blur = {"value": None, "raw": "?" * rng.randint(2, 5), "confidence": round(rng.uniform(0.2, 0.6), 2)}
        if key == "qty":
            line["qty"] = blur
        else:
            slip[key] = blur
    elif kind == "missing_signature":
        slip["signature"] = False
    elif kind == "plausible_wrong_qty":
        # Off by one in whichever direction stays plausible; it must always differ from the truth.
        part = ref.parts[truth]
        q = line["qty"]
        line["qty"] = q - 1 if q > 1 and q >= min(part.max_per_pull, part.on_hand) else q + 1
    elif kind == "wrong_part_number":
        line["part_number"] = _neighbour(ref.parts[truth], ref).part_number
    else:
        raise ValueError(f"Unknown error type {kind}")
    return slip, truth


@dataclass
class Detection:
    kind: str
    n: int
    flagged: int  # sent to a person at the counter (block or warning)
    auto_ok: int  # resolved by the checker itself, correctly (name-only matches)
    auto_wrong: int  # resolved by the checker itself, to the WRONG part
    missed: int  # passed as ready with the error still in it

    @property
    def caught(self) -> float:
        return (self.flagged + self.auto_ok) / self.n


def measure_detection(ref: Reference, n: int = 300, seed: int = 7) -> tuple[dict[str, Detection], float]:
    """Run the real validator over injected errors. Returns (per type, false-alarm rate)."""
    rng = random.Random(seed)
    results = {}
    for kind in ERROR_LABEL:
        flagged = auto_ok = auto_wrong = missed = 0
        for _ in range(n):
            slip, truth = inject(kind, _clean_slip(rng, ref), rng, ref)
            r = validate(slip, ref, TODAY)
            if r.status != "READY":
                flagged += 1
            elif kind == "name_only":
                if r.lines[0].part_number == truth:
                    auto_ok += 1
                else:
                    auto_wrong += 1
            else:
                missed += 1
        results[kind] = Detection(kind, n, flagged, auto_ok, auto_wrong, missed)
    clean = [validate(_clean_slip(rng, ref), ref, TODAY) for _ in range(n)]
    false_alarm = sum(r.status != "READY" for r in clean) / n
    return results, false_alarm


# ---------------------------------------------------------------- 2. model


def load_assumptions(path: Path = ASSUMPTIONS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def scenario_values(a: dict, which: str) -> dict[str, float]:
    """which: 'likely', or 'pessimistic' / 'optimistic' (every input at its worse / better end)."""
    out = {}
    for key, worse in WORSE.items():
        if which == "likely":
            out[key] = a[key]["likely"]
        else:
            better = "low" if worse == "high" else "high"
            out[key] = a[key][worse if which == "pessimistic" else better]
    return out


def model(v: dict[str, float], mix: dict[str, float], det: dict[str, Detection], false_alarm: float) -> dict:
    M, S, s = v["mismatches_per_week"], v["slips_per_week"], v["slip_caused_share"]
    mpm, mpf, sec = v["minutes_per_mismatch"], v["minutes_per_flag"], v["seconds_added_per_slip"]
    weeks = v["weeks_per_year"]

    d_flag = sum(mix[k] * det[k].flagged / det[k].n for k in mix)
    d_auto = sum(mix[k] * det[k].auto_ok / det[k].n for k in mix)
    d = d_flag + d_auto

    slip_errors = M * s  # each slip error surfaces as one count mismatch in the manual process
    avoided = slip_errors * d
    flags = slip_errors * d_flag + max(S - slip_errors, 0) * false_alarm

    manual_h = M * mpm / 60
    checked_h = (M - avoided) * mpm / 60 + flags * mpf / 60 + S * sec / 3600
    net_h = manual_h - checked_h

    # Break-even share s*: net hours are linear in s, so solve net(s*) = 0.
    fixed = S * false_alarm * mpf / 60 + S * sec / 3600
    slope = M * (d * mpm - d_flag * mpf + false_alarm * mpf) / 60
    break_even = fixed / slope if slope > 0 else None

    return {
        "detection_weighted": d,
        "mismatches_per_week": {"manual": M, "checked": M - avoided},
        "hours_per_week": {"manual": manual_h, "checked": checked_h, "saved": net_h},
        "hours_per_year_saved": net_h * weeks,
        "dollars_per_year_saved": net_h * weeks * v["clerk_hourly_cost"],
        "flags_per_week": flags,
        "audit_variances_per_year": {"manual": M * v["unresolved_share"] * weeks,
                                     "checked": (M - avoided) * v["unresolved_share"] * weeks},
        "corrections_logged_per_year": avoided * weeks,
        "break_even_slip_share": break_even,
    }


SHARE_KEYS = {"slip_caused_share", "unresolved_share"}


def clean_overrides(overrides: dict | None) -> dict[str, float]:
    """Keep only known inputs, as numbers in a sane range (shares 0-1, the rest >= 0)."""
    out = {}
    for key, value in (overrides or {}).items():
        if key not in WORSE or isinstance(value, bool):
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        out[key] = min(max(v, 0.0), 1.0) if key in SHARE_KEYS else max(v, 0.0)
    return out


def impact(ref: Reference, n: int = 300, seed: int = 7, assumptions: dict | None = None,
           overrides: dict | None = None, detection: tuple | None = None) -> dict:
    """overrides replace the 'likely' value of any input (the UI's sliders). The pessimistic
    and optimistic scenarios always use the file's ranges, so they stay a fixed frame."""
    a = assumptions or load_assumptions()
    det, false_alarm = detection or measure_detection(ref, n, seed)
    mix = a["error_mix"]["shares"]
    likely = scenario_values(a, "likely") | clean_overrides(overrides)
    return {
        "detection": {k: vars(d) | {"caught": d.caught, "label": ERROR_LABEL[k]} for k, d in det.items()},
        "false_alarm_rate": false_alarm,
        "scenarios": {"pessimistic": model(scenario_values(a, "pessimistic"), mix, det, false_alarm),
                      "likely": model(likely, mix, det, false_alarm),
                      "optimistic": model(scenario_values(a, "optimistic"), mix, det, false_alarm)},
        "likely_inputs": likely,
        "assumptions": a,
        "settings": {"n_per_type": n, "seed": seed},
    }
