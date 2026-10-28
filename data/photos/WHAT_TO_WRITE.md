# Sample slip photos

All photos here are of **synthetic** slips: print `forms/checkout_slip.html`, fill it in
by hand with the content below, and photograph it (phone camera is fine, JPG or PNG).
No real storeroom slips or work orders are used.

The file name matters: mock mode looks up `data/extractions/<photo name without extension>.json`.

## slip_clean.jpeg (representative case)

| Field | Write |
|---|---|
| W/O # | WO-26-0412 |
| Date | 10/22/26 |
| Taken by | J. Rivera |
| Location | Harlow Hall |
| Line 1 | PL-1001, 3/4 PVC elbow, 6, ea |
| Line 2 | PL-1010, 3/4 ball valve, 2, ea |
| Signature | sign it |

Expected: `READY`.

## slip_hard_case.jpeg (difficult input)

| Field | Write |
|---|---|
| W/O # | 26-0390 (closed W/O, no "WO-" prefix) |
| Date | 10/26/26 |
| Taken by | A. Okafor, **written messily on purpose** |
| Location | Pierce Lib |
| Line 1 | *(no part #)*, duplex outlet, 4, *(no unit)* |
| Line 2 | GN-4010, hinges, 2, *(no unit)* |
| Signature | sign it |

Expected: `BLOCKED` with CLOSED_WO (suggest WO-26-0415), PART_AMBIGUOUS (20A vs 15A),
UNIT_AMBIGUOUS (2 PR or 1 PR), and HUMAN_REVIEW on whatever the model could not read.

## Refreshing the cached extractions

The JSON files in `data/extractions/` are **real Claude Haiku readings** of the two photos
here, saved on 2026-10-28 (`_provenance.kind` is `live model output`). To read the photos
again, or after replacing them:

```
python -m slipcheck check data/photos/slip_clean.jpeg --live --save-extraction
python -m slipcheck check data/photos/slip_hard_case.jpeg --live --save-extraction
```

Two Haiku calls, well under a cent total. From then on, mock mode replays real output.
