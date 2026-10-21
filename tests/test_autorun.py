"""Account run: one process answers the business question for every account, starts by hand or from the schedule, and sends only exceptions to a person."""
import asyncio
import json
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import autorun, salesplan, workbook
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def sample_and_no_schedule(monkeypatch):
    workbook.activate(workbook.sample())
    monkeypatch.setattr(autorun, "STAGE_PACE", 0)
    monkeypatch.setattr(autorun.agents, "pace", lambda s: asyncio.sleep(0))
    yield
    autorun.set_schedule(False)
    workbook.activate(workbook.sample())


def run_all():
    async def go():
        return [e async for e in autorun.run_events()]
    return asyncio.run(go())


def wait_for(run_id, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        r = autorun.get(run_id)
        if r.done:
            return r
        time.sleep(0.05)
    pytest.fail("the run did not finish")


def test_every_company_gets_one_answer_and_one_route():
    events = run_all()
    results = [e["result"] for e in events if e["type"] == "acc_done"]
    companies = {r["company"] for r in workbook.rows()}
    assert len(results) == len(companies) == len({r["ticker"] for r in results})
    done = events[-1]
    assert done["type"] == "run_done" and done["processed"] == len(results)
    assert sum(done["counts"].values()) == len(results)
    for r in results:
        assert r["route"] in autorun.ROUTES


def test_each_account_passes_the_four_agents_in_order():
    events = run_all()
    stages = {}
    for e in events:
        if e["type"] == "acc_stage":
            stages.setdefault(e["ticker"], []).append(e["stage"])
    assert all(s == autorun.STAGES for s in stages.values())


def test_offers_cite_their_evidence_and_cases_fit_the_need():
    for r in (e["result"] for e in run_all() if e["type"] == "acc_done"):
        if not r["offer"]:
            assert r["route"] == "parked" and not r["cases"]
            continue
        assert r["offer"]["key"] in salesplan.PLAYS
        for c in r["cases"]:
            assert c["theme"] == r["offer"]["theme"], "a case for another need never fits"
        if r["route"] == "ready":
            assert r["basis"] == "account" and r["cases"] and r["why"]["id"] in r["sources"]


def test_the_reviewer_sends_exceptions_to_a_person():
    results = {e["result"]["ticker"]: e["result"] for e in run_all() if e["type"] == "acc_done"}
    assert results["UBSG"]["route"] == "review" and any("Cowork" in x for x in results["UBSG"]["reasons"]), "strategic accounts need a sign-off"
    assert results["RO"]["route"] == "review" and any("Sensitive" in x for x in results["RO"]["reasons"]), "a lawsuit headline is read first"
    for r in results.values():
        complete = workbook.by_ticker(r["ticker"])["complete"]
        if not complete and r["offer"]:
            assert r["route"] == "review"
        if r["route"] == "review":
            assert r["reasons"]


def test_an_account_with_its_own_evidence_and_a_case_goes_out_on_its_own():
    results = {e["result"]["ticker"]: e["result"] for e in run_all() if e["type"] == "acc_done"}
    nov = results["NOVN"]
    assert nov["route"] == "ready" and nov["confidence"] == "high"
    assert all(c["passed"] for c in nov["checks"])


def test_the_industry_scan_uses_the_feed_headlines():
    ind = autorun.industry("Financials")
    assert ind["top_theme"] == "cost" and "UBS" in ind["summary"]
    assert all(h["id"].startswith("SIG-") for h in ind["headlines"])
    assert autorun.industry("Real estate")["top_theme"] is None


def test_past_cases_are_marked_synthetic_and_use_known_plays():
    data = autorun.case_file()
    assert "synthetic" in data["source"].lower()
    for c in data["cases"]:
        assert c["play"] in salesplan.PLAYS and c["theme"] in salesplan.THEMES
        assert salesplan.PLAYS[c["play"]]["theme"] == c["theme"]


def test_a_run_started_by_hand_finishes_in_the_background_and_can_be_followed():
    r = client.post("/api/autorun/run", json={"mode": "offline"}).json()
    assert r["started"] and r["run"]["trigger"] == "manual"
    run = wait_for(r["run"]["id"])
    assert run.final["processed"] == run.summary()["processed"]
    with client.stream("GET", f"/api/autorun/stream?run={run.id}") as resp:
        events = [json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data: ") and line != "data: {}"]
    assert events[0]["type"] == "run_start" and events[-1]["type"] == "run_done"
    status = client.get("/api/autorun").json()
    assert status["runs"][0]["id"] == run.id and status["runs"][0]["done"]


def test_the_schedule_starts_a_run_by_itself_when_it_is_due():
    s = client.post("/api/autorun/schedule", json={"enabled": True, "cadence": "demo", "mode": "offline"}).json()
    assert s["enabled"] and 110 <= s["seconds_to_next"] <= 120
    assert autorun._tick(datetime.now()) is None, "not due yet"
    started = autorun._tick(datetime.now() + timedelta(minutes=3))
    assert started and started.trigger == "schedule" and started.by == "Autopilot"
    wait_for(started.id)
    assert autorun.SCHEDULE["next_run"] > datetime.now() + timedelta(minutes=2)
    off = client.post("/api/autorun/schedule", json={"enabled": False}).json()
    assert not off["enabled"] and off["next_run"] is None
    assert autorun._tick(datetime.now() + timedelta(days=1)) is None


def test_daily_and_weekly_runs_fall_at_seven():
    mon = datetime(2026, 10, 19, 8, 0)  # a Monday after 07:00
    assert autorun.next_after("daily", mon) == datetime(2026, 10, 20, 7, 0)
    assert autorun.next_after("weekly", mon) == datetime(2026, 10, 26, 7, 0)
    assert autorun.next_after("weekly", datetime(2026, 10, 19, 6, 0)) == datetime(2026, 10, 19, 7, 0)
