"""CLI.

  python -m slipcheck check data/slips/10_hard_case.json
  python -m slipcheck check data/photos/slip_hard_case.jpg           # mock extraction
  python -m slipcheck check data/photos/slip_hard_case.jpg --live --save-extraction
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
    s = sub.add_parser("serve", help="start the web UI and API")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
