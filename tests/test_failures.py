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


@pytest.mark.parametrize("split", ["heldout_corrected", "heldout_locked", "dev"])
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
