import pytest

from slipcheck import failures as fl


@pytest.mark.parametrize("paper, read, kind", [
    ("h. santos", "h.santos", "spacing or punctuation only"),
    ("10/14/26", "10/4/26", "digit misread or dropped"),
    ("knox hall", "knox mall", "letters misread"),
    ("flapper", "hopper", "letters misread"),
    ("gloves", "", "read as blank"),
    ("", "3", "read where the paper is blank"),
    ("ballcock", "wire nut", "different word"),
])
def test_error_kinds(paper, read, kind):
    assert fl.error_kind(paper, read) == kind


@pytest.mark.parametrize("split", ["heldout_corrected", "heldout_locked", "dev", "dev_v2", "heldout_corrected_v2"])
def test_analysis_agrees_with_the_eval_summary(split):
    """The dashboard must show the same numbers as EVAL.md, which come from the eval summary."""
    a = fl.analyze(split)
    _, report = fl.load(split)
    rp = report["summary"]["reaches_posting"]
    assert a["tiles"]["posting_wrong_critical"]["k"] == rp["slips_with_wrong_critical_value"]["k"]
    assert a["tiles"]["posting_wrong_any"]["k"] == rp["slips_with_any_wrong_value"]["k"]
    assert a["tiles"]["slips_reviewed"]["k"] == report["summary"]["review_rate"]["k"]
    assert sum(m["posted"] for m in a["misses"]) == rp["wrong_fields"]
    assert sum(r["wrong"] for r in a["by_field"]) == report["summary"]["wrong_fields"]["total"]
    assert sum(b["correct"] + b["wrong"] for b in a["confidence"]["bins"]) + a["confidence"]["below"] \
        + a["confidence"]["no_confidence"] == sum(len(s["fields"]) for s in report["slips"])


def test_every_unstopped_misread_is_listed_and_none_is_stopped():
    a = fl.analyze("heldout_corrected")
    assert a["misses"] and all(m["fate"] in ("warned_only", "nothing_raised") for m in a["misses"])
    assert all(r["stopped"] + r["warned_only"] + r["nothing_raised"] == r["wrong"] for r in a["by_field"])


def test_unknown_split_is_refused():
    with pytest.raises(fl.NoResults):
        fl.analyze("everything")


def test_the_api_serves_it():
    from fastapi.testclient import TestClient
    from slipcheck.api import app

    c = TestClient(app)
    assert c.get("/api/eval/failures").json()["split"] == "heldout_corrected"
    assert c.get("/api/eval/failures?split=nope").status_code == 404


def test_false_positives_separate_what_stops_from_what_only_warns():
    """A warning on a correct read doesn't stop posting, so it must not be counted with reviews and blocks."""
    a = fl.analyze("heldout_corrected")
    _, report = fl.load("heldout_corrected")
    correct = [f for s in report["slips"] for f in s["fields"] if f["correct"]]
    t = a["false_positive_totals"]
    assert t["rule_blocks"] == sum(f["new_block"] and not f["review"] for f in correct)
    assert t["rule_warnings"] == sum(f["new_flag"] and not f["new_block"] and not f["review"] for f in correct)
    assert t["reviews"] == a["unnecessary_reviews"]["k"]


def test_drill_down_returns_the_photo_the_reading_came_from():
    corrected = fl.slip_detail("heldout_corrected", "H02")
    locked = fl.slip_detail("heldout_locked", "H02")
    assert corrected["photo_of"] == "H03" and locked["photo_of"] == "H02"  # the recorded swap
    assert corrected["reading"] and {"name", "truth", "read"} <= set(corrected["fields"][0])
    assert fl.photo_path("H14").name == "H14.jpeg"
    with pytest.raises(fl.NoResults):
        fl.slip_detail("dev", "H99")


def test_the_drill_down_api_and_photo():
    from fastapi.testclient import TestClient
    from slipcheck.api import app

    c = TestClient(app)
    assert c.get("/api/eval/slip", params={"split": "heldout_corrected", "slip": "H14"}).json()["slip"] == "H14"
    assert c.get("/api/eval/photo/H14").headers["content-type"].startswith("image/")
    assert c.get("/api/eval/photo/..%2Fsecret").status_code == 404
