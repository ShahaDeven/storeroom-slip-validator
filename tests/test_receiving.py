from datetime import date
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from slipcheck.api import app
from slipcheck.extract import ExtractionError
from slipcheck.receiving.extract import parse_pdf, read_receipt
from slipcheck.receiving.reference import load_receiving
from slipcheck.receiving.validate import validate_receipt
from slipcheck.validate import InvalidSlip

RECEIPTS = Path(__file__).resolve().parent.parent / "data" / "receiving" / "receipts"
TODAY = date(2026, 11, 4)


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("SLIPCHECK_DB", str(tmp_path / "ledger.db"))


@pytest.fixture(scope="module")
def ref():
    return load_receiving()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def check(name, ref):
    return validate_receipt(read_receipt(RECEIPTS / name), ref, TODAY)


def codes(report, severity=None):
    return {i.code for i in report.issues if severity is None or i.severity == severity}


def issue(report, code):
    return next(i for i in report.issues if i.code == code)


def apply_fix(reading, iss, fix):
    """What the UI does: set the fix's values on the issue's line, or on the header."""
    target = reading if iss.line is None else reading["items"][iss.line - 1]
    target.update(fix["set"])
    return reading


def fix_labelled(iss, text):
    return next(f for f in iss.fixes if text in f["label"])


# ------------------------------------------------------------ reading the PDF


def test_pdf_values_and_real_word_boxes():
    r = parse_pdf(RECEIPTS / "R02.pdf")
    assert r["receipt_number"]["value"] == "R-20102" and r["po_number"]["value"] == "PO-26-1102"
    assert [{k: v["value"] for k, v in it.items()} for it in r["items"]] == [
        {"part_number": "EL-2010", "part_name": "20a outlet", "qty": "30", "unit": "ea"},
        {"part_number": "EL-2011", "part_name": "15a outlet", "qty": "18", "unit": "ea"}]
    src = r["items"][1]["qty"]["source"]
    w, h = src["page_size"]
    x0, y0, x1, y1 = src["bbox"]
    assert src["method"] == "pdf_text" and src["page"] == 1 and src["line"] == 2
    assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h  # a box on the page, not an invented location
    assert r["items"][1]["qty"]["confidence"] == 1.0


def test_blank_cells_are_blank_not_guessed():
    assert parse_pdf(RECEIPTS / "R11.pdf")["received_by"]["value"] is None
    assert parse_pdf(RECEIPTS / "R06.pdf")["items"][0]["unit"]["value"] is None


def test_the_image_reading_carries_no_invented_coordinates():
    r = read_receipt(RECEIPTS / "R13.png")
    assert "bbox" not in r["po_number"]["source"] and r["po_number"]["source"]["method"] == "vision"


def test_a_pdf_that_is_not_a_receipt_is_rejected(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 80), "Quarterly newsletter, nothing to receive here.")
    doc.save(str(tmp_path / "news.pdf"))
    with pytest.raises(ExtractionError, match="does not look like a delivery receipt"):
        parse_pdf(tmp_path / "news.pdf")


def test_a_scanned_pdf_with_no_text_layer_says_so(tmp_path):
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(tmp_path / "blank.pdf"))
    with pytest.raises(ExtractionError, match="no text layer"):
        parse_pdf(tmp_path / "blank.pdf")


def test_non_receipt_input_is_rejected(ref):
    for bad in (None, [], "R-1", {"foo": 1}):
        with pytest.raises(InvalidSlip):
            validate_receipt(bad, ref, TODAY)


# ------------------------------------------------------------ the scenarios


@pytest.mark.parametrize("name, status, expected", [
    ("R01.pdf", "READY", set()),
    ("R02.pdf", "READY_WITH_WARNINGS", {"SHORT_SHIPMENT", "LINE_NOT_DELIVERED"}),
    ("R03.pdf", "BLOCKED", {"OVER_SHIPMENT"}),
    ("R04.pdf", "READY", set()),
    ("R05.pdf", "BLOCKED", {"UNIT_REMAINDER"}),
    ("R06.pdf", "BLOCKED", {"UNIT_AMBIGUOUS"}),
    ("R07.pdf", "BLOCKED", {"UNORDERED_ITEM"}),
    ("R08.pdf", "BLOCKED", {"DUPLICATE_RECEIPT"}),
    ("R09.pdf", "BLOCKED", {"PO_CLOSED"}),
    ("R10.pdf", "BLOCKED", {"UNKNOWN_PO"}),
    ("R11.pdf", "BLOCKED", {"MISSING_RECEIVED_BY"}),
    ("R12.pdf", "BLOCKED", {"UNORDERED_ITEM"}),
    ("R13.png", "READY", set()),
])
def test_each_sample_shows_what_it_was_made_to_show(ref, name, status, expected):
    r = check(name, ref)
    assert r.status == status and codes(r, "block") | codes(r, "warn") == expected


def test_a_short_delivery_is_a_partial_not_a_failure(ref):
    r = check("R02.pdf", ref)
    assert r.status != "BLOCKED"
    short = issue(r, "SHORT_SHIPMENT")
    assert short.severity == "warn" and "12 EA remain on order" in short.message
    states = {p["part_number"]: p["state"] for p in r.po_lines}
    assert states == {"EL-2010": "complete", "EL-2011": "partial", "EL-2001": "not delivered"}
    assert {p["part_number"]: p["open_after"] for p in r.po_lines}["EL-2011"] == 12


def test_pack_size_converts_pieces_to_boxes(ref):
    r = check("R04.pdf", ref)
    assert (r.lines[0]["qty"], r.lines[0]["unit"]) == (10, "BX") and "UNIT_CONVERTED" in codes(r, "info")


def test_blocked_lines_do_not_make_the_po_line_look_undelivered(ref):
    for name in ("R05.pdf", "R06.pdf", "R12.pdf"):
        assert "LINE_NOT_DELIVERED" not in codes(check(name, ref)), name


def test_a_correction_is_never_the_other_line_already_on_the_receipt(ref):
    r = check("R12.pdf", ref)
    labels = [f["label"] for f in issue(r, "UNORDERED_ITEM").fixes]
    assert labels[0] == "Change to PL-1001" and "Change to PL-1002" not in labels


def test_unknown_po_suggests_lookalikes_from_the_same_vendor(ref):
    s = issue(check("R10.pdf", ref), "UNKNOWN_PO").suggestions
    assert s and all("Northline Supply" in x for x in s)


def test_a_duplicate_does_not_also_report_over_shipment(ref):
    assert codes(check("R08.pdf", ref)) == {"DUPLICATE_RECEIPT"}


# ------------------------------------------------------------ answering the questions


@pytest.mark.parametrize("name, code, label, then_status", [
    ("R03.pdf", "OVER_SHIPMENT", "Receive 6 and return 2", "READY"),
    ("R03.pdf", "OVER_SHIPMENT", "Accept all 8", "READY"),  # a recorded decision, not a lingering warning
    ("R03.pdf", "OVER_SHIPMENT", "Return to vendor", "READY_WITH_WARNINGS"),
    ("R06.pdf", "UNIT_AMBIGUOUS", "1 BX", "READY_WITH_WARNINGS"),
    ("R07.pdf", "UNORDERED_ITEM", "Return to vendor", "READY"),
    ("R12.pdf", "UNORDERED_ITEM", "Change to PL-1001", "READY"),
    ("R05.pdf", "UNIT_REMAINDER", "Hold for the buyer", "READY_WITH_WARNINGS"),
])
def test_each_offered_answer_resolves_the_block(ref, name, code, label, then_status):
    reading = read_receipt(RECEIPTS / name)
    first = validate_receipt(reading, ref, TODAY)
    reading = apply_fix(reading, issue(first, code), fix_labelled(issue(first, code), label))
    after = validate_receipt(reading, ref, TODAY)
    assert code not in codes(after, "block") and after.status == then_status, [i.code for i in after.issues]


def test_missing_received_by_is_fixed_by_typing_a_name(ref):
    reading = read_receipt(RECEIPTS / "R11.pdf")
    reading["received_by"] = "R. Malik"
    assert validate_receipt(reading, ref, TODAY).status == "READY"


def test_low_confidence_reading_goes_to_review(ref):
    reading = read_receipt(RECEIPTS / "R13.png")
    reading["items"][0]["qty"] = {"value": "10", "raw": "1?", "confidence": 0.5}
    r = validate_receipt(reading, ref, TODAY)
    assert "HUMAN_REVIEW" in codes(r, "block")


# ------------------------------------------------------------ posting, history and the audit trail


def post(client, name, reading=None, answers=()):
    reading = reading or read_receipt(RECEIPTS / name)
    return client.post("/api/receiving/post", json={"receipt": reading, "name": name, "answers": list(answers)})


def test_posting_updates_the_po_and_can_close_it(client):
    assert post(client, "R01.pdf").status_code == 200
    po = next(p for p in client.get("/api/receiving/summary").json()["pos"] if p["po_number"] == "PO-26-1101")
    assert po["status"] == "CLOSED" and all(ln["open"] == 0 for ln in po["lines"])
    # a second delivery against the now-complete PO is refused
    again = read_receipt(RECEIPTS / "R01.pdf")
    again["receipt_number"] = "R-99999"
    r = client.post("/api/receiving/validate", json={"receipt": again}).json()
    assert r["status"] == "BLOCKED" and any(i["code"] == "PO_CLOSED" for i in r["issues"])


def test_the_same_receipt_cannot_be_posted_twice_but_reopens_as_posted(client):
    assert post(client, "R01.pdf").status_code == 200
    assert post(client, "R01.pdf").status_code == 409
    reopened = client.post("/api/receiving/validate", json={"receipt": read_receipt(RECEIPTS / "R01.pdf"), "name": "R01.pdf"}).json()
    assert reopened["posted"]["receipt_number"] == "R-20101"
    assert reopened["status"] == "READY"  # shown as it was before posting, not as a duplicate of itself


def test_blocked_receipts_cannot_be_posted(client):
    assert post(client, "R03.pdf").status_code == 409
    assert client.get("/api/receiving/summary").json()["counts"]["posted"] == 0


def test_a_partial_delivery_then_the_rest(client):
    assert post(client, "R02.pdf").status_code == 200
    rest = read_receipt(RECEIPTS / "R02.pdf")
    rest["receipt_number"] = "R-20150"
    rest["items"] = [rest["items"][1], {"part_number": "EL-2001", "part_name": "wire nut yellow", "qty": "10", "unit": "bx"}]
    rest["items"][0]["qty"] = {"value": "12", "confidence": 1.0}
    r = client.post("/api/receiving/validate", json={"receipt": rest}).json()
    assert r["status"] == "READY", [i["code"] for i in r["issues"]]
    assert post(client, "rest", rest).status_code == 200
    po = next(p for p in client.get("/api/receiving/summary").json()["pos"] if p["po_number"] == "PO-26-1102")
    assert po["status"] == "CLOSED"


def test_the_audit_trail_records_what_was_found_and_answered(client):
    client.post("/api/receiving/validate", json={"receipt": read_receipt(RECEIPTS / "R03.pdf"), "name": "R03.pdf"})
    fixed = read_receipt(RECEIPTS / "R03.pdf")
    fixed["items"][0]["qty"] = 6
    assert post(client, "R03.pdf", fixed, ["Line 1: Receive 6 and return 2"]).status_code == 200
    events = client.get("/api/events").json()
    kinds = [e["kind"] for e in events]
    assert "receipt_checked" in kinds and "receipt_posted" in kinds
    checked = next(e for e in events if e["kind"] == "receipt_checked")
    assert ["block", "OVER_SHIPMENT"] in checked["detail"]["found"]
    posted = next(e for e in events if e["kind"] == "receipt_posted")
    assert posted["detail"]["answers"] == ["Line 1: Receive 6 and return 2"]
    assert client.get("/api/receiving/summary").json()["caught"] == [{"code": "OVER_SHIPMENT", "count": 1}]


def test_clearing_the_shift_log_restores_the_purchase_orders(client):
    assert post(client, "R01.pdf").status_code == 200
    client.post("/api/ledger/reset")
    assert client.get("/api/receiving/summary").json()["counts"]["posted"] == 0
    assert post(client, "R01.pdf").status_code == 200


def test_samples_are_served_by_id_only(client):
    ids = {s["id"] for s in client.get("/api/receiving/samples").json()}
    assert ids == {f"R{n:02d}" for n in range(1, 14)}
    assert client.get("/api/receiving/samples/..").status_code == 404
    assert client.get("/api/receiving/samples/R99").status_code == 404
    assert client.get("/api/receiving/page/R02").content[:4] == b"\x89PNG"


def test_uploading_a_pdf_reads_its_text_layer_and_rejects_other_files(client):
    ok = client.post("/api/receiving/extract", files={"file": ("R02.pdf", (RECEIPTS / "R02.pdf").read_bytes(), "application/pdf")})
    assert ok.json()["reading"]["po_number"]["value"] == "PO-26-1102"
    bad = client.post("/api/receiving/extract", files={"file": ("notes.txt", b"x", "text/plain")})
    assert bad.status_code == 422
