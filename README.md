# storeroom-slip-validator

Catch storeroom checkout-slip errors **when the slip is entered**, not days later at count time.

In a facilities storeroom, crews take parts against a handwritten slip: W/O number, date,
who took it, location, items, signature. Every error on that slip (a closed W/O number, a "2"
written for a part tracked in pairs, a part name with no number, illegible handwriting) is
created at the counter but only discovered at the next physical count. By then the crew has
moved on and the trail is cold.

This prototype takes one slip (a photo, or the typed transcription a clerk would key in)
and returns a **clean entry ready to post** plus **the questions to ask the crew right now**,
while they can still be reached in minutes.

```
photo ──► vision extraction (AI, optional) ──┐
                                             ├──► slip JSON ──► deterministic validator ──► clean entry
typed slip (clerk transcription) ────────────┘    (one schema)   (rules, no AI)             + issues
                                                                                             + "call the crew and ask..."
                       low-confidence reads ──► HUMAN_REVIEW (never guessed)
```

**Where AI is used, and where it isn't:** AI only *reads* the handwriting, and it is told to
transcribe, not interpret. Every decision (does this W/O exist, is it open, which unit, is
this quantity plausible) is plain code against the catalog and the work-order list, so it
is repeatable, testable, and explainable to a storeroom supervisor.

---

## Setup

Python 3.10+. Node is **not** required to run it: the built web UI is committed in `frontend/dist/`.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

| Package | Needed for |
|---|---|
| `rapidfuzz` | core fuzzy matching (offline) |
| `fastapi`, `uvicorn`, `python-multipart` | API and web UI server |
| `anthropic`, `pillow` | **live** photo extraction only (optional): API client, and straightening/shrinking phone photos |
| `python-dotenv` | optional: reads `ANTHROPIC_API_KEY` from a `.env` file in the project folder |
| `pytest`, `httpx` | tests |

**No API key or paid service is needed.** Photo extraction defaults to **mock mode**, which
replays cached extractions from `data/extractions/`. Live mode is opt-in (see below).

After changing Python code, restart `serve`: the server loads code once, at start. The page
says so if it is newer than the running server.

## Run

Web UI:

```bash
python -m slipcheck serve          # open http://127.0.0.1:8000
```

Pick a slip on the left. The slip is drawn as the paper copy, with problems marked in red
next to the field they are about and a HOLD / READY TO POST stamp. On the right are the
questions to ask the crew, each with one-click answers. Answering re-checks the slip; the
corrected values appear in green over the struck-through original. You can also drop in
your own photo or JSON slip.

Demo path for the hard case: open **Hard case: four problems**, pick *WO-26-0415*, pick a
receptacle, pick *1 PR*, type the name into the review box. The stamp turns to READY TO POST.

**Posting and the shift log (mocked inventory).** "Post to inventory" re-checks the slip on
the server, refuses anything still blocked or already posted (same W/O, person, date and
parts), saves the entry, and lowers on-hand, so a later slip for the same part is checked
against the reduced stock. The **Shift log** tab shows what was posted (W/O, location, parts,
aisles, and the answers given at the counter), what is on hold and why, how many slips wait
on a handwriting check, the problems caught before the count by type, and stock after
posting. The header tally keeps the main counts visible on the Counter tab. Postings live
in a local SQLite file (`data/runtime/ledger.db`, git-ignored; override with
`SLIPCHECK_DB`). Nothing leaves the machine. "Clear shift log" resets it.

**Data tab.** The catalog and work orders the checker reads, as the mocked inventory holds
them now: every part with start, posted and on-hand (low stock flagged), every work order
with what was issued against it this shift, and a feed of stock changes (entry, W/O, who, and
before → after per part). Rows changed by the latest posting are highlighted. The tab
refreshes every few seconds, so a posting from another window shows up too. Filter by
"moved this shift", "running low", open/closed, or search.

Command line:

```bash
python -m slipcheck demo                                   # every sample, one line each
python -m slipcheck check data/slips/01_clean.json         # representative case
python -m slipcheck check data/slips/10_hard_case.json     # difficult case
python -m slipcheck check data/slips/12_truncated.json     # invalid input -> rejected, exit 2
python -m slipcheck check data/slips/10_hard_case.json --json   # machine-readable report
python -m slipcheck impact                                 # modeled manual vs checked comparison
pytest                                                     # tests
```

Frontend development (only if changing the UI; Node 20+):

```bash
python -m slipcheck serve          # API on :8000
cd frontend && npm install && npm run dev     # UI on :5173, proxies /api to :8000
npm run build                      # rebuild frontend/dist, which the Python server serves
```

| Layer | Stack |
|---|---|
| UI | React 19, TypeScript, Vite 8, Tailwind CSS 4 (`frontend/`) |
| API | FastAPI (`slipcheck/api.py`): samples, validate, photo upload |
| Rules | plain Python (`slipcheck/validate.py`), shared with the CLI |
| Reading photos | Claude Haiku vision, or cached readings in mock mode (`slipcheck/extract.py`) |

Photos (after adding them, see `data/photos/WHAT_TO_WRITE.md`):

```bash
python -m slipcheck check data/photos/slip_hard_case.jpeg            # MOCK: cached extraction
python -m slipcheck check data/photos/slip_hard_case.jpeg --live     # LIVE: needs ANTHROPIC_API_KEY
python -m slipcheck check data/photos/slip_hard_case.jpeg --live --save-extraction   # refresh cache
```

Live mode uses Claude Haiku (`SLIPCHECK_MODEL` to override), about one call per slip,
well under a cent each.

**What happened on the real photos** (two handwritten slips on ruled paper, read by Claude Haiku):
- `slip_clean.jpeg` was read exactly and came out `READY`.
- `slip_hard_case.jpeg` came out `BLOCKED` with CLOSED_WO, PART_AMBIGUOUS and UNIT_AMBIGUOUS, as designed.
- The model misread "duplex outlet" as **"dupler outlet" at 0.80 confidence**, above the 0.75
  review threshold, so its own confidence did not flag the mistake. The rules still did: the
  misread name fuzzy-matched both duplex receptacles equally, so the crew is asked which one,
  and nothing wrong gets posted. This is why AI only reads and the rules decide.
- The name "A. OKafor" was read at 0.85, so no HUMAN_REVIEW this time. The sample JSON
  `10_hard_case.json` shows that path with a low-confidence read.

## Sample data (all synthetic)

| File | What it is |
|---|---|
| `data/catalog.csv` | 60 parts across plumbing, electrical, HVAC, carpentry, paint and custodial: part number, name, aliases, **unit of issue** (EA / PR / BX / RL) and pieces per unit, aisle, on-hand, typical max per pull |
| `data/work_orders.csv` | 30 work orders across 10 crews, open and closed, with crew, crew members, location, dates |
| `data/slips/*.json` | 20 slips as a clerk would transcribe them: clean pulls, one per failure mode, and a multi-line weekly pull |
| `data/extractions/*.json` | cached photo extractions for mock mode (each says where it came from in `_provenance`) |
| `data/photos/` | handwritten sample slips on paper, photographed (see `WHAT_TO_WRITE.md`) |
| `data/impact_assumptions.json` | inputs to the impact estimate, each tagged observed / assumed / unknown |
| `forms/checkout_slip.html` | printable blank slip (optional; a hand-drawn slip on ruled paper works too) |

Buildings, crews, names, part numbers and W/O numbers are invented.

## Examples: input → expected output

| Input | Status | Why |
|---|---|---|
| `01_clean.json` | `READY` | everything checks out |
| `02_closed_wo.json` | `BLOCKED` | CLOSED_WO, suggests WO-26-0412 (same crew + location) |
| `03_pairs_no_unit.json` | `BLOCKED` | UNIT_AMBIGUOUS: "2" hinges = 2 PR or 1 PR? |
| `04_pieces_converted.json` | `READY` | "4 pcs" gloves converted to 2 PR (info) |
| `05_name_only_clear.json` | `READY` | "wax ring", "flapper" auto-matched (score 100 vs next best < 50) |
| `06_name_only_ambiguous.json` | `BLOCKED` | PART_AMBIGUOUS: 20x20 vs 24x24 filter |
| `07_unsigned_big_pull.json` | `BLOCKED` | MISSING_SIGNATURE, UNUSUAL_QTY (30 tubes vs usual max 12) |
| `08_wo_typo.json` | `BLOCKED` | UNKNOWN_WO "26-0142", suggests WO-26-0412 (transposed digits, same crew) |
| `09_exceeds_on_hand.json` | `BLOCKED` | EXCEEDS_ON_HAND: 8 belts vs 6 in the system, so recount aisle C04 |
| `10_hard_case.json` | `BLOCKED` | **closed W/O + name-only part + ambiguous "2" + illegible name** |
| `11_invalid_input.json` | `BLOCKED` | blank W/O / name / signature, "a few" qty, junk line, all reported, no crash |
| `12_truncated.json` | `REJECTED` (exit 2) | not valid JSON |
| `13_custodial_restock.json` | `READY` | 4-line restock in boxes, rolls and each |
| `14_ear_plugs_in_pieces.json` | `READY` | "10 pcs" ear plugs converted to 5 PR |
| `15_not_on_crew.json` | `READY_WITH_WARNINGS` | NOT_ON_CREW: electrician from another crew on this W/O |
| `16_wrong_building.json` | `READY_WITH_WARNINGS` | LOCATION_MISMATCH: slip says Knox Hall, W/O is Alcott Residence |
| `17_name_contradicts_number.json` | `BLOCKED` | NAME_NUMBER_MISMATCH: "exit sign" written next to a breaker's number |
| `18_same_part_twice.json` | `READY_WITH_WARNINGS` | DUPLICATE_PART: drywall sheets on two lines |
| `19_dated_before_wo.json` | `READY_WITH_WARNINGS` | BEFORE_WO_OPENED |
| `20_weekly_plumbing_pull.json` | `BLOCKED` | 5 lines: two name-only lines auto-matched, "ball valve" ambiguous (3/4 vs 1/2), "3 pcs" gloves not whole pairs |

Representative case, `python -m slipcheck check data/slips/01_clean.json`:

```
Status: READY
W/O WO-26-0412 | crew Plumbing A | taken by J. Rivera | Harlow Hall | 2026-10-22

Entry to post:
  1. 6 EA           PL-1001 PVC Elbow 90 deg 3/4 in [aisle A03]
  2. 2 EA           PL-1010 Ball Valve 3/4 in Brass [aisle A04]

Nothing to ask the crew. Ready to post.
```

Difficult case, `python -m slipcheck check data/slips/10_hard_case.json`:

```
Status: BLOCKED
W/O WO-26-0390 | crew Electrical | taken by A. Okafor | Pierce Library | 2026-10-26

Entry to post:
  1. 4              UNRESOLVED PART
  2. ? (unresolved) GN-4010 Door Hinge 4.5 in Satin Nickel [aisle D02]

Issues:
  [BLOCK] CLOSED_WO            wo_number: WO-26-0390 was closed on 2026-09-29. Parts can't be recorded against it.
           -> Move to WO-26-0415 (OPEN, Electrical, Pierce Library)
  [BLOCK] HUMAN_REVIEW         taken_by: Low-confidence read 'A. Okaf?r' (confidence 0.62). Check against the paper slip; not guessed.
  [BLOCK] PART_AMBIGUOUS       line 1: Name only: 'duplex outlet' fits more than one catalog part.
           -> EL-2010 Duplex Receptacle 20A White [aisle B03] (match 100)
           -> EL-2011 Duplex Receptacle 15A White [aisle B03] (match 100)
           -> EL-2020 GFCI Receptacle 20A [aisle B03] (match 75)
  [BLOCK] UNIT_AMBIGUOUS       line 2: '2' with no unit, and GN-4010 is tracked in PR of 2. Did the crew take 2 PR (4 pieces) or 1 PR (2 pieces)?
           -> 2 PR
           -> 1 PR

Call A. Okafor (Electrical) now and ask:
  1. [wo_number] WO-26-0390 was closed on 2026-09-29. Parts can't be recorded against it.
     Suggested: Move to WO-26-0415 (OPEN, Electrical, Pierce Library)
  2. [line 1] Name only: 'duplex outlet' fits more than one catalog part.
     Options: EL-2010 Duplex Receptacle 20A White | EL-2011 Duplex Receptacle 15A White | EL-2020 GFCI Receptacle 20A
  3. [line 2] '2' with no unit, and GN-4010 is tracked in PR of 2. Did the crew take 2 PR (4 pieces) or 1 PR (2 pieces)?
     Options: 2 PR | 1 PR
```

## Is it worth it? Manual vs checked (modeled)

`python -m slipcheck impact` compares the manual process with the checker. **These are
modeled numbers, not measured savings.** The same comparison is on the **Impact (estimated)** tab in the web UI,
with a slider for every input (tagged Observed or Assumed), the break-even marked on the
slip-error slider, and a banner saying what was measured and what was estimated. Two parts are kept separate:

1. **Detection is measured by running the real validator.** Clean synthetic slips get
   one injected error each (the error types seen at the counter), 300 per type. The
   checker must catch them with its actual rules.
2. **The cost model** combines that detection rate with storeroom numbers from
   [data/impact_assumptions.json](data/impact_assumptions.json). Every input is tagged:

| Input | Value (low / likely / high) | Source |
|---|---|---|
| Slips per week | 50 / 85 / 150 (10-20 a normal day, 40-50 a very busy one) | **observed** |
| Count mismatches per week | 7 / 7.5 / 8 | **observed** |
| Minutes to chase one mismatch | 30 / 45 / 60 (crew busy, gets put on hold) | **observed** |
| Share of mismatches caused by a slip error | 20% / 50% / 80% | **assumed**: the key unknown |
| Mix of error types | see file | types **observed**, frequencies **assumed** |
| Minutes to answer a flag at the counter | 2 / 3 / 5 | assumed |
| Seconds the check adds to every slip | 0 / 10 / 20 | assumed |
| Mismatches never traced (left for the yearly audit) | 10% / 25% / 40% | assumed |
| Staff hourly cost (USD) | 22 / 28 / 35 | assumed |
| Who parts were charged to (crew or unit) | not used | **unknown**: decided by management and accounting; changes who pays, not how much |
| Receiving-document call-backs | not counted | **observed**, but about vendor receipts, which this does not touch |

Detection (real rules, seed 7):

| Error written on the slip | Caught |
|---|---|
| Old, closed W/O number | 100% |
| Pieces written for a pair-tracked part, no unit | 100% |
| Part name only | 100% (84% resolved automatically and correctly, 16% sent to a person, 0% wrong) |
| Field too unclear to read | 100% |
| Not signed | 100% |
| Neighbouring part number with the right name | 75% |
| Wrong but plausible quantity | 1%: nothing on the slip contradicts it |
| **Weighted by the assumed mix** | **78%** |

Result:

| | Pessimistic | Likely | Optimistic |
|---|---|---|---|
| Count mismatches / week (manual → checked) | 7.0 → 5.9 | 7.5 → 4.6 | 8.0 → 3.0 |
| Staff hours / week (manual → checked) | 3.5 → 3.9 | 5.6 → 3.8 | 8.0 → 3.2 |
| **Hours saved / year** | **-18** | **+91** | **+242** |
| Staff cost saved / year (USD) | -402 | +2,557 | +8,456 |
| Variances left for the yearly audit (manual → checked) | 35 → 30 | 94 → 57 | 160 → 61 |
| Corrections logged with a reason / year | 54 | 146 | 249 |
| **Break-even: share of mismatches that must be slip errors** | **36%** | **6%** | **0%** |

How to read it:
- **Pessimistic puts every input at its worst end at once**, so it is a floor, not a
  forecast. In that floor the checker costs slightly more than it saves, mostly from 20
  seconds of overhead on 150 slips a week. That is left in on purpose.
- **The claim worth making is the break-even:** in the likely case the checker pays off as
  long as about 6% or more of count mismatches start as a slip error. The one thing
  that would sink it is that almost all drift comes from somewhere else (parts taken with
  no slip, receiving errors, loss). A two-week shadow pilot measures exactly that.
- **The yearly audit's main question was why each variance happened.** Every correction
  made at the counter is logged with its cause, and **Download for accounting (CSV)** on the
  Shift log tab exports one row per posted part with the problems found at entry and how
  each was corrected.
- Limits of the model: the false-alarm rate on clean synthetic slips is 0%, which is too
  clean, since real slips abbreviate buildings and names. Each slip error is assumed to cause one
  count mismatch. Staff time only; no part prices or write-off value yet.

## Checks

| Code | Severity | Who answers |
|---|---|---|
| `CLOSED_WO`, `UNKNOWN_WO`, `MISSING_WO` | block | crew (an open W/O on the same crew + location is suggested) |
| `UNIT_AMBIGUOUS` | block | crew. A bare number on a pair/box part is **never** converted silently |
| `UNIT_REMAINDER` | block | crew ("3 pieces" of a pair-issued part) |
| `UNIT_CONVERTED`, `UNIT_ASSUMED` | info / warn | written unit converted; odd bare number read as pairs |
| `PART_AMBIGUOUS`, `NAME_NUMBER_MISMATCH`, `NO_PART` | block | crew |
| `NAME_MATCHED` | info | auto-match only if score ≥ 88 **and** ≥ 12 ahead of the runner-up |
| `UNKNOWN_PART`, `BAD_LINE` | block | storeroom desk |
| `EXCEEDS_ON_HAND` | block | desk: slip or count is already wrong, recount the aisle |
| `UNUSUAL_QTY`, `DUPLICATE_PART`, `LOCATION_MISMATCH`, `NOT_ON_CREW` | warn | |
| `MISSING_SIGNATURE`, `MISSING_TAKEN_BY`, `MISSING_QTY`, `BAD_QTY` | block | crew |
| `HUMAN_REVIEW` | block | desk: any field read with confidence < 0.75; illegible ≠ blank |
| `MISSING_DATE`, `BAD_DATE`, `FUTURE_DATE`, `BEFORE_WO_OPENED` | warn | |

Status is `BLOCKED` if anything blocks, else `READY_WITH_WARNINGS`, else `READY`.

## Implemented / mocked / deferred

| | |
|---|---|
| **Implemented** | slip schema shared by typed and photo input; all checks above; fuzzy part and W/O matching; unit-of-issue conversion; confidence-gated human review; one-click answers that re-check the slip; posting with duplicate protection and stock deduction; shift log (posted, on hold, read checks, problems caught, stock); Data tab (live stock and work orders, change feed); accounting CSV export with root cause per line; detection measurement on injected errors; web UI (React + FastAPI), CLI, JSON output; live vision extraction code path; tests |
| **Mocked** | catalog and work orders are CSVs standing in for the inventory / CMMS system; "Post to inventory" writes to a local SQLite file, not a real inventory system; photo extraction defaults to cached JSON. The two shipped caches are **real Claude Haiku readings** of handwritten slips (`data/photos/`), saved with `--live --save-extraction` on 2026-10-28; mock mode replays them, so no key is needed to see what the model actually read |
| **Estimated** | the hours and dollars on the Impact tab and from `slipcheck impact`: storeroom volumes are observed, most other inputs are assumed, only the detection rates are measured. Not a measured saving |
| **Deferred** | writing to a real inventory / CMMS; users and sign-in (the shift log is one shared log); notifying the crew (the prototype produces the questions, a person makes the call); learning crew-specific habits; multi-page slips; measuring self-reported confidence against real accuracy |

## Known limitations

- Model self-reported confidence is not calibrated. The review threshold (0.75) is a starting point to be tuned against a labeled set of real slips.
- Location matching handles prefixes ("Pierce Lib") but not arbitrary abbreviations ("Davis Sci Ctr" still warns).
- Offline OCR (e.g. Tesseract) was not used; it performs poorly on handwriting.

## Time, AI use, and prior work

**Time spent: about 4.5 hours in total, over the 4-hour guideline.** Split so the in-scope
work can be judged on its own:

| Within about the first 4 hours (the brief's prototype) | After, beyond the time limit |
|---|---|
| Rule-based validator with all checks, sample data, CLI, tests | Shift log and posting to the mocked inventory |
| Photo reading (live and mock), confidence-gated human review | Data tab |
| Web UI showing the slip with one-click answers | Impact estimate (CLI and tab) and accounting CSV |
| Representative and invalid-input cases | Larger dataset (60 parts, 30 W/Os, 20 slips) |

I went past the limit on the shift log and impact estimate because a claim that the check
saves time needed something to back it. Both are labeled as estimated where they estimate.

**AI use.** Built with Claude Code (Claude) as a pair programmer: scaffolding, most of the
code, the UI, and drafting this README. The problem, the storeroom facts and every observed
number come from my own work in the storeroom; the AI did not supply them. How I checked
its output:
- ran every sample slip and compared each report with the failure it was written to show;
- drove the web UI in a real browser (scripted with Playwright) through the full demo path and at
  phone width, reading screenshots;
- a test suite for every rule, the API, the shift log and the impact model;
- corrected it where its assumptions were wrong for my storeroom (for example, parts were not
  charged to crews, and receiving call-backs are not part of the savings).

**Prior work reused:** none; written for this case study.

## What I would investigate next

1. **How much stock drift comes from parts taken with no slip at all.** If that dominates, a slip validator can't fix it, and that is the result that would make me drop this direction.
2. **How soon slips are actually entered.** Catching errors "while the crew is reachable" assumes same-day entry; batch entry at week's end shrinks the benefit.
3. Error frequency by type on real slips, to decide which checks earn their place.
4. Extraction accuracy on 50+ real handwritten slips, and where to set the review threshold.
5. **The same check on the receiving side.** Scanned vendor documents were already reviewed
   within 1-2 days. Reading them automatically and matching them to the order and to what
   was put away is the same pattern (document → extraction → rule checks against the system).
