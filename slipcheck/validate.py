"""Deterministic slip validation. No AI in this module.

Input is a slip dict in one shared schema, whether it came from a clerk typing the
paper slip or from the photo extractor. Any field may be a plain value (typed input,
confidence 1.0) or {"value", "confidence", "raw"} (photo extraction).

Output is a Report: a clean entry ready to post plus the issues that must be
resolved *now*, while the crew that wrote the slip can still be reached.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from rapidfuzz import fuzz, process

from slipcheck.reference import Part, Reference, WorkOrder

REVIEW_THRESHOLD = 0.75  # below this, a read is sent to a person instead of trusted
NAME_AUTO_MATCH = 88  # fuzzy score needed to auto-resolve a name-only part...
NAME_AUTO_GAP = 12  # ...and how far ahead of the runner-up it must be

BLOCK, WARN, INFO = "block", "warn", "info"
CREW, DESK = "crew", "desk"  # who can answer: the crew that wrote it, or the clerk

PIECE_WORDS = {"ea", "each", "pc", "pcs", "piece", "pieces", "ct"}
UNIT_WORDS = {
    "pr": "PR", "pair": "PR", "pairs": "PR", "prs": "PR",
    "bx": "BX", "box": "BX", "boxes": "BX",
    "rl": "RL", "roll": "RL", "rolls": "RL",
}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12}
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y")


class InvalidSlip(ValueError):
    """The input is not a slip at all (wrong type, unreadable JSON, empty photo read)."""


@dataclass
class Field:
    value: Any
    confidence: float = 1.0
    raw: str | None = None

    @property
    def empty(self) -> bool:
        return self.value is None or (isinstance(self.value, str) and not self.value.strip())

    @property
    def unsure(self) -> bool:
        """Something is written but the reader could not read it confidently.
        A null value with low confidence means illegible, which is not the same as blank."""
        return self.confidence < REVIEW_THRESHOLD


# Which slip field a line-level issue is about, so a UI can pin it to that field.
CODE_KEY = {
    "UNKNOWN_PART": "part_number", "NAME_NUMBER_MISMATCH": "part_number", "NO_PART": "part_number",
    "PART_AMBIGUOUS": "part_name", "NAME_MATCHED": "part_name", "DUPLICATE_PART": "part_number",
    "MISSING_QTY": "qty", "BAD_QTY": "qty", "UNIT_MISMATCH": "unit", "UNIT_REMAINDER": "unit",
    "UNIT_CONVERTED": "unit", "UNIT_ASSUMED": "unit", "UNIT_AMBIGUOUS": "unit",
    "EXCEEDS_ON_HAND": "qty", "UNUSUAL_QTY": "qty",
}


@dataclass
class Issue:
    severity: str
    code: str
    where: str
    message: str
    ask: str = DESK
    suggestions: list[str] = field(default_factory=list)
    # One-click resolutions: {"label": ..., "set": {slip key: value}}; applied to the
    # header when line is None, else to items[line - 1].
    fixes: list[dict] = field(default_factory=list)
    line: int | None = None
    key: str | None = None

    def __post_init__(self):
        m = re.match(r"line (\d+)\s*(\w+)?", self.where)
        if m:
            self.line = int(m.group(1))
            self.key = self.key or m.group(2) or CODE_KEY.get(self.code)
        else:
            self.key = self.key or self.where


def _fix(label: str, **values: Any) -> dict:
    return {"label": label, "set": values}


def _wo_fix(wo: "WorkOrder") -> dict:
    return _fix(f"{wo.wo_number}, {wo.location}", wo_number=wo.wo_number)


def _part_fix(part: "Part") -> dict:
    return _fix(f"{part.part_number} {part.name}", part_number=part.part_number, part_name=part.name)


@dataclass
class Line:
    line: int
    part_number: str | None
    name: str | None
    aisle: str | None
    qty: float | None
    unit: str | None


@dataclass
class Report:
    status: str
    wo_number: str | None
    crew: str | None
    taken_by: str | None
    location: str | None
    slip_date: str | None
    lines: list[Line]
    issues: list[Issue]

    @property
    def blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == BLOCK]

    def to_dict(self) -> dict:
        return asdict(self)


def as_field(x: Any) -> Field:
    if isinstance(x, dict) and "value" in x:
        conf = x.get("confidence")
        return Field(x["value"], 1.0 if conf is None else float(conf), x.get("raw"))
    return Field(x)


def _norm(text: str) -> str:
    text = text.lower().replace('"', " in ").replace("°", " deg ")
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- work order


def normalize_wo(raw: Any, default_year: int) -> str | None:
    """'wo 26-412', '26/0412', '0412' -> 'WO-26-0412'. None if no number is present."""
    digits = re.findall(r"\d+", str(raw))
    if not digits:
        return None
    if len(digits) >= 2:
        year, num = digits[-2][-2:], digits[-1]
    else:
        year, num = f"{default_year % 100:02d}", digits[0]
    return f"WO-{year}-{int(num):04d}"


def _same_place(a: Any, b: str) -> bool:
    """Crews abbreviate building names ('Pierce Lib'), so allow a prefix-style match."""
    a, b = _norm(str(a)), _norm(b)
    return max(fuzz.token_set_ratio(a, b), fuzz.partial_ratio(a, b)) >= 85


def _is_member(person: str | None, wo: WorkOrder) -> bool:
    if not person:
        return False
    return any(fuzz.token_set_ratio(_norm(person), _norm(m)) >= 85 for m in wo.members)


def _wo_label(wo: WorkOrder) -> str:
    return f"{wo.wo_number} ({wo.status}, {wo.crew}, {wo.location})"


def _open_alternatives(ref: Reference, taken_by: str | None, location: str | None,
                       crew: str | None) -> list[WorkOrder]:
    """Open W/Os the parts most likely belong on: same location and crew first."""
    scored = []
    for wo in ref.work_orders.values():
        if not wo.is_open:
            continue
        same_loc = bool(location) and _same_place(location, wo.location)
        same_crew = _is_member(taken_by, wo) or (crew is not None and wo.crew == crew)
        score = 2 * same_loc + same_crew
        if score:
            scored.append((score, wo))
    scored.sort(key=lambda s: -s[0])
    return [wo for _, wo in scored[:3]]


def check_work_order(slip: dict, ref: Reference, today: date, issues: list[Issue]
                     ) -> tuple[WorkOrder | None, str | None]:
    f = as_field(slip.get("wo_number"))
    taken_by = as_field(slip.get("taken_by")).value
    location = as_field(slip.get("location")).value
    if f.empty and f.unsure:
        issues.append(_review("wo_number", f))
        return None, None
    if f.empty:
        alts = _open_alternatives(ref, taken_by, location, None)
        issues.append(Issue(BLOCK, "MISSING_WO", "wo_number", "No W/O number on the slip.",
                            CREW, [_wo_label(w) for w in alts], [_wo_fix(w) for w in alts]))
        return None, None
    if f.unsure:
        issues.append(_review("wo_number", f))

    wo_number = normalize_wo(f.value, today.year)
    wo = ref.work_orders.get(wo_number) if wo_number else None
    if wo is None:
        # Likely a transposed digit: look-alike numbers, but only ones that fit this
        # crew or location; otherwise fall back to the crew's open W/Os.
        fits = {w.wo_number for w in _open_alternatives(ref, taken_by, location, None)}
        close = [k for k, _, _ in process.extract(wo_number or str(f.value), list(ref.work_orders),
                                                  scorer=fuzz.ratio, limit=5, score_cutoff=75)
                 if k in fits]
        options = [ref.work_orders[k] for k in (close or sorted(fits))]
        issues.append(Issue(
            BLOCK, "UNKNOWN_WO", "wo_number",
            f"W/O '{f.value}' does not exist in the system.", CREW,
            [_wo_label(w) for w in options], [_wo_fix(w) for w in options]))
        return None, wo_number

    if not wo.is_open:
        alts = _open_alternatives(ref, taken_by, location or wo.location, wo.crew)
        issues.append(Issue(
            BLOCK, "CLOSED_WO", "wo_number",
            f"{wo.wo_number} was closed on {wo.closed}. Parts cannot be charged to it.",
            CREW, [f"Move to {_wo_label(w)}" for w in alts], [_wo_fix(w) for w in alts]))
    if location and not _same_place(location, wo.location):
        issues.append(Issue(WARN, "LOCATION_MISMATCH", "location",
                            f"Slip says '{location}' but {wo.wo_number} is at {wo.location}.", CREW,
                            fixes=[_fix(f"Use {wo.location}", location=wo.location)]))
    if taken_by and not _is_member(str(taken_by), wo):
        issues.append(Issue(WARN, "NOT_ON_CREW", "taken_by",
                            f"'{taken_by}' is not listed on {wo.crew} for {wo.wo_number} "
                            f"({', '.join(wo.members)}).", DESK))
    return wo, wo.wo_number


# ---------------------------------------------------------------- header fields


def parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def check_header(slip: dict, wo: WorkOrder | None, today: date, issues: list[Issue]) -> str | None:
    taken_by = as_field(slip.get("taken_by"))
    if taken_by.unsure:
        issues.append(_review("taken_by", taken_by))
    elif taken_by.empty:
        issues.append(Issue(BLOCK, "MISSING_TAKEN_BY", "taken_by",
                            "No name for who took the parts.", CREW))

    loc = as_field(slip.get("location"))
    if loc.unsure:
        issues.append(_review("location", loc))
    elif loc.empty:
        issues.append(Issue(INFO, "LOCATION_FROM_WO", "location",
                            f"No location written; using W/O location {wo.location}." if wo
                            else "No location written.", DESK))

    sig = as_field(slip.get("signature"))
    if sig.empty or sig.value is False:
        issues.append(Issue(BLOCK, "MISSING_SIGNATURE", "signature",
                            "Slip is not signed. Get a signature before the parts are posted.", CREW,
                            fixes=[_fix("Signed at the counter", signature=True)]))

    d = as_field(slip.get("date"))
    if d.empty and d.unsure:
        issues.append(_review("date", d))
        return None
    if d.empty:
        issues.append(Issue(WARN, "MISSING_DATE", "date",
                            f"No date on slip; recording entry date {today}.", DESK))
        return today.isoformat()
    if d.unsure:
        issues.append(_review("date", d))
    parsed = parse_date(d.value)
    if parsed is None:
        issues.append(Issue(WARN, "BAD_DATE", "date", f"Could not read date '{d.value}'.", DESK))
        return None
    if parsed > today:
        issues.append(Issue(WARN, "FUTURE_DATE", "date", f"Slip is dated {parsed}, after today.", DESK))
    if wo and parsed < wo.opened:
        issues.append(Issue(WARN, "BEFORE_WO_OPENED", "date",
                            f"Slip date {parsed} is before {wo.wo_number} was opened ({wo.opened}).", CREW))
    return parsed.isoformat()


# ---------------------------------------------------------------- items


def _part_choices(ref: Reference) -> dict[str, str]:
    """One searchable string per (part, name-or-alias) so aliases can win on their own."""
    return {f"{p.part_number}|{i}": _norm(text)
            for p in ref.parts.values()
            for i, text in enumerate((p.name, *p.aliases))}


def match_part_name(name: str, ref: Reference, limit: int = 3) -> list[tuple[Part, float]]:
    best: dict[str, float] = {}
    for _, score, key in process.extract(_norm(name), _part_choices(ref),
                                         scorer=fuzz.token_set_ratio, limit=None):
        pn = key.split("|")[0]
        best[pn] = max(best.get(pn, 0), score)
    ranked = sorted(best.items(), key=lambda kv: -kv[1])[:limit]
    return [(ref.parts[pn], score) for pn, score in ranked]


def _cand(part: Part, score: float) -> str:
    return f"{part.part_number} {part.name} [aisle {part.aisle}] (match {score:.0f})"


def resolve_part(item: dict, n: int, ref: Reference, issues: list[Issue]) -> Part | None:
    where = f"line {n}"
    pn_f, name_f = as_field(item.get("part_number")), as_field(item.get("part_name"))
    for label, f in (("part_number", pn_f), ("part_name", name_f)):
        if f.unsure:
            issues.append(_review(f"{where} {label}", f))

    if not pn_f.empty:
        pn = str(pn_f.value).strip().upper().replace(" ", "")
        part = ref.parts.get(pn)
        if part is None:
            close = process.extract(pn, list(ref.parts), scorer=fuzz.ratio, limit=3, score_cutoff=70)
            if name_f.empty:
                ranked = [(ref.parts[k], s) for k, s, _ in close]
            else:  # the written name is stronger evidence than a look-alike number
                near = {k for k, _, _ in close}
                ranked = sorted(match_part_name(str(name_f.value), ref),
                                key=lambda ps: (-ps[1], ps[0].part_number not in near))
            issues.append(Issue(BLOCK, "UNKNOWN_PART", where,
                                f"Part number '{pn_f.value}' is not in the catalog.", DESK,
                                [_cand(p, s) for p, s in ranked], [_part_fix(p) for p, _ in ranked]))
            return None
        if not name_f.empty:
            score = max(fuzz.token_set_ratio(_norm(str(name_f.value)), _norm(t))
                        for t in (part.name, *part.aliases))
            if score < 60:
                best = match_part_name(str(name_f.value), ref, limit=1)
                issues.append(Issue(
                    BLOCK, "NAME_NUMBER_MISMATCH", where,
                    f"'{name_f.value}' does not look like {part.part_number} ({part.name}). "
                    "Which one did the crew take?", CREW,
                    [_cand(part, score)] + [_cand(p, s) for p, s in best],
                    [_part_fix(part)] + [_part_fix(p) for p, _ in best if p is not part]))
        return part

    if name_f.empty:
        if not (pn_f.unsure or name_f.unsure):  # illegible is already queued for review
            issues.append(Issue(BLOCK, "NO_PART", where, "Line has no part number or name.", CREW))
        return None

    cands = match_part_name(str(name_f.value), ref)
    top_part, top = cands[0]
    runner_up = cands[1][1] if len(cands) > 1 else 0
    if top >= NAME_AUTO_MATCH and top - runner_up >= NAME_AUTO_GAP:
        issues.append(Issue(INFO, "NAME_MATCHED", where,
                            f"Name only: '{name_f.value}' matched to {top_part.part_number} "
                            f"{top_part.name} (match {top:.0f}, next best {runner_up:.0f}).", DESK))
        return top_part
    plausible = [(p, s) for p, s in cands if s >= 50]
    issues.append(Issue(BLOCK, "PART_AMBIGUOUS", where,
                        f"Name only: '{name_f.value}' fits more than one catalog part.", CREW,
                        [_cand(p, s) for p, s in plausible], [_part_fix(p) for p, _ in plausible]))
    return None


def parse_qty(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if text in NUMBER_WORDS:
        return float(NUMBER_WORDS[text])
    try:
        return float(text)
    except ValueError:
        return None


def check_qty(item: dict, n: int, part: Part | None, issues: list[Issue]
              ) -> tuple[float | None, str | None]:
    """Return (quantity in the catalog's unit of issue, that unit)."""
    where = f"line {n}"
    qf, uf = as_field(item.get("qty")), as_field(item.get("unit"))
    if qf.unsure:
        issues.append(_review(f"{where} qty", qf))
        if qf.empty:
            return None, None
    elif qf.empty:
        issues.append(Issue(BLOCK, "MISSING_QTY", where, "No quantity written.", CREW))
        return None, None
    qty = parse_qty(qf.value)
    if qty is None or qty <= 0 or qty != int(qty):
        issues.append(Issue(BLOCK, "BAD_QTY", where,
                            f"Quantity '{qf.value}' is not a whole positive number.", CREW))
        return None, None
    if part is None:
        return qty, None

    written = None if uf.empty else str(uf.value).strip().lower().rstrip(".")
    written_unit = "PIECE" if written in PIECE_WORDS else UNIT_WORDS.get(written or "")
    size = part.unit_size

    if size == 1:
        if written_unit in ("PR", "BX"):
            issues.append(Issue(WARN, "UNIT_MISMATCH", where,
                                f"Slip says {qty:g} {written}, but {part.part_number} is issued "
                                f"by {part.unit}. Recorded as {qty:g} {part.unit}.", CREW))
    elif written_unit == part.unit:
        pass
    elif written_unit == "PIECE":
        if qty % size:
            lo, hi = int(qty // size), int(qty // size) + 1
            issues.append(Issue(BLOCK, "UNIT_REMAINDER", where,
                                f"{qty:g} pieces of {part.part_number}, which is issued in "
                                f"{part.unit} of {size}. That is not a whole {part.unit}.", CREW,
                                [f"{n} {part.unit}" for n in (lo, hi) if n],
                                [_fix(f"{n} {part.unit} ({n * size} pieces)", qty=n, unit=part.unit)
                                 for n in (lo, hi) if n]))
            return None, part.unit
        converted = qty / size
        issues.append(Issue(INFO, "UNIT_CONVERTED", where,
                            f"{qty:g} pieces converted to {converted:g} {part.unit} "
                            f"({size} per {part.unit}).", DESK))
        qty = converted
    elif qty % size:
        # '3' hinges cannot be 1.5 pairs, so the only sensible reading is 3 PR.
        issues.append(Issue(WARN, "UNIT_ASSUMED", where,
                            f"No unit written; read as {qty:g} {part.unit} because {qty:g} "
                            f"pieces would not be a whole {part.unit}.", DESK))
    else:
        # Exactly the error seen at count time: never pick a reading, ask.
        issues.append(Issue(
            BLOCK, "UNIT_AMBIGUOUS", where,
            f"'{qty:g}' with no unit, and {part.part_number} is tracked in {part.unit} of {size}. "
            f"Did the crew take {qty:g} {part.unit} ({qty * size:g} pieces) or "
            f"{qty / size:g} {part.unit} ({qty:g} pieces)?", CREW,
            [f"{qty:g} {part.unit}", f"{qty / size:g} {part.unit}"],
            [_fix(f"{qty:g} {part.unit} ({qty * size:g} pieces)", qty=int(qty), unit=part.unit),
             _fix(f"{qty / size:g} {part.unit} ({qty:g} pieces)", qty=int(qty / size), unit=part.unit)]))
        return None, part.unit

    if qty > part.on_hand:
        issues.append(Issue(BLOCK, "EXCEEDS_ON_HAND", where,
                            f"{qty:g} {part.unit} exceeds the {part.on_hand} the system shows "
                            f"on hand. Either the slip or the count is wrong; recount aisle "
                            f"{part.aisle} before posting.", DESK))
    elif qty > part.max_per_pull:
        issues.append(Issue(WARN, "UNUSUAL_QTY", where,
                            f"{qty:g} {part.unit} is more than the usual max of "
                            f"{part.max_per_pull} per pull for {part.part_number}.", CREW))
    return qty, part.unit


# ---------------------------------------------------------------- entry point


def _review(where: str, f: Field) -> Issue:
    read = f.raw if f.raw is not None else f.value
    return Issue(BLOCK, "HUMAN_REVIEW", where,
                 f"Low-confidence read '{read}' (confidence {f.confidence:.2f}). "
                 "Check against the paper slip; not guessed.", DESK)


def validate(slip: Any, ref: Reference, today: date | None = None) -> Report:
    if not isinstance(slip, dict):
        raise InvalidSlip(f"Expected a slip object, got {type(slip).__name__}.")
    known = {"wo_number", "date", "taken_by", "location", "items", "signature"}
    if not known & slip.keys():
        raise InvalidSlip("Input has none of the slip fields "
                          f"({', '.join(sorted(known))}). Is this a checkout slip?")
    today = today or date.today()
    issues: list[Issue] = []

    wo, wo_number = check_work_order(slip, ref, today, issues)
    slip_date = check_header(slip, wo, today, issues)

    items = slip.get("items") or []
    if not isinstance(items, list) or not items:
        issues.append(Issue(BLOCK, "NO_ITEMS", "items", "No parts listed on the slip.", CREW))
        items = []

    lines: list[Line] = []
    seen: dict[str, int] = {}
    for n, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            issues.append(Issue(BLOCK, "BAD_LINE", f"line {n}", f"Unreadable line: {item!r}", DESK))
            continue
        part = resolve_part(item, n, ref, issues)
        qty, unit = check_qty(item, n, part, issues)
        if part is not None:
            if part.part_number in seen:
                issues.append(Issue(WARN, "DUPLICATE_PART", f"line {n}",
                                    f"{part.part_number} also appears on line {seen[part.part_number]}; "
                                    "combine or confirm both pulls.", DESK))
            seen.setdefault(part.part_number, n)
        lines.append(Line(n, part.part_number if part else None, part.name if part else None,
                          part.aisle if part else None, qty, unit))

    severities = {i.severity for i in issues}
    status = "BLOCKED" if BLOCK in severities else "READY_WITH_WARNINGS" if WARN in severities else "READY"
    location = as_field(slip.get("location")).value or (wo.location if wo else None)
    return Report(status, wo_number, wo.crew if wo else None, as_field(slip.get("taken_by")).value,
                  location, slip_date, lines, issues)
