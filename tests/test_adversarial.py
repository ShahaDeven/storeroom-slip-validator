from slipcheck import adversarial as adv
from slipcheck import ledger

# The cases that document failures we know about. If one of these starts passing, the fix is
# real: move it out of this set and drop its known_gap text. If a new one appears, it's a regression.
KNOWN_GAPS = {"A7", "S2", "S3", "S4"}


def test_every_case_behaves_as_recorded():
    s = adv.run_suite()
    by_verdict = {r["id"]: r["verdict"] for r in s["cases"]}
    assert s["counts"]["regression"] == 0, [r["id"] for r in s["cases"] if r["verdict"] == "regression"]
    assert {i for i, v in by_verdict.items() if v == "known_gap"} == KNOWN_GAPS


def test_known_gaps_are_the_only_things_that_got_in():
    s = adv.run_suite()
    assert {r["id"] for r in s["cases"] if r["got_in"]} <= KNOWN_GAPS
    for r in s["cases"]:
        if r["verdict"] == "known_gap":
            assert r["known_gap"], f"{r['id']} needs an explanation"


def test_suite_never_touches_the_real_ledger(tmp_path, monkeypatch):
    real = tmp_path / "real.db"
    monkeypatch.setenv("SLIPCHECK_DB", str(real))
    adv.run_suite()
    assert ledger.db_path() == real and not real.exists()


def test_case_ids_are_unique_and_each_ends_in_an_attempt():
    ids = [c.id for c in adv.CASES]
    assert len(ids) == len(set(ids))
    assert all(c.steps and c.expect in {"posted", "posted_with_warnings", "blocked", "needs_review", "refused"}
               for c in adv.CASES)


def test_the_api_runs_the_suite():
    from fastapi.testclient import TestClient
    from slipcheck.api import app

    body = TestClient(app).get("/api/adversarial").json()
    assert body["total"] == len(adv.CASES) and body["counts"]["regression"] == 0
