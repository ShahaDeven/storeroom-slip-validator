import pytest

from slipcheck import eval as ev
from slipcheck import load_reference
from slipcheck.extract import add_provenance


@pytest.fixture(scope="module")
def ref():
    return load_reference()


def row(**kw):
    base = {"slip_id": "T01", "split": "dev", "style": "A", "scenario": "clean_2line", "condition": "clear",
            "photo": "data/eval/photos/T01.jpeg", "wo_number": "WO-26-0412", "date": "10/22/26",
            "taken_by": "J. Rivera", "location": "Harlow Hall", "signed": "yes",
            "line1_part_number": "PL-1001", "line1_description": "3/4 elbow", "line1_qty": "6", "line1_unit": "ea"}
    return base | kw


def field(value, conf=0.95):
    return {"value": value, "raw": value, "confidence": conf}


def reading(wo="WO-26-0412", qty=("6", 0.95), name=("3/4 elbow", 0.95), part_number="PL-1001", **item_extra):
    return {"wo_number": field(wo), "date": field("10/22/26"), "taken_by": field("J. Rivera"),
            "location": field("Harlow Hall"), "signature": {"value": True, "confidence": 0.95},
            "items": [{"part_number": field(part_number), "part_name": field(name[0], name[1]),
                       "qty": field(qty[0], qty[1]), "unit": field("ea")} | item_extra]}


def wrong(result):
    return [f for f in result.fields if not f.correct]


# ------------------------------------------------------------ statistics


def test_wilson_interval():
    assert ev.wilson(0, 0) == (0.0, 1.0)
    lo, hi = ev.wilson(0, 20)
    assert lo == 0.0 and 0.14 < hi < 0.18  # "0 of 20" still allows roughly 16%
    lo, hi = ev.wilson(10, 10)
    assert hi == 1.0 and 0.70 < lo < 0.80
    assert ev.prop(3, 4)["rate"] == 0.75 and ev.prop(0, 0)["rate"] is None


@pytest.mark.parametrize("name, a, b, expected", [
    ("wo_number", "wo-26-0412", "26-0412", True),          # the validator treats these as one work order
    ("wo_number", "26-0412", "26-0462", False),
    ("date", "10/22/26", "10/22/2026", True),
    ("date", "10/22/26", "10/23/26", False),
    ("part_number", "pl-1001", "pl- 1001", True),            # a stray space is ignored, as in the validator
    ("part_number", "pl-1001", "pl 1001", False),            # a missing hyphen is not: the catalog lookup would fail
    ("part_number", "pl-1001", "pl-1007", False),
    ("part_name", "duplex outlet", "dupler outlet", False),  # words are compared exactly
    ("qty", "4", "9", False),
])
def test_equality_by_meaning_only_where_the_validator_agrees(name, a, b, expected):
    assert ev.same_value(name, a, b) is expected


def test_norm_makes_numbers_and_case_comparable():
    assert ev.norm("4.0") == "4" and ev.norm(" PL-1001. ") == "pl-1001" and ev.norm(None) == ""
    assert ev.norm(True) == "yes" and ev.norm(False) == "no"


# ------------------------------------------------------------ the four outcomes


def test_correct_reading_changes_nothing(ref):
    r = ev.evaluate_slip(row(), reading(), ref)
    assert r.outcome == "read_correctly" and wrong(r) == []


def test_confident_quantity_misread_is_reported_as_not_caught(ref):
    """6 read as 9 at 0.95: nothing on the slip contradicts it, so nothing flags it."""
    r = ev.evaluate_slip(row(), reading(qty=("9", 0.95)), ref)
    bad = wrong(r)
    assert [f.name for f in bad] == ["qty"]
    assert bad[0].critical and bad[0].silent and not bad[0].review
    assert r.outcome == "misread_not_caught"


def test_the_same_misread_at_low_confidence_goes_to_review(ref):
    r = ev.evaluate_slip(row(), reading(qty=("9", 0.5)), ref)
    assert r.outcome == "misread_caught" and wrong(r)[0].review and r.review_requested


def test_misread_digit_in_the_work_order_is_caught_by_cross_checks(ref):
    """WO-26-0462 is a Custodial W/O in another building; the slip's person and place don't fit it."""
    r = ev.evaluate_slip(row(), reading(wo="WO-26-0462"), ref)
    bad = wrong(r)
    assert [f.name for f in bad] == ["wo_number"]
    assert bad[0].new_flag and not bad[0].review and r.outcome == "misread_caught"


def test_misread_absorbed_by_a_block_that_was_already_there(ref):
    """'dupler outlet' vs 'duplex outlet': both are ambiguous, so a person chooses the part either way."""
    truth = row(line1_part_number="", line1_description="duplex outlet", line1_qty="4", line1_unit="")
    read = reading(part_number=None, name=("dupler outlet", 0.8), qty=("4", 0.95))
    read["items"][0]["unit"] = field(None, 1.0)
    r = ev.evaluate_slip(truth, read, ref)
    bad = wrong(r)
    assert [f.name for f in bad] == ["part_name"] and bad[0].critical
    assert bad[0].absorbed and not bad[0].flagged and not bad[0].silent
    assert r.outcome == "misread_caught"


def test_minor_misread_with_no_flag_is_not_counted_as_unsafe(ref):
    r = ev.evaluate_slip(row(), reading(name=("3/4 ellbow", 0.9)), ref)  # description, number is right
    assert wrong(r)[0].name == "part_name" and not wrong(r)[0].critical
    assert r.outcome == "misread_noncritical_unflagged"


def test_format_difference_is_not_a_misread(ref):
    r = ev.evaluate_slip(row(wo_number="26-0412"), reading(wo="WO-26-0412"), ref)
    assert r.outcome == "read_correctly"


def test_blank_fields_read_as_blank_are_not_scored(ref):
    truth = row(date="")
    read = reading()
    read["date"] = field(None, 1.0)
    r = ev.evaluate_slip(truth, read, ref)
    assert all(f.name != "date" for f in r.fields) and r.outcome == "read_correctly"


def test_unnecessary_review_is_counted_on_correct_fields(ref):
    results = [ev.evaluate_slip(row(), reading(name=("3/4 elbow", 0.6)), ref)]
    s = ev.summarize(results)
    assert s["unnecessary_review"]["k"] == 1 and s["fields_correct"]["rate"] == 1.0


def test_summary_counts_and_bins(ref):
    results = [ev.evaluate_slip(row(), reading(), ref),
               ev.evaluate_slip(row(slip_id="T02"), reading(qty=("9", 0.95)), ref),
               ev.evaluate_slip(row(slip_id="T03"), reading(qty=("9", 0.5)), ref)]
    s = ev.summarize(results)
    assert {k: v["k"] for k, v in s["outcomes"].items()} == {
        "read_correctly": 1, "misread_caught": 1, "misread_not_caught": 1, "misread_noncritical_unflagged": 0}
    assert s["wrong_fields"]["silent_critical"] == 1 and s["wrong_fields"]["caught_by_review"] == 1
    assert s["detection_recall"]["k"] == 1 and s["detection_recall"]["n"] == 2
    # only bins with at least 10 fields are marked interpretable; here just the top one has enough
    assert [b["interpretable"] for b in s["confidence_bins"]] == [False, False, False, True]
    log = ev.misread_log(results)
    assert {m["caught_by"] for m in log} == {"NOT CAUGHT", "review"}


# ------------------------------------------------------------ truth, provenance, and the held-out guard


def test_truth_slip_keeps_blanks_blank():
    t = ev.truth_slip(row(line1_part_number="", line1_unit="", signed="no"))
    assert t["items"][0]["part_number"] == "" and t["items"][0]["unit"] == "" and t["signature"] is False


def test_provenance_records_only_what_is_known():
    data = {"_provenance": {"model": "m", "extracted_on": "2026-11-04"}, "wo_number": field("26-0412"),
            "signature": {"value": True, "confidence": 0.9},
            "items": [{"qty": field("6"), "unit": field(None, 1.0)}, "junk line"]}
    add_provenance(data, "D01.jpeg")
    src = data["wo_number"]["source"]
    assert src["document"] == "D01.jpeg" and src["line"] is None and src["field"] == "wo_number"
    assert src["method"] == "vision" and src["model"] == "m" and src["review_status"] == "unreviewed"
    assert data["items"][0]["qty"]["source"]["line"] == 1
    assert not {"bbox", "box", "x", "y", "coordinates"} & set(src)  # no invented locations
    again = dict(src)
    add_provenance(data, "other.jpeg")
    assert data["wo_number"]["source"] == again  # idempotent: never overwrites


def test_heldout_needs_the_freeze_confirmation():
    with pytest.raises(ev.EvalRefused, match="frozen"):
        ev.run("heldout")


def test_heldout_runs_once(tmp_path, monkeypatch):
    lock = tmp_path / "lock.json"
    lock.write_text("{}")
    monkeypatch.setattr(ev, "LOCK", lock)
    with pytest.raises(ev.EvalRefused, match="already run"):
        ev.run("heldout", confirm_frozen=True)
