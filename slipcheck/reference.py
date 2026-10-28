"""Reference data the validator checks slips against: parts catalog and work orders.

In a real storeroom these would come from the inventory / CMMS system. Here they are
synthetic CSVs in data/ (see README).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Part:
    part_number: str
    name: str
    aliases: tuple[str, ...]
    unit: str  # unit of issue the system tracks: EA, PR, BX, RL
    unit_size: int  # pieces per unit of issue (PR = 2, BX = 12 / 100, EA = 1)
    aisle: str
    on_hand: int
    max_per_pull: int


@dataclass(frozen=True)
class WorkOrder:
    wo_number: str
    status: str  # OPEN | CLOSED
    crew: str
    members: tuple[str, ...]
    location: str
    opened: date
    closed: date | None

    @property
    def is_open(self) -> bool:
        return self.status.upper() == "OPEN"


@dataclass
class Reference:
    parts: dict[str, Part] = field(default_factory=dict)
    work_orders: dict[str, WorkOrder] = field(default_factory=dict)


def _split(cell: str) -> tuple[str, ...]:
    return tuple(s.strip() for s in cell.split("|") if s.strip())


def load_reference(data_dir: Path = DATA_DIR) -> Reference:
    ref = Reference()
    with open(data_dir / "catalog.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ref.parts[row["part_number"]] = Part(
                part_number=row["part_number"],
                name=row["name"],
                aliases=_split(row["aliases"]),
                unit=row["unit"],
                unit_size=int(row["unit_size"]),
                aisle=row["aisle"],
                on_hand=int(row["on_hand"]),
                max_per_pull=int(row["max_per_pull"]),
            )
    with open(data_dir / "work_orders.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ref.work_orders[row["wo_number"]] = WorkOrder(
                wo_number=row["wo_number"],
                status=row["status"],
                crew=row["crew"],
                members=_split(row["members"]),
                location=row["location"],
                opened=date.fromisoformat(row["opened"]),
                closed=date.fromisoformat(row["closed"]) if row["closed"] else None,
            )
    return ref
