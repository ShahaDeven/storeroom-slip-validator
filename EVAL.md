# Evaluation: does photo reading plus rule checks hold up on handwriting?

**Exploratory, small sample.** 30 handwritten storeroom slips, one writer in four deliberate
styles, read by Claude Haiku. The question isn't "how accurate is the model?" but "when the model
misreads a field, does the system notice before a wrong entry is posted?"

## Headline

The held-out set was run once, after the freeze. Two photos turned out to have been saved under
each other's names (H02/H03, verified by eye, [below](#the-correction-and-what-it-taught)). Both
results are shown, always together: the **locked** run is the recorded result; the **corrected**
column re-scores the same cached readings with that one data-handling fix.

| Held-out, 20 slips | Locked (recorded) | Corrected (photo swap fixed) |
|---|---|---|
| **Slips where a wrong critical value would be posted** | **2/20** (3–30%) | **0/20** (0–16%) |
| Slips where any wrong stored value would be posted (dates, names, places included) | 11/20 | 10/20 (30–70%) |
| Slips that needed a person to confirm at least one field | 15/20 (75%) | 15/20 (75%) |
| Critical fields read correctly | 127/150 (85%) | 140/149 (94%) |

"Would be posted" means the wrong value is not stopped: no review request, no block on that field.
A **warning is not a stop**: it is shown, and the slip still posts. The count assumes the clerk
settles every stop correctly from the paper and clicks past warnings. Critical fields are W/O,
signature, part number, quantity, unit, and the description when there is no part number.

What this shows, and what it doesn't:
- **Uncertain reads did not post silently.** Posting refuses any slip with a blocking issue, and a
  read below 0.75 confidence is a block (`HUMAN_REVIEW`). That part is a property of the code,
  not of this sample.
- **Confident misreads can post.** Six held-out fields were read wrong at 0.90 confidence or above
  ("flapper" as "hopper", "Knox Hall" as "Knox mall"). When no rule contradicts such a read, nothing
  stops it. In this sample none of them was a critical field that got through; the
  [adversarial suite](README.md#adversarial-suite) shows the same failure on a quantity (cases A7
  and S2), where it would matter.
- **Half the slips would still post a wrong minor value**: six names (three of them only spacing
  or punctuation, like "h.santos"), two dates that lost a digit, two locations.
- **The cost is review load, and it is high.** 75% of held-out slips needed a person. This is
  not a time-saving result; workflow time has [not been measured](#not-measured-yet).
- **One writer.** Four deliberate styles by one person is not handwriting variation across people.
  See [what was and wasn't tested](#what-was-tested-and-what-wasnt).

An earlier version of this file led with "0 of 20 critical misreads went unnoticed". That number
counted a warning as "caught". It is still in the results table below, as "noticed", next to the
stricter "stopped" count.

## How it was tested

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
| Noticed (was "caught") | the reading's report carries a flag on that field that the true transcription's report doesn't (a rule, **block or warning**), or a low-confidence review request, or an existing block that makes a person choose that field's value anyway |
| Stopped | noticed by something that blocks posting: a review request, a new block on that field, or an existing block on it. A warning alone is not a stop |
| Stored | written into the posted entry: every critical field, plus date, taken-by and location. A description next to a part number is not stored; the entry carries the catalog name |
| Would be posted | a wrong stored field that is not stopped. Assumes the clerk settles every stop correctly and posts past warnings |
| Not noticed (slip) | the slip has at least one wrong critical field that is not noticed |
| Unnecessary review | a correctly read field sent to review |

Intervals are 95% Wilson intervals. **Fields within one slip are not independent**, so field-level
intervals are optimistic; the slip-level ones are the honest ones.

## Results

| | Development (10) | Held-out, locked (20) | Held-out, corrected (20) |
|---|---|---|---|
| All fields correct | 107/116 (92%) | 190/243 (78%) | 210/242 (87%) |
| Critical fields correct | 66/71 (93%) | 127/150 (85%) | 140/149 (94%) |
| **Slips where a wrong critical value would be posted** | **1/10 (2–40%)** | **2/20 (3–30%)** | **0/20 (0–16%)** |
| Slips where any wrong stored value would be posted | 2/10 | 11/20 | 10/20 |
| Slips with a critical misread not noticed (looser: warnings count) | 0/10 (0–28%) | 2/20 | 0/20 (0–16%) |
| Wrong fields stopped before posting | 6/9 | 22/53 (42%) | 19/32 (59%) |
| Wrong fields noticed (review, rule, block or warning) | 7/9 | 26/53 (49%) | 22/32 (69%) |
| Wrong fields that were only warned about | 1 | 4 | 3 |
| Minor misreads not flagged (fields) | 2 | 17 | 10 |
| Slips needing review | 5/10 (50%) | 15/20 (75%) | 15/20 (75%) |
| Correct fields sent to review | 1/107 (1%) | 11/190 (6%) | 12/210 (6%) |

**The locked held-out numbers are the recorded result** (`results_heldout.json`, unchanged). The
corrected column applies one data-handling fix, described below, using the same cached readings,
rules and thresholds (`python -m slipcheck eval --split heldout --corrected`).

The "would be posted", "stopped" and "only warned" rows were added after the held-out run, when
the adversarial suite showed that a warning does not stop posting. They come from re-scoring the
same cached readings with the same frozen rules (`--rescore`); no reading, rule, threshold or label
changed, and the re-score reproduces every number the locked run recorded (checked in code). The
development set's one posted critical value is D08: WO-26-0412 read as WO-26-0462, another crew's
real work order, which only raised warnings.

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

| Style | Fields correct | Critical misreads not noticed |
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
for field, and they account for **all 10** unnoticed critical misreads. Recorded in
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

1. **A wrong critical value would have been posted on 1 of 10 development slips, 2 of 20 locked
   held-out slips and 0 of 20 corrected held-out slips.** The upper bounds (40%, 30%, 16%) are wide;
   this is evidence, not proof. The development case was a W/O misread that only raised warnings,
   the failure the adversarial suite pins as S3.
2. **Rules notice what confidence misses.** Seven held-out misreads were noticed only by rules, for example
   `hv-8040` and `gw-4050`, part numbers that don't exist, and a work-order number read without its dash.
3. **Unflagged minor misreads are mostly dates and names.** Two dates lost a digit (`10/14` read as
   `10/4`, `10/18` as `10/8`) at 0.80–0.85. Dates are not "critical" by the definition above, but a
   wrong date matters for an audit trail. Making dates critical is the first change worth testing, on
   new development data.
4. **Harder handwriting means more review.** 75% of held-out slips needed review, against 50% in
   development. The time-saving estimate in the app assumes far fewer review requests, so it is
   optimistic.

## What was tested, and what wasn't

| Dimension | Tested here | Not tested | How it would be measured |
|---|---|---|---|
| Writers | 1 person, 4 deliberate styles | variation across people: letter shapes, spacing, abbreviations, habits | 2–3 other writers, about 10 slips each, as a new held-out set run once |
| Slip layout | 1 form on ruled paper | other storerooms' forms, carbon copies | photos of real slips from another site |
| Image quality | phone photos: clear, dim light, angled | blur, glare, crumpled carbons, flatbed scans | condition labels on the new set, accuracy reported per condition |
| Document types | handwritten slips (evaluated); receipts only through rules and the adversarial suite | receipt reading accuracy: 12 text-layer PDFs and 1 image, no labelled set | a labelled set of photographed and scanned receipts |
| Suppliers | 3 invented vendors | real vendor names, receipt formats, PO numbering | receipts from 3 or more real suppliers |
| Catalog | 60 synthetic parts, clean | duplicates, retired parts, inconsistent units in a real catalog | run against an exported real catalog |
| Model | Claude Haiku, one prompt, one read per photo | other models, prompt variants, read-to-read variance | read every held-out photo three times |
| Labels | written from the generator, checked by the writer | a second labeller (one label error was found afterwards) | a second person labels the new set blind |
| Sample | 10 development + 20 held-out slips | anything like production volume | each new set at least 30 slips |

Slip content is synthetic (parts, work orders and names come from the sample data), written by
hand on real paper.

## What the architecture guarantees, and what it doesn't

| | Guaranteed by the code | Not guaranteed |
|---|---|---|
| Low-confidence read | becomes a block (`HUMAN_REVIEW`); posting refuses a slip or receipt with any block (`ledger.post`, `receiving/store.post`) | that the person checking reads the paper correctly |
| Read that a rule contradicts | blocked or warned, with the reason shown next to the field | that a clerk does not click past a warning (warnings post) |
| Confident read that no rule contradicts | nothing | caught at all: 6 held-out fields at 0.90+ were wrong; adversarial cases A7 and S2 |
| Same slip or receipt posted twice | refused (same content, or same receipt number) | a re-keyed receipt with a different date |

Closing the third row needs a second source for the value (a packing list, an advance ship notice,
a count at put-away), not a better threshold. The second row is a rules decision: making W/O
cross-checks block instead of warn is the first change worth testing, on new development data.

## Not measured yet

| Metric | Status |
|---|---|
| Errors that reach an approved transaction | **measured here** for handwritten slips (the "would be posted" rows), under the stated assumption about the clerk; not measured in a real workflow, which needs posted entries compared against the paper |
| Slips that need review | **measured here**: 75% held-out, 50% development |
| Time to process a slip by hand | not measured |
| Time to process a slip with Slip Check | not measured |
| Time per human review | not measured |

Until the three timing rows are measured, nothing here supports a time-saving claim; the Impact
section is a model with stated assumptions. The smallest useful measurement is a timing pilot: the same
20 slips entered by hand and through Slip Check, timing each slip and each review, by at least two
clerks.

## Reproduce

```bash
python -m slipcheck eval --split dev                      # development, cached readings, no API calls
python -m slipcheck eval --sweep                          # review-threshold sweep, development only
python -m slipcheck eval --split heldout --corrected      # held-out with the recorded correction, no API calls
python -m slipcheck eval --split heldout --rescore        # the locked run re-scored: adds the stricter rows, no API calls
```

Cached readings are in `data/eval/readings/` (live Claude Haiku output with token counts). The
evaluation used 28 live reads in total: 8 development and 20 held-out (37,930 input and 20,796
output tokens for the held-out run).
