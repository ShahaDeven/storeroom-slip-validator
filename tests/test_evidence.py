import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipcheck import load_reference
from slipcheck.api import app
from slipcheck.evidence import RULES, receipt_evidence, slip_evidence
from slipcheck.receiving.extract import read_receipt
from slipcheck.receiving.reference import RECEIVING_DIR, load_receiving
from slipcheck.receiving.validate import validate_receipt
from slipcheck.validate import validate

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("SLIPCHECK_DB", str(tmp_path / "ledger.db"))


def slips():
    for p in sorted((DATA / "slips").glob("*.json")):
        try:
            yield p.name, json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue


def test_every_code_the_samples_raise_has_a_rule_in_plain_words():
    ref, rref, seen = load_reference(), load_receiving(), set()
    for _, s in slips():
        try:
            seen |= {i.code for i in validate(s, ref).issues}
        except Exception:
            continue
    for p in sorted((RECEIVING_DIR / "receipts").iterdir()):
        seen |= {i.code for i in validate_receipt(read_receipt(p), rref).issues}
    assert seen - RULES.keys() == set()


def test_evidence_lines_up_with_the_issues_and_changes_no_decision():
    ref = load_reference()
    s = json.loads((DATA / "slips" / "10_hard_case.json").read_text(encoding="utf-8"))
    before = validate(s, ref).to_dict()
    report = validate(s, ref)
    ev = slip_evidence(s, report, ref)
    assert len(ev) == len(report.issues) and report.to_dict() == before
    assert [e["rule"]["code"] for e in ev] == [i.code for i in report.issues]


def test_a_closed_wo_shows_the_work_order_record():
    ref = load_reference()
    s = json.loads((DATA / "slips" / "10_hard_case.json").read_text(encoding="utf-8"))
    report = validate(s, ref)
    e = next(e for i, e in zip(report.issues, slip_evidence(s, report, ref)) if i.code == "CLOSED_WO")
    rows = dict(e["reference"]["rows"])
    assert rows["Status"] == "CLOSED" and rows["Crew"] == "Electrical"
    assert e["extracted"]["field"] == "W/O number" and e["rule"]["outcome"].startswith("Blocks posting")


def test_a_pdf_value_carries_its_real_word_box_and_a_photo_value_carries_none():
    rref = load_receiving()
    r = read_receipt(RECEIVING_DIR / "receipts" / "R03.pdf")
    report = validate_receipt(r, rref)
    e = next(e for i, e in zip(report.issues, receipt_evidence(r, report, rref)) if i.code == "OVER_SHIPMENT")
    assert e["extracted"]["source"]["bbox"] and e["extracted"]["source"]["method"] == "pdf_text"
    assert dict(e["reference"]["rows"])["Still open"] == "6 BX"

    from slipcheck.extract import extract
    photo = extract(DATA / "photos" / "slip_hard_case.jpeg")
    rep = validate(photo, load_reference())
    for e in slip_evidence(photo, rep, load_reference()):
        src = (e["extracted"] or {}).get("source") or {}
        assert not {"bbox", "box", "x", "y"} & set(src)  # no invented locations


def test_duplicate_receipt_points_at_the_history_record():
    rref = load_receiving()
    r = read_receipt(RECEIVING_DIR / "receipts" / "R08.pdf")
    report = validate_receipt(r, rref)
    e = next(e for i, e in zip(report.issues, receipt_evidence(r, report, rref)) if i.code == "DUPLICATE_RECEIPT")
    assert "R-10388" in e["reference"]["title"] and dict(e["reference"]["rows"])["PO"] == "PO-26-1104"


def test_both_validate_endpoints_return_evidence():
    c = TestClient(app)
    s = json.loads((DATA / "slips" / "10_hard_case.json").read_text(encoding="utf-8"))
    body = c.post("/api/validate", json={"slip": s}).json()
    assert len(body["evidence"]) == len(body["issues"])
    r = read_receipt(RECEIVING_DIR / "receipts" / "R12.pdf")
    body = c.post("/api/receiving/validate", json={"receipt": r}).json()
    assert len(body["evidence"]) == len(body["issues"]) and body["evidence"][0]["reference"]
