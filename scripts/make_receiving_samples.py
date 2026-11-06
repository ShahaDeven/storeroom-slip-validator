"""Build the synthetic receiving data: purchase orders, receiving history, and sample receipts.

    python scripts/make_receiving_samples.py

Writes to data/receiving/:
  purchase_orders.csv   the system of record (like the parts catalog); vendors are invented
  receipts_seed.csv     deliveries already received before the demo starts
  receipts/R01.pdf ...  digital delivery receipts (a text layer, so no OCR is needed)
  receipts/R13.png      the same kind of document rendered to an image, for the vision path
  scenarios.csv         what each receipt is designed to show (the tests check these)

Everything is synthetic. Vendor names, PO and receipt numbers are invented.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "receiving"

VENDORS = {
    "Northline Supply": ("412 Foundry Row", "Buffalo, NY 14203"),
    "Ridgeway Electric": ("88 Canal Street", "Rochester, NY 14604"),
    "Calder Industrial": ("1500 Mill Road", "Syracuse, NY 13202"),
}

# po_number, vendor, status, ordered_on, [(part_number, description, qty_ordered, unit, unit_size)]
POS = [
    ("PO-26-1101", "Northline Supply", "OPEN", "10/05/26", [
        ("PL-1001", "PVC Elbow 90 deg 3/4 in", 50, "EA", 1), ("PL-1010", "Ball Valve 3/4 in Brass", 12, "EA", 1),
        ("PL-1040", "PTFE Thread Seal Tape 1/2 in", 24, "RL", 1)]),
    ("PO-26-1102", "Ridgeway Electric", "OPEN", "10/06/26", [
        ("EL-2010", "Duplex Receptacle 20A White", 30, "EA", 1), ("EL-2011", "Duplex Receptacle 15A White", 30, "EA", 1),
        ("EL-2001", "Wire Nut Yellow (box of 100)", 10, "BX", 100)]),
    ("PO-26-1103", "Calder Industrial", "OPEN", "10/07/26", [
        ("HV-3001", "Air Filter 20x20x2 MERV 8 (box of 12)", 6, "BX", 12),
        ("HV-3002", "Air Filter 24x24x2 MERV 8 (box of 12)", 6, "BX", 12)]),
    ("PO-26-1104", "Northline Supply", "OPEN", "10/08/26", [
        ("PL-1020", "Wax Ring Toilet Seal", 20, "EA", 1), ("PL-1021", "Toilet Flapper 2 in Universal", 20, "EA", 1)]),
    ("PO-26-1105", "Ridgeway Electric", "OPEN", "10/09/26", [("EL-2001", "Wire Nut Yellow (box of 100)", 10, "BX", 100)]),
    ("PO-26-1106", "Ridgeway Electric", "OPEN", "10/09/26", [("EL-2002", "Wire Nut Red (box of 100)", 8, "BX", 100)]),
    ("PO-26-1107", "Calder Industrial", "OPEN", "10/10/26", [("HV-3002", "Air Filter 24x24x2 MERV 8 (box of 12)", 6, "BX", 12)]),
    ("PO-26-1108", "Northline Supply", "OPEN", "10/12/26", [("PL-1050", "P-Trap 1-1/2 in PVC", 10, "EA", 1)]),
    ("PO-26-1109", "Calder Industrial", "OPEN", "10/13/26", [
        ("GN-4010", "Door Hinge 4.5 in Satin Nickel", 12, "PR", 2), ("GN-4012", "Lever Lockset Passage", 8, "EA", 1)]),
    ("PO-26-1111", "Northline Supply", "OPEN", "10/14/26", [
        ("PL-1001", "PVC Elbow 90 deg 3/4 in", 40, "EA", 1), ("PL-1002", "PVC Elbow 90 deg 1/2 in", 40, "EA", 1)]),
    ("PO-26-1112", "Calder Industrial", "OPEN", "10/15/26", [("GN-4001", "Work Gloves Leather Large", 10, "PR", 2)]),
    ("PO-26-1090", "Ridgeway Electric", "CLOSED", "09/10/26", [("EL-2030", "LED Tube T8 4 ft", 48, "EA", 1)]),
]

# receipt_number, po_number, received_on, [(part_number, qty, unit)]: deliveries already received.
SEED = [
    ("R-10388", "PO-26-1104", "10/15/26", [("PL-1020", 8, "EA"), ("PL-1021", 20, "EA")]),
    ("R-10301", "PO-26-1090", "09/22/26", [("EL-2030", 24, "EA")]),
    ("R-10302", "PO-26-1090", "09/29/26", [("EL-2030", 24, "EA")]),
]

# id, receipt_number, po_number, vendor, date, received_by, lines [(line part#, description, qty, unit)], what it shows
RECEIPTS = [
    ("R01", "R-20101", "PO-26-1101", "Northline Supply", "10/26/26", "K. Haas",
     [("PL-1001", "pvc elbow 3/4", "50", "ea"), ("PL-1010", "ball valve 3/4", "12", "ea"), ("PL-1040", "ptfe tape", "24", "roll")],
     "complete delivery, nothing to ask"),
    ("R02", "R-20102", "PO-26-1102", "Ridgeway Electric", "10/26/26", "A. Okafor",
     [("EL-2010", "20a outlet", "30", "ea"), ("EL-2011", "15a outlet", "18", "ea")],
     "partial delivery: one line short, one line not delivered; both stay open"),
    ("R03", "R-20103", "PO-26-1103", "Calder Industrial", "10/27/26", "S. Chen",
     [("HV-3001", "air filter 20x20", "8", "bx"), ("HV-3002", "air filter 24x24", "6", "bx")],
     "over-shipment: 8 boxes against 6 ordered"),
    ("R04", "R-20104", "PO-26-1105", "Ridgeway Electric", "10/27/26", "L. Brandt",
     [("EL-2001", "wire nut yellow", "1000", "ea")],
     "pack size: 1,000 pieces converted to 10 boxes of 100"),
    ("R05", "R-20105", "PO-26-1106", "Ridgeway Electric", "10/27/26", "L. Brandt",
     [("EL-2002", "wire nut red", "10", "ea")],
     "pack size: 10 pieces is not a whole box of 100"),
    ("R06", "R-20106", "PO-26-1107", "Calder Industrial", "10/27/26", "R. Malik",
     [("HV-3002", "air filter 24x24", "12", "")],
     "no unit: 12 boxes or 12 pieces (one box)?"),
    ("R07", "R-20107", "PO-26-1108", "Northline Supply", "10/27/26", "D. Pryor",
     [("PL-1050", "p-trap", "10", "ea"), ("GN-4060", "silicone caulk", "4", "ea")],
     "an item that was never ordered"),
    ("R08", "R-10388", "PO-26-1104", "Northline Supply", "10/15/26", "K. Haas",
     [("PL-1020", "wax ring", "8", "ea"), ("PL-1021", "flapper", "20", "ea")],
     "duplicate: this receipt number was already received"),
    ("R09", "R-20109", "PO-26-1090", "Ridgeway Electric", "10/28/26", "A. Okafor",
     [("EL-2030", "t8 led", "12", "ea")],
     "the purchase order is already closed"),
    ("R10", "R-20110", "PO-26-1110", "Northline Supply", "10/28/26", "K. Haas",
     [("PL-1001", "pvc elbow 3/4", "10", "ea")],
     "PO number does not exist (digits swapped)"),
    ("R11", "R-20111", "PO-26-1109", "Calder Industrial", "10/28/26", "",
     [("GN-4010", "door hinge 4.5", "12", "pr"), ("GN-4012", "lever lockset", "8", "ea")],
     "complete delivery, but nobody signed as received by"),
    ("R12", "R-20112", "PO-26-1111", "Northline Supply", "10/28/26", "K. Haas",
     [("PL-1007", "3/4 pvc elbow", "40", "ea"), ("PL-1002", "1/2 elbow", "40", "ea")],
     "part number typo: PL-1007 is not on the PO, but the description matches PL-1001"),
    ("R13", "R-20113", "PO-26-1112", "Calder Industrial", "10/29/26", "R. Malik",
     [("GN-4001", "leather gloves l", "10", "pr")],
     "complete delivery, delivered as an image (vision path)"),
]


def draw(receipt) -> pymupdf.Document:
    rid, number, po, vendor, date, by, lines, _ = receipt
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((50, 62), "DELIVERY RECEIPT", fontsize=18, fontname="hebo")
    page.insert_text((50, 90), vendor, fontsize=11, fontname="hebo")
    for i, text in enumerate(VENDORS[vendor]):
        page.insert_text((50, 105 + 13 * i), text, fontsize=9, fontname="helv")
    for y, label, value in [(150, "Receipt #:", number), (166, "PO #:", po), (182, "Date:", date),
                            (198, "Vendor:", vendor), (214, "Received by:", by)]:
        page.insert_text((50, y), f"{label} {value}".rstrip(), fontsize=10, fontname="helv")
    for x, text in [(50, "Line"), (90, "Part #"), (190, "Description"), (430, "Qty"), (490, "Unit")]:
        page.insert_text((x, 252), text, fontsize=10, fontname="hebo")
    page.draw_line((50, 258), (560, 258), width=0.8)
    for i, (part, desc, qty, unit) in enumerate(lines):
        y = 277 + 20 * i
        for x, text in [(50, str(i + 1)), (90, part), (190, desc), (430, qty), (490, unit)]:
            if text:
                page.insert_text((x, y), text, fontsize=10, fontname="helv")
    page.insert_text((50, 700), "Goods received subject to count and inspection.", fontsize=8, fontname="helv")
    page.insert_text((50, 713), "Synthetic document for a software prototype.", fontsize=8, fontname="helv")
    return doc


def main():
    (OUT / "receipts").mkdir(parents=True, exist_ok=True)
    with open(OUT / "purchase_orders.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["po_number", "vendor", "status", "ordered_on", "line", "part_number", "description", "qty_ordered", "unit", "unit_size"])
        for po, vendor, status, ordered, lines in POS:
            for n, (part, desc, qty, unit, size) in enumerate(lines, 1):
                w.writerow([po, vendor, status, ordered, n, part, desc, qty, unit, size])
    with open(OUT / "receipts_seed.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["receipt_number", "po_number", "received_on", "part_number", "qty", "unit"])
        for number, po, date, lines in SEED:
            for part, qty, unit in lines:
                w.writerow([number, po, date, part, qty, unit])
    with open(OUT / "scenarios.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "receipt_number", "po_number", "shows"])
        for r in RECEIPTS:
            w.writerow([r[0], r[1], r[2], r[7]])
    for r in RECEIPTS:
        doc = draw(r)
        if r[0] == "R13":  # an image with no text layer: forces the vision path
            doc[0].get_pixmap(dpi=150).save(str(OUT / "receipts" / "R13.png"))
        else:
            doc.save(str(OUT / "receipts" / f"{r[0]}.pdf"))
        doc.close()
    print(f"wrote {len(POS)} purchase orders, {len(SEED)} seed receipts, {len(RECEIPTS)} sample receipts to {OUT}")


if __name__ == "__main__":
    main()
