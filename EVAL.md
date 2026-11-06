# Evaluation: does photo reading plus rule checks hold up on handwriting?

**Exploratory, small sample.** 30 handwritten storeroom slips, one writer in four deliberate
styles, read by Claude Haiku. The question isn't "how accurate is the model?" but "when the model
misreads a field, does the system notice before a wrong entry is posted?"

**Results on the 20 held-out slips, corrected for one verified photo-naming error:**
- **0 of 20 slips had a misread on a critical field that went unnoticed** (95% Wilson interval 0–16%).
  Every misread work order, part number, quantity, unit or signature was sent to review, flagged by
  a rule, or blocked.
- **The model's own confidence is not enough on its own.** Six fields read at 0.90 or above were wrong,
  including "flapper" read as "hopper" and "Knox Hall" as "Knox mall". This is why the AI only reads
  and plain rules decide.
- **The cost is review load.** 15 of 20 slips (75%) needed a person to confirm at least one field,
  and 6% of correctly read fields were sent to review anyway.

## What was tested

```
photo ──► Claude Haiku transcribes each field + a confidence ──► the real validator (rules) ──► report
                                                                       ▲
true transcription (labels.csv) ───────────────────────────────────────┘  (run again: the oracle)
```

For each slip the validator runs twice: on the true transcription and on the model's reading. A
wrong field matters only if the reading's report fails to show it. The code is `slipcheck/eval.py`.

## Data and protocol

| | Development | Held-out |
|---|---|---|
| Slips | 10 (D01–D08 plus the two earlier photos) | 20 (H01–H20) |
| Handwriting styles | A, B | A, B, **C, D** (C and D never seen in development) |
| Conditions | clear, crossed-out quantity, abbreviations, similar digits | plus compressed writing, dim light, angled photos, missing fields |
| Use | debugging; thresholds may be tuned here (`--sweep`) | run **once**, after the freeze |

- **One writer, four deliberate styles:** A normal, B fast and slanted, C small capitals, D
  non-dominant hand. This is not handwriting variety across people.
- Slip content is synthetic and generated from the parts catalog and work orders
  (`scripts/make_eval_sheet.py`). Each slip was checked to contain the problem it was meant to
  contain: closed work orders, pairs with no unit, name-only parts, unsigned slips and so on.
- The answer key (`data/eval/labels.csv`) records what the paper says, not what was meant. It was
  committed (`07f896d`) before the held-out set was run.
- Freeze: the review threshold stayed at its original 0.75. The development sweep gave no reason to
  move it, and 0.90 would have sent 8 of 10 slips to review. The code was committed (`86a55af`), and
  the held-out set was run once. The harness refuses a second run and refuses to run with
  uncommitted changes (`data/eval/.heldout_run.json`).

## Definitions

| Term | Meaning |
|---|---|
| Field correct | reading equals the paper after trimming, case and number normalisation; W/O numbers, dates and part numbers compare by meaning (a missing "WO-" prefix is not a misread). Fields blank on paper and read as blank are not counted. |
| Critical field | W/O number, signature, part number, quantity, unit, and the description when there is no part number |
| Caught | the reading's report carries a flag on that field that the true transcription's report doesn't (a rule), or a low-confidence review request, or an existing block that makes a person choose that field's value anyway |
| Not caught (slip) | the slip has at least one wrong critical field that is not caught |
| Unnecessary review | a correctly read field sent to review |

Intervals are 95% Wilson intervals. **Fields within one slip are not independent**, so field-level
intervals are optimistic; the slip-level ones are the honest ones.

## Results

| | Development (10) | Held-out, locked (20) | Held-out, corrected (20) |
|---|---|---|---|
| All fields correct | 107/116 (92%) | 190/243 (78%) | **210/242 (87%)** |
| Critical fields correct | 66/71 (93%) | 127/150 (85%) | **140/149 (94%)** |
| Slips with a critical misread **not caught** | 0/10 (0–28%) | 2/20 | **0/20 (0–16%)** |
| Wrong fields caught (review, rule, block) | 7/9 | 26/53 (49%) | 22/32 (69%) |
| Minor misreads not flagged (fields) | 2 | 17 | 10 |
| Slips needing review | 5/10 (50%) | 15/20 (75%) | 15/20 (75%) |
| Correct fields sent to review | 1/107 (1%) | 11/190 (6%) | 12/210 (6%) |

**The locked held-out numbers are the recorded result** (`results_heldout.json`, unchanged). The
corrected column applies one data-handling fix, described below, using the same cached readings,
rules and thresholds (`python -m slipcheck eval --split heldout --corrected`).

### Confidence against observed correctness

This is not calibration. The model reports its own confidence; this shows how often a field at that
confidence was actually right.

| Model's confidence | Development | Held-out, corrected |
|---|---|---|
| 0.5–0.7 | 1/2 | 1/6 (too few to read anything into) |
| 0.7–0.9 | 17/25 (68%) | 69/90 (77%) |
| 0.9–1.0 | **89/89 (100%)** | **140/146 (96%)** |

At 0.90 and above, development was perfect, but held-out wasn't. Below 0.90, roughly one field in
four was wrong. The 0.75 review threshold catches the low end, but not the 0.75–0.90 band, where
most of the unflagged minor misreads sit.

### By handwriting style (held-out, corrected)

| Style | Fields correct | Critical misreads not caught |
|---|---|---|
| A normal | 61/68 (90%) | 0 |
| B fast, slanted | 47/55 (85%) | 0 |
| C small capitals (unseen) | 49/55 (89%) | 0 |
| D non-dominant hand (unseen) | 53/64 (83%) | 0 |

Five slips per style: read this as direction, not measurement.

## The correction, and what it taught

**Photo swap.** `H02.jpeg` and `H03.jpeg` were saved under each other's names. Checked by eye after
the run: the photo filed as H02 shows WO-26-0481, S. Whitfield, gloves medium and black wire (the
H03 answer); the photo filed as H03 shows WO-26-0386, H. Santos, trash bags and a GFCI outlet (the
H02 answer). In the locked run, the "misreads" on these two slips are each other's answers, field
for field, and they account for **all 10** uncaught critical misreads. Recorded in
`data/eval/corrections.json`.

That mistake is also a real finding. **A photo filed against the wrong slip is a real-world failure:
a scan attached to the wrong record.** The rules caught four problems on the misfiled slips
(signature, work order, quantity, unit), but most fields passed, because each misfiled reading was
consistent with itself. Field-level checks can't tell that the whole document is the wrong one. A
document-identity check (a slip or receipt number that must match the record it is filed against)
would close that gap.

**One answer-key error, not corrected.** The H03 paper is unsigned; its row says signed. The model
read "unsigned" correctly, and the missing-signature rule flagged it. It is left in the answer key
and counted as a caught misread, so the corrected critical accuracy is 140/149; on the paper it is
141/149.

## Findings

1. **No critical misread went unnoticed** in development or corrected held-out (0/10 and 0/20). The
   upper bounds, 28% and 16%, are wide; this is evidence, not proof.
2. **Rules catch what confidence misses.** Seven held-out misreads were caught only by rules, for example
   `hv-8040` and `gw-4050`, part numbers that don't exist, and a work-order number read without its dash.
3. **Unflagged minor misreads are mostly dates and names.** Two dates lost a digit (`10/14` read as
   `10/4`, `10/18` as `10/8`) at 0.80–0.85. Dates are not "critical" by the definition above, but a
   wrong date matters for an audit trail. Making dates critical is the first change worth testing, on
   new development data.
4. **Harder handwriting means more review.** 75% of held-out slips needed review, against 50% in
   development. The time-saving estimate in the app assumes far fewer review requests, so it is
   optimistic.

## Limits

- One writer. Four styles by the same hand do not stand in for many people's handwriting.
- 30 slips. The intervals above are wide; nothing here is a production accuracy number.
- Synthetic content on real paper: parts, work orders and names come from the sample data.
- The answer key was written from the generator and checked against the paper by the writer, with
  one error found afterwards (above). There was no second labeller.
- One model (Claude Haiku), one prompt, read once per photo; no repeat reads to measure variance.

## Reproduce

```bash
python -m slipcheck eval --split dev                      # development, cached readings, no API calls
python -m slipcheck eval --sweep                          # review-threshold sweep, development only
python -m slipcheck eval --split heldout --corrected      # held-out with the recorded correction, no API calls
```

Cached readings are in `data/eval/readings/` (live Claude Haiku output with token counts). The
evaluation used 28 live reads in total: 8 development and 20 held-out (37,930 input and 20,796
output tokens for the held-out run).
