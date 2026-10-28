"""Shift log: what was checked at the counter, what was posted, and the stock it moved.

MOCKED inventory system. Posting here writes to a local SQLite file
(data/runtime/ledger.db, or $SLIPCHECK_DB) and lowers on-hand for the rest of the
session; nothing leaves this machine. Reset it with the "Clear shift log" button or
POST /api/ledger/reset.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from slipcheck.reference import DATA_DIR, Reference
from slipcheck.validate import BLOCK, Report

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    name TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    first_codes TEXT NOT NULL,   -- JSON [[severity, code], ...] at the first check
    status TEXT NOT NULL,        -- latest status
    open_codes TEXT NOT NULL,    -- JSON [code, ...] still blocking at the latest check
    wo_number TEXT, taken_by TEXT, crew TEXT
);
CREATE TABLE IF NOT EXISTS postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    posted_at TEXT NOT NULL,
    wo_number TEXT, crew TEXT, taken_by TEXT, location TEXT, slip_date TEXT,
    lines TEXT NOT NULL,         -- JSON [{part_number, name, aisle, qty, unit}]
    answers TEXT NOT NULL        -- JSON [str]: what the clerk resolved at the counter
);
"""


class AlreadyPosted(Exception):
    def __init__(self, posting: dict):
        super().__init__(f"Already posted at {posting['posted_at']} as entry #{posting['id']}.")
        self.posting = posting


class NotPostable(Exception):
    pass


def db_path() -> Path:
    return Path(os.environ.get("SLIPCHECK_DB") or DATA_DIR / "runtime" / "ledger.db")


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def fingerprint(report: Report) -> str:
    """Same W/O, person, date and parts = same pull. Catches a slip keyed in twice."""
    lines = sorted((ln.part_number or "", ln.qty or 0, ln.unit or "") for ln in report.lines)
    key = json.dumps([report.wo_number, (report.taken_by or "").lower(), report.slip_date, lines])
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _posting(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["lines"] = json.loads(d["lines"])
    d["answers"] = json.loads(d["answers"])
    return d


def find_posting(report: Report) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM postings WHERE fingerprint = ?", (fingerprint(report),)).fetchone()
    return _posting(row) if row else None


def record_check(name: str, report: Report) -> None:
    """Remember the first problems found on a slip (what was caught) and its latest state."""
    now = _now()
    first = json.dumps(sorted({(i.severity, i.code) for i in report.issues if i.severity != "info"}))
    open_codes = json.dumps(sorted({i.code for i in report.issues if i.severity == BLOCK}))
    with closing(_connect()) as conn, conn:
        conn.execute(
            """INSERT INTO checks (name, first_seen, last_seen, first_codes, status, open_codes,
                                   wo_number, taken_by, crew)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET last_seen = excluded.last_seen,
                   status = excluded.status, open_codes = excluded.open_codes,
                   wo_number = excluded.wo_number, taken_by = excluded.taken_by, crew = excluded.crew""",
            (name, now, now, first, report.status, open_codes, report.wo_number,
             report.taken_by, report.crew),
        )


def post(name: str, report: Report, answers: list[str]) -> dict:
    if report.status == "BLOCKED":
        raise NotPostable(f"{len(report.blocking)} problem(s) still block this slip.")
    existing = find_posting(report)
    if existing:
        raise AlreadyPosted(existing)
    lines = [{"part_number": ln.part_number, "name": ln.name, "aisle": ln.aisle,
              "qty": ln.qty, "unit": ln.unit} for ln in report.lines]
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            """INSERT INTO postings (name, fingerprint, posted_at, wo_number, crew, taken_by,
                                     location, slip_date, lines, answers)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, fingerprint(report), _now(), report.wo_number, report.crew, report.taken_by,
             report.location, report.slip_date, json.dumps(lines), json.dumps(answers)),
        )
        row = conn.execute("SELECT * FROM postings WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _posting(row)


def posted_by_part() -> dict[str, float]:
    totals: dict[str, float] = {}
    with closing(_connect()) as conn:
        for (lines,) in conn.execute("SELECT lines FROM postings"):
            for ln in json.loads(lines):
                if ln["part_number"] and ln["qty"]:
                    totals[ln["part_number"]] = totals.get(ln["part_number"], 0) + ln["qty"]
    return totals


def with_posted_stock(ref: Reference) -> Reference:
    """The catalog as the mock inventory sees it now: on-hand minus everything posted."""
    taken = posted_by_part()
    if not taken:
        return ref
    parts = {pn: replace(p, on_hand=p.on_hand - int(taken.get(pn, 0))) for pn, p in ref.parts.items()}
    return Reference(parts=parts, work_orders=ref.work_orders)


def summary(ref: Reference) -> dict:
    with closing(_connect()) as conn:
        checks = [dict(r) for r in conn.execute("SELECT * FROM checks ORDER BY last_seen DESC")]
        postings = [_posting(r) for r in conn.execute("SELECT * FROM postings ORDER BY id DESC")]
    posted_names = {p["name"] for p in postings}

    caught: dict[str, dict] = {}
    for c in checks:
        for severity, code in json.loads(c["first_codes"]):
            entry = caught.setdefault(code, {"code": code, "severity": severity, "count": 0})
            entry["count"] += 1

    pending = []
    for c in checks:
        if c["name"] in posted_names:
            continue
        open_codes = json.loads(c["open_codes"])
        pending.append({"name": c["name"], "status": c["status"], "open_codes": open_codes,
                        "needs_review": "HUMAN_REVIEW" in open_codes, "wo_number": c["wo_number"],
                        "taken_by": c["taken_by"], "crew": c["crew"], "last_seen": c["last_seen"]})

    taken = posted_by_part()
    stock = []
    for pn, qty in sorted(taken.items()):
        p = ref.parts.get(pn)
        if p:
            now = p.on_hand - qty
            stock.append({"part_number": pn, "name": p.name, "aisle": p.aisle, "unit": p.unit,
                          "start": p.on_hand, "posted": qty, "on_hand": now,
                          "low": now <= p.max_per_pull})

    return {
        "counts": {
            "checked": len(checks),
            "posted": len(postings),
            "on_hold": sum(1 for p in pending if p["status"] == "BLOCKED"),
            "ready_unposted": sum(1 for p in pending if p["status"] != "BLOCKED"),
            "needs_review": sum(1 for p in pending if p["needs_review"]),
            "caught": sum(c["count"] for c in caught.values()),
            "resolved_at_counter": sum(len(p["answers"]) for p in postings),
        },
        "postings": postings,
        "pending": pending,
        "caught": sorted(caught.values(), key=lambda c: (-c["count"], c["code"])),
        "stock": stock,
    }


def data_view(ref: Reference) -> dict:
    """The reference data as the mock inventory holds it now, plus every stock change.

    Replays postings in order so each change carries its before and after on-hand.
    """
    with closing(_connect()) as conn:
        postings = [_posting(r) for r in conn.execute("SELECT * FROM postings ORDER BY id")]

    running = {pn: p.on_hand for pn, p in ref.parts.items()}
    last_change: dict[str, dict] = {}
    by_wo: dict[str, dict] = {}
    changes = []
    for post_ in postings:
        stamp = {"posting_id": post_["id"], "posted_at": post_["posted_at"]}
        for ln in post_["lines"]:
            pn, qty = ln["part_number"], ln["qty"] or 0
            if pn not in running:
                continue
            before = running[pn]
            running[pn] = before - qty
            changes.append(stamp | {"part_number": pn, "name": ln["name"], "unit": ln["unit"],
                                    "qty": qty, "before": before, "after": running[pn],
                                    "wo_number": post_["wo_number"], "taken_by": post_["taken_by"]})
            last_change[pn] = stamp | {"qty": qty}
        wo = by_wo.setdefault(post_["wo_number"], {"postings": 0, "lines": 0})
        wo["postings"] += 1
        wo["lines"] += len(post_["lines"])
        wo["last"] = stamp

    parts = [{"part_number": p.part_number, "name": p.name, "unit": p.unit, "unit_size": p.unit_size,
              "aisle": p.aisle, "start": p.on_hand, "on_hand": running[p.part_number],
              "posted": p.on_hand - running[p.part_number], "max_per_pull": p.max_per_pull,
              "low": running[p.part_number] <= p.max_per_pull, "last": last_change.get(p.part_number)}
             for p in ref.parts.values()]
    work_orders = [{"wo_number": w.wo_number, "status": w.status, "crew": w.crew,
                    "members": list(w.members), "location": w.location,
                    "opened": w.opened.isoformat(), "closed": w.closed.isoformat() if w.closed else None,
                    "postings": by_wo.get(w.wo_number, {}).get("postings", 0),
                    "lines": by_wo.get(w.wo_number, {}).get("lines", 0),
                    "last": by_wo.get(w.wo_number, {}).get("last")}
                   for w in ref.work_orders.values()]
    return {"parts": parts, "work_orders": work_orders, "changes": changes[::-1],
            "latest_posting_id": postings[-1]["id"] if postings else None}


def reset() -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM checks")
        conn.execute("DELETE FROM postings")
