import json
from datetime import date
from pathlib import Path

import pytest

from slipcheck import InvalidSlip, load_reference, validate
from slipcheck.__main__ import load_slip, main
from slipcheck.extract import ExtractionError, _parse_json, extract
from slipcheck.validate import BLOCK, normalize_wo

TODAY = date(2026, 10, 27)
SLIPS = Path(__file__).resolve().parent.parent / "data" / "slips"


@pytest.fixture(scope="module")
def ref():
    return load_reference()


def slip(**overrides):
    base = {
        "wo_number": "WO-26-0412", "date": "10/22/2026", "taken_by": "J. Rivera",
        "location": "Harlow Hall", "signature": True,
        "items": [{"part_number": "PL-1001", "part_name": "3/4 PVC elbow", "qty": 6, "unit": "ea"}],
    }
    return base | overrides


def codes(report, severity=None):
    return {i.code for i in report.issues if severity is None or i.severity == severity}


def item(**kw):
    return {"part_number": None, "part_name": None, "qty": 1, "unit": None} | kw


# ------------------------------------------------------------ happy path


def test_clean_slip_is_ready(ref):
    r = validate(slip(), ref, TODAY)
    assert r.status == "READY"
    assert r.issues == []
    assert r.lines[0].part_number == "PL-1001" and r.lines[0].qty == 6 and r.lines[0].aisle == "A03"


# ------------------------------------------------------------ work orders


def test_closed_wo_suggests_open_wo_for_same_crew_and_location(ref):
    r = validate(slip(wo_number="WO-26-0388"), ref, TODAY)
    issue = next(i for i in r.issues if i.code == "CLOSED_WO")
    assert r.status == "BLOCKED"
    assert "WO-26-0412" in issue.suggestions[0]


def test_wo_typo_suggests_lookalike_on_same_crew_only(ref):
    r = validate(slip(wo_number="26-0142"), ref, TODAY)
    issue = next(i for i in r.issues if i.code == "UNKNOWN_WO")
    assert len(issue.suggestions) == 1 and "WO-26-0412" in issue.suggestions[0]


@pytest.mark.parametrize("raw, expected", [
    ("WO-26-0412", "WO-26-0412"), ("26-0412", "WO-26-0412"), ("wo 26/412", "WO-26-0412"),
    ("0412", "WO-26-0412"), ("none", None),
])
def test_normalize_wo(raw, expected):
    assert normalize_wo(raw, 2026) == expected


def test_location_abbreviation_is_not_a_mismatch(ref):
    r = validate(slip(location="Harlow"), ref, TODAY)
    assert "LOCATION_MISMATCH" not in codes(r)


def test_wrong_location_warns(ref):
    r = validate(slip(location="Bell Hall"), ref, TODAY)
    assert "LOCATION_MISMATCH" in codes(r, "warn")


def test_taker_not_on_crew_warns(ref):
    r = validate(slip(taken_by="S. Chen"), ref, TODAY)
    assert "NOT_ON_CREW" in codes(r, "warn")


# ------------------------------------------------------------ units


def test_pair_tracked_part_with_bare_number_is_ambiguous_and_unposted(ref):
    r = validate(slip(items=[item(part_number="GN-4010", qty=2)]), ref, TODAY)
    issue = next(i for i in r.issues if i.code == "UNIT_AMBIGUOUS")
    assert issue.severity == BLOCK
    assert issue.suggestions == ["2 PR", "1 PR"]
    assert r.lines[0].qty is None  # never pick a reading silently


def test_pieces_convert_to_pairs(ref):
    r = validate(slip(items=[item(part_number="GN-4001", qty=4, unit="pcs")]), ref, TODAY)
    assert r.status == "READY"
    assert (r.lines[0].qty, r.lines[0].unit) == (2, "PR")


def test_odd_pieces_of_pair_part_blocks(ref):
    r = validate(slip(items=[item(part_number="GN-4001", qty=3, unit="pcs")]), ref, TODAY)
    assert "UNIT_REMAINDER" in codes(r, BLOCK)


def test_odd_bare_number_on_pair_part_is_read_as_pairs(ref):
    r = validate(slip(items=[item(part_number="GN-4010", qty=3)]), ref, TODAY)
    assert "UNIT_ASSUMED" in codes(r, "warn")
    assert r.lines[0].qty == 3


# ------------------------------------------------------------ part matching


def test_name_only_clear_match_resolves(ref):
    r = validate(slip(items=[item(part_name="wax ring")]), ref, TODAY)
    assert r.lines[0].part_number == "PL-1020"
    assert "NAME_MATCHED" in codes(r, "info")


def test_name_only_tie_is_not_guessed(ref):
    r = validate(slip(items=[item(part_name="duplex outlet", qty=4)]), ref, TODAY)
    issue = next(i for i in r.issues if i.code == "PART_AMBIGUOUS")
    assert r.lines[0].part_number is None
    assert {s.split()[0] for s in issue.suggestions[:2]} == {"EL-2010", "EL-2011"}


def test_unknown_part_number(ref):
    r = validate(slip(items=[item(part_number="PL-1100", part_name="3/4 elbow")]), ref, TODAY)
    issue = next(i for i in r.issues if i.code == "UNKNOWN_PART")
    assert any("PL-1001" in s for s in issue.suggestions)


def test_name_contradicting_number_blocks(ref):
    r = validate(slip(items=[item(part_number="PL-1001", part_name="duct tape")]), ref, TODAY)
    assert "NAME_NUMBER_MISMATCH" in codes(r, BLOCK)


def test_duplicate_part_warns(ref):
    r = validate(slip(items=[item(part_number="PL-1001"), item(part_number="PL-1001")]), ref, TODAY)
    assert "DUPLICATE_PART" in codes(r, "warn")


# ------------------------------------------------------------ quantity / header


def test_more_than_on_hand_blocks(ref):
    r = validate(slip(items=[item(part_number="HV-3011", qty=8, unit="ea")]), ref, TODAY)
    assert "EXCEEDS_ON_HAND" in codes(r, BLOCK)


def test_unusually_large_pull_warns(ref):
    r = validate(slip(items=[item(part_number="EL-2030", qty=30, unit="ea")]), ref, TODAY)
    assert r.status == "READY_WITH_WARNINGS" and "UNUSUAL_QTY" in codes(r)


@pytest.mark.parametrize("qty", ["a few", 0, -2, 1.5, True])
def test_bad_quantity_blocks(ref, qty):
    r = validate(slip(items=[item(part_number="PL-1001", qty=qty)]), ref, TODAY)
    assert "BAD_QTY" in codes(r, BLOCK)


def test_word_quantity_is_read(ref):
    r = validate(slip(items=[item(part_number="PL-1001", qty="two", unit="ea")]), ref, TODAY)
    assert r.lines[0].qty == 2


def test_missing_signature_blocks(ref):
    assert "MISSING_SIGNATURE" in codes(validate(slip(signature=False), ref, TODAY), BLOCK)


def test_future_and_unreadable_dates_warn(ref):
    assert "FUTURE_DATE" in codes(validate(slip(date="12/01/2026"), ref, TODAY))
    assert "BAD_DATE" in codes(validate(slip(date="last tuesday"), ref, TODAY))


# ------------------------------------------------------------ confidence / human review


def test_low_confidence_read_goes_to_human_review(ref):
    r = validate(slip(taken_by={"value": None, "raw": "A. Ok?f??", "confidence": 0.35}), ref, TODAY)
    assert "HUMAN_REVIEW" in codes(r, BLOCK)
    assert "MISSING_TAKEN_BY" not in codes(r)  # illegible is not the same as blank


def test_confident_photo_fields_pass_through(ref):
    r = validate(slip(wo_number={"value": "26-0412", "raw": "26-0412", "confidence": 0.95}), ref, TODAY)
    assert r.status == "READY" and r.wo_number == "WO-26-0412"


# ------------------------------------------------------------ invalid input


@pytest.mark.parametrize("bad", [None, [], "WO-26-0412", {"foo": 1}])
def test_non_slip_input_is_rejected(ref, bad):
    with pytest.raises(InvalidSlip):
        validate(bad, ref, TODAY)


def test_garbage_slip_blocks_without_crashing(ref):
    r = validate(json.loads((SLIPS / "11_invalid_input.json").read_text()), ref, TODAY)
    assert r.status == "BLOCKED"
    assert {"MISSING_WO", "MISSING_TAKEN_BY", "BAD_QTY", "BAD_LINE"} <= codes(r)


def test_truncated_json_is_rejected():
    with pytest.raises(InvalidSlip, match="not valid JSON"):
        load_slip(SLIPS / "12_truncated.json", live=False, save=False)


def test_hard_case_sample(ref):
    r = validate(json.loads((SLIPS / "10_hard_case.json").read_text()), ref, TODAY)
    assert {"CLOSED_WO", "HUMAN_REVIEW", "PART_AMBIGUOUS", "UNIT_AMBIGUOUS"} <= codes(r, BLOCK)


# ------------------------------------------------------------ extraction (mock + guards)


def test_mock_extraction_replays_cache(tmp_path, ref):
    photo = tmp_path / "slip_hard_case.png"
    photo.write_bytes(b"not really an image")
    data = extract(photo)
    assert data["_provenance"]["kind"] == "live model output"  # real Haiku reading, replayed
    assert validate(data, ref, TODAY).status == "BLOCKED"


def test_mock_extraction_without_cache_explains(tmp_path):
    photo = tmp_path / "unknown_photo.jpg"
    photo.write_bytes(b"x")
    with pytest.raises(ExtractionError, match="No cached extraction"):
        extract(photo)


def test_live_extraction_without_key_explains(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    photo = tmp_path / "slip.jpg"
    photo.write_bytes(b"x")
    with pytest.raises(ExtractionError, match="ANTHROPIC_API_KEY"):
        extract(photo, live=True)


def test_model_json_in_code_fence_is_parsed():
    assert _parse_json('```json\n{"wo_number": null}\n```') == {"wo_number": None}
    with pytest.raises(ExtractionError):
        _parse_json("Sorry, I can't read this slip.")


def test_cli_exit_codes(capsys):
    assert main(["check", str(SLIPS / "01_clean.json")]) == 0
    assert "Status: READY" in capsys.readouterr().out
    assert main(["check", str(SLIPS / "12_truncated.json")]) == 2


def test_new_samples_land_where_designed(ref):
    expected = {
        "13_custodial_restock.json": ("READY", set()),
        "14_ear_plugs_in_pieces.json": ("READY", set()),
        "15_not_on_crew.json": ("READY_WITH_WARNINGS", {"NOT_ON_CREW"}),
        "16_wrong_building.json": ("READY_WITH_WARNINGS", {"LOCATION_MISMATCH"}),
        "17_name_contradicts_number.json": ("BLOCKED", {"NAME_NUMBER_MISMATCH"}),
        "18_same_part_twice.json": ("READY_WITH_WARNINGS", {"DUPLICATE_PART"}),
        "19_dated_before_wo.json": ("READY_WITH_WARNINGS", {"BEFORE_WO_OPENED"}),
        "20_weekly_plumbing_pull.json": ("BLOCKED", {"PART_AMBIGUOUS", "UNIT_REMAINDER"}),
    }
    for name, (status, issue_codes) in expected.items():
        r = validate(json.loads((SLIPS / name).read_text()), ref, TODAY)
        assert r.status == status, name
        assert {i.code for i in r.issues if i.severity != "info"} == issue_codes, name


def test_odd_pieces_offer_both_whole_pair_readings(ref):
    r = validate(slip(items=[item(part_number="GN-4001", qty=3, unit="pcs")]), ref, TODAY)
    issue = next(i for i in r.issues if i.code == "UNIT_REMAINDER")
    assert [f["set"] for f in issue.fixes] == [{"qty": 1, "unit": "PR"}, {"qty": 2, "unit": "PR"}]
