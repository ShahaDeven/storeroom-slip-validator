"""CLI.

  python -m slipcheck check data/slips/10_hard_case.json
  python -m slipcheck check data/photos/slip_hard_case.jpeg           # mock extraction
  python -m slipcheck check data/photos/slip_hard_case.jpeg --live --save-extraction
  python -m slipcheck demo                                            # every sample, one line each
  python -m slipcheck serve                                           # web UI at http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from slipcheck.extract import ExtractionError, extract
from slipcheck.reference import DATA_DIR, load_reference
from slipcheck.render import render
from slipcheck.validate import InvalidSlip, validate

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def load_slip(path: Path, live: bool, save: bool) -> dict:
    if path.suffix.lower() in IMAGE_SUFFIXES:
        return extract(path, live=live, save=save)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InvalidSlip(f"File not found: {path}")
    except json.JSONDecodeError as e:
        raise InvalidSlip(f"{path.name} is not valid JSON ({e.msg} at line {e.lineno}).")


def cmd_check(args: argparse.Namespace) -> int:
    ref = load_reference()
    try:
        slip = load_slip(Path(args.slip), args.live, args.save_extraction)
        report = validate(slip, ref)
    except (InvalidSlip, ExtractionError) as e:
        print(f"Rejected: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(render(report, args.slip))
    return 0


def cmd_demo(_: argparse.Namespace) -> int:
    ref = load_reference()
    paths = sorted((DATA_DIR / "slips").glob("*.json")) + sorted(
        p for p in (DATA_DIR / "photos").iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    for path in paths:
        try:
            report = validate(load_slip(path, live=False, save=False), ref)
            codes = ", ".join(sorted({i.code for i in report.issues if i.severity != "info"})) or "-"
            print(f"{path.name:<32} {report.status:<20} {codes}")
        except (InvalidSlip, ExtractionError) as e:
            print(f"{path.name:<32} {'REJECTED':<20} {e}")
    return 0


def cmd_impact(args: argparse.Namespace) -> int:
    from slipcheck.impact import impact

    r = impact(load_reference(), n=args.n, seed=args.seed)
    if args.json:
        print(json.dumps(r, indent=2, default=str))
        return 0
    a, sc = r["assumptions"], r["scenarios"]

    print("MODELED, NOT MEASURED. Synthetic slips; storeroom numbers from data/impact_assumptions.json.\n")
    print(f"1. Detection: the real validator run on {args.n} injected slips per error type (seed {args.seed})")
    for d in r["detection"].values():
        auto = f", {d['auto_ok']} resolved automatically" if d["auto_ok"] else ""
        wrong = f", {d['auto_wrong']} auto-resolved WRONG" if d["auto_wrong"] else ""
        print(f"   {d['label']:<50} caught {d['caught']:>4.0%}  ({d['flagged']} flagged{auto}{wrong}, {d['missed']} missed)")
    print(f"   False alarms on clean slips: {r['false_alarm_rate']:.1%}")
    print(f"   Weighted by the assumed error mix: {sc['likely']['detection_weighted']:.0%} of slip errors caught\n")

    print("2. Inputs")
    for key in ("slips_per_week", "mismatches_per_week", "minutes_per_mismatch", "slip_caused_share",
                "minutes_per_flag", "seconds_added_per_slip", "unresolved_share", "clerk_hourly_cost"):
        v = a[key]
        print(f"   {key:<24} {v['low']:>6} / {v['likely']:<6} / {v['high']:<6} [{v['source']}]")
    for key, v in a["excluded"].items():
        print(f"   {key:<24} excluded [{v['source']}]")
    print()

    def row(label, fn, fmt):
        print(f"   {label:<40}" + "".join(f"{fmt(fn(sc[w])):>14}" for w in ("pessimistic", "likely", "optimistic")))

    print("3. Result" + " " * 33 + f"{'pessimistic':>14}{'likely':>14}{'optimistic':>14}")
    row("Count mismatches / week, manual", lambda s: s["mismatches_per_week"]["manual"], lambda x: f"{x:.1f}")
    row("Count mismatches / week, with check", lambda s: s["mismatches_per_week"]["checked"], lambda x: f"{x:.1f}")
    row("Staff hours / week, manual", lambda s: s["hours_per_week"]["manual"], lambda x: f"{x:.1f}")
    row("Staff hours / week, with check", lambda s: s["hours_per_week"]["checked"], lambda x: f"{x:.1f}")
    row("Hours saved / year", lambda s: s["hours_per_year_saved"], lambda x: f"{x:+.0f}")
    row("Staff cost saved / year (USD)", lambda s: s["dollars_per_year_saved"], lambda x: f"{x:+,.0f}")
    row("Yearly-audit variances, manual", lambda s: s["audit_variances_per_year"]["manual"], lambda x: f"{x:.0f}")
    row("Yearly-audit variances, with check", lambda s: s["audit_variances_per_year"]["checked"], lambda x: f"{x:.0f}")
    row("Corrections logged with a reason / year", lambda s: s["corrections_logged_per_year"], lambda x: f"{x:.0f}")
    row("Break-even: slip-caused share needed", lambda s: s["break_even_slip_share"],
        lambda x: "n/a" if x is None else f"{x:.0%}")
    print("\n   Pessimistic takes every input at its worst end at once, so it is a floor, not a forecast.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    print(f"Slip check: http://127.0.0.1:{args.port}")
    uvicorn.run("slipcheck.api:app", host="127.0.0.1", port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="slipcheck", description="Validate a storeroom checkout slip at entry time.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate one slip (.json, or a photo)")
    c.add_argument("slip")
    c.add_argument("--live", action="store_true", help="read photos with the vision model (needs ANTHROPIC_API_KEY)")
    c.add_argument("--save-extraction", action="store_true", help="with --live, cache the extraction for mock mode")
    c.add_argument("--json", action="store_true", help="print the report as JSON")
    c.set_defaults(fn=cmd_check)
    sub.add_parser("demo", help="run every sample slip and photo").set_defaults(fn=cmd_demo)
    i = sub.add_parser("impact", help="modeled hours/cost saved vs the manual process")
    i.add_argument("--n", type=int, default=300, help="injected slips per error type")
    i.add_argument("--seed", type=int, default=7)
    i.add_argument("--json", action="store_true")
    i.set_defaults(fn=cmd_impact)
    s = sub.add_parser("serve", help="start the web UI and API")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
