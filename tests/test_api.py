import pytest
from fastapi.testclient import TestClient

from slipcheck.api import app


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    """Every test gets its own shift log, so nothing touches data/runtime/ledger.db."""
    monkeypatch.setenv("SLIPCHECK_DB", str(tmp_path / "ledger.db"))


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def sample(client, name):
    return client.get(f"/api/samples/{name}").json()["slip"]


def test_samples_listed(client):
    names = {s["name"] for s in client.get("/api/samples").json()}
    assert {"01_clean.json", "10_hard_case.json", "12_truncated.json"} <= names


def test_validate_returns_pinned_issues_with_fixes(client):
    slip = client.get("/api/samples/10_hard_case.json").json()["slip"]
    report = client.post("/api/validate", json={"slip": slip}).json()
    assert report["status"] == "BLOCKED"
    closed = next(i for i in report["issues"] if i["code"] == "CLOSED_WO")
    assert closed["key"] == "wo_number" and closed["line"] is None
    assert closed["fixes"][0]["set"] == {"wo_number": "WO-26-0415"}
    unit = next(i for i in report["issues"] if i["code"] == "UNIT_AMBIGUOUS")
    assert (unit["line"], unit["key"]) == (2, "unit")


def test_answering_every_question_makes_hard_case_ready(client):
    """The UI flow: apply one fix per blocking issue, re-validate, end READY."""
    slip = client.get("/api/samples/10_hard_case.json").json()["slip"]
    slip["wo_number"] = "WO-26-0415"
    slip["taken_by"] = "A. Okafor"
    slip["items"][0] |= {"part_number": "EL-2011", "part_name": "Duplex Receptacle 15A White"}
    slip["items"][1] |= {"qty": 1, "unit": "PR"}
    report = client.post("/api/validate", json={"slip": slip}).json()
    assert report["status"] == "READY", report["issues"]


def test_corrupted_sample_comes_back_as_error_not_crash(client):
    body = client.get("/api/samples/12_truncated.json").json()
    assert body["slip"] is None and "not valid JSON" in body["error"]


def test_non_slip_is_422(client):
    assert client.post("/api/validate", json={"slip": [1, 2]}).status_code == 422


def test_sample_path_traversal_is_404(client):
    assert client.get("/api/samples/..%2Fcatalog.csv").status_code == 404


@pytest.mark.parametrize("name", ["..", "...json", "WHAT_TO_WRITE.md"])
def test_odd_sample_names_are_404(client, name):
    assert client.get(f"/api/samples/{name}").status_code == 404


def test_unknown_api_route_is_404_not_the_app_shell(client):
    assert client.get("/api/nope").status_code == 404


def test_ui_route_cannot_read_files_outside_dist(client):
    r = client.get("/..%2F..%2Fslipcheck%2Fapi.py")
    assert "HTTP API for the web UI" not in r.text  # falls back to the app shell instead
    assert r.headers["content-type"].startswith("text/html")


def test_upload_rejects_non_image(client):
    r = client.post("/api/extract", files={"file": ("notes.txt", b"x", "text/plain")})
    assert r.status_code == 422


def test_upload_uses_mock_cache_by_file_name(client):
    r = client.post("/api/extract", files={"file": ("slip_hard_case.png", b"x", "image/png")})
    assert r.json()["slip"]["_provenance"]["kind"] == "hand-authored placeholder"


# ------------------------------------------------------------ shift log (mock inventory)


def test_posting_a_clean_slip_records_it_and_lowers_stock(client):
    r = client.post("/api/post", json={"slip": sample(client, "01_clean.json"), "name": "01_clean.json"})
    assert r.status_code == 200 and r.json()["id"] == 1
    log = client.get("/api/ledger").json()
    assert log["counts"]["posted"] == 1
    elbows = next(s for s in log["stock"] if s["part_number"] == "PL-1001")
    assert (elbows["start"], elbows["posted"], elbows["on_hand"]) == (120, 6, 114)


def test_the_same_slip_cannot_be_posted_twice(client):
    body = {"slip": sample(client, "01_clean.json"), "name": "01_clean.json"}
    assert client.post("/api/post", json=body).status_code == 200
    again = client.post("/api/post", json=body)
    assert again.status_code == 409 and "Already posted" in again.json()["detail"]
    # Re-opening it shows it as posted.
    assert client.post("/api/validate", json=body).json()["posted"]["id"] == 1


def test_blocked_slip_cannot_be_posted(client):
    r = client.post("/api/post", json={"slip": sample(client, "10_hard_case.json"), "name": "10_hard_case.json"})
    assert r.status_code == 409
    assert client.get("/api/ledger").json()["counts"]["posted"] == 0


def test_posted_stock_feeds_the_next_check(client):
    """6 A44 belts on hand: post 4, and a second pull of 4 now exceeds what's left."""
    slip = sample(client, "09_exceeds_on_hand.json")
    slip["items"][0]["qty"] = 4
    assert client.post("/api/post", json={"slip": slip, "name": "belts-1"}).status_code == 200
    slip["date"] = "10/27/2026"  # a different pull, not a duplicate
    codes = {i["code"] for i in client.post("/api/validate", json={"slip": slip}).json()["issues"]}
    assert "EXCEEDS_ON_HAND" in codes


def test_shift_log_counts_holds_reviews_and_caught(client):
    for name in ("10_hard_case.json", "17_name_contradicts_number.json", "13_custodial_restock.json"):
        client.post("/api/validate", json={"slip": sample(client, name), "name": name})
    counts = client.get("/api/ledger").json()["counts"]
    assert counts["checked"] == 3
    assert counts["on_hold"] == 2
    assert counts["needs_review"] == 1  # hard case has an illegible name
    assert counts["ready_unposted"] == 1
    assert counts["caught"] == 5  # 4 on the hard case + 1 mismatch


def test_answers_are_kept_with_the_posting(client):
    slip = sample(client, "02_closed_wo.json")
    slip["wo_number"] = "WO-26-0412"
    r = client.post("/api/post", json={"slip": slip, "name": "02_closed_wo.json",
                                       "answers": ["W/O number: WO-26-0412, Harlow Hall"]})
    assert r.json()["answers"] == ["W/O number: WO-26-0412, Harlow Hall"]
    assert client.get("/api/ledger").json()["counts"]["resolved_at_counter"] == 1


def test_clearing_the_shift_log_restores_stock(client):
    client.post("/api/post", json={"slip": sample(client, "01_clean.json"), "name": "01_clean.json"})
    log = client.post("/api/ledger/reset").json()
    assert log["counts"]["posted"] == 0 and log["stock"] == []
