"""Sales plan: the Cowork shortlist checked against the evidence, competitors, Microsoft plays, seller days and the plan assistant."""
import asyncio
import json
import re

import pytest
from fastapi.testclient import TestClient

from app import chat, reports, salesplan, signals, workbook
from app.config import STATIC
from app.main import app

client = TestClient(app)
CTX = {"tickers": ["UBSG", "VACN", "CLN"], "focus": "UBSG", "days": 20}


@pytest.fixture(autouse=True)
def sample_workbook():
    workbook.activate(workbook.sample())
    yield
    workbook.activate(workbook.sample())


@pytest.fixture
def with_reports(monkeypatch):
    """The report figures as on a machine that has the PDFs (the figures themselves are in financials.json)."""
    docs = reports.manifest()["documents"]
    for d in docs:
        monkeypatch.setitem(d, "available", True)


def run(message, **kw):
    async def go():
        return [e async for e in salesplan.plan_events(message, **kw)]
    events = asyncio.run(go())
    return events, next(e for e in events if e["type"] == "answer")


# ----------------------------------------------------------------------------- shortlist and evidence

def test_the_cowork_shortlist_names_companies_in_the_sample_workbook_with_known_themes():
    accounts = salesplan.shortlist_file()["accounts"]
    assert [a["ticker"] for a in accounts] == ["UBSG", "VACN", "CLN"]
    assert all(workbook.by_ticker(a["ticker"]) and a["theme"] in salesplan.THEMES and a["hypothesis"] for a in accounts)
    assert salesplan.default_tickers() == ["UBSG", "VACN", "CLN"]


def test_evidence_is_real_headlines_quoted_word_for_word_and_never_price_moves():
    feed = {e["id"]: e for e in signals.feed()}
    for t in CTX["tickers"]:
        for i in salesplan.evidence(t):
            e = feed[i["id"]]
            assert e["kind"] == "news" and e["ticker"] == t
            assert f"“{e['headline']}”" in i["text"] and e["source"] in i["text"]
    assert "SIG-111" in feed and feed["SIG-111"]["kind"] == "quote"
    assert "SIG-111" not in {i["id"] for i in salesplan.evidence("UBSG")}, "the 11.5% price drop says nothing about demand"


def test_hypotheses_are_checked_against_the_feed():
    ubs = salesplan.check_hypothesis("UBSG")
    assert ubs["status"] == "Evidence found" and {i["id"] for i in ubs["supports"]} == {"SIG-046", "SIG-112"}
    assert salesplan.check_hypothesis("VACN")["status"] == "Evidence found"
    assert {i["id"] for i in salesplan.check_hypothesis("CLN")["supports"]} == {"SIG-028"}
    assert salesplan.check_hypothesis("NOVN")["status"] == "No Cowork hypothesis"


def test_report_figures_can_contradict_cowork(with_reports):
    vat = salesplan.check_hypothesis("VACN")
    assert vat["status"] == "Mixed evidence", "Q3 news says sales grow, the H1 report says they fell"
    counter = vat["counters"][0]
    assert counter["id"] == "REP-VACN-p2" and "-8.3%" in counter["text"]
    cln = {i["theme"]: i for i in salesplan.evidence("CLN") if i["kind"] == "report"}
    assert "7.0% to 9.8%" in cln["cost"]["text"] and "sales fell" in cln["cost"]["text"]
    assert [p["key"] for p in salesplan.plays_for("VACN")] == ["scale", "finops"]


def test_every_play_has_a_theme_products_a_pitch_and_a_proof_page_in_the_app():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for key, p in salesplan.PLAYS.items():
        assert p["theme"] in salesplan.THEMES and p["products"] and p["pitch"] and len(p["questions"]) >= 2
        assert f"{p['proof']['page']}:" in js.split("const VIEWS = {")[1].split("}")[0] or p["proof"]["page"] == "overview"


def test_ubs_gets_the_finops_play_first_with_evidence_and_cowork_agreeing():
    plays = salesplan.plays_for("UBSG")
    assert plays[0]["key"] == "finops" and plays[0]["fit"] == "Evidence and Cowork agree"
    assert "Model router in Microsoft Foundry" in plays[0]["products"]
    assert {p["key"] for p in plays} == {"finops", "resilience"}


# ----------------------------------------------------------------------------- priorities and seller days

def test_seller_days_follow_priority_and_add_up():
    ov = salesplan.overview(CTX["tickers"], 20)
    days = {a["ticker"]: a["days"] for a in ov["accounts"]}
    assert sum(days.values()) == 20
    assert ov["order"][0] == "UBSG" and days["UBSG"] == max(days.values())
    for a in ov["accounts"]:
        assert a["priority"] == sum(a["priority_parts"].values()) and 0 <= a["priority"] <= 10


def test_allocation_is_largest_remainder_and_skips_accounts_without_priority():
    accs = [{"ticker": "A", "priority": 5}, {"ticker": "B", "priority": 3}, {"ticker": "C", "priority": 0}]
    assert salesplan.allocate(accs, 8) == {"A": 5, "B": 3, "C": 0}
    assert sum(salesplan.allocate(accs, 7).values()) == 7
    assert salesplan.allocate([{"ticker": "A", "priority": 0}], 10) == {"A": 0}
    assert sum(salesplan.allocate(accs, 999).values()) == salesplan.MAX_DAYS


def test_another_workbook_without_the_shortlist_falls_back_to_the_strongest_companies(monkeypatch, tmp_path):
    monkeypatch.setattr(salesplan, "SHORTLIST_PATH", tmp_path / "missing.json")
    top = [r["ticker"] for r in chat.t_rank_companies("score", "desc", 3)["ranking"]]
    assert salesplan.default_tickers() == top
    assert all(a["hypothesis"]["status"] == "No Cowork hypothesis" for a in salesplan.overview()["accounts"])


# ----------------------------------------------------------------------------- competitors and talk track

def test_competitors_are_sector_peers_with_a_rank_and_shared_themes():
    c = salesplan.competitors("UBSG")
    assert c["sector"] == "Financials" and all(workbook.by_ticker(p["ticker"])["sector"] == "Financials" for p in c["peers"])
    assert c["rank_in_sector"] == 1 and c["of_sector"] == len(c["peers"]) + 1
    cost = next(s for s in c["shared_themes"] if s["theme"] == "cost")
    assert cost["peers"] == ["PGHN"] and cost["account_has_it"], "Partners Group cutting jobs makes cost a sector theme"
    assert set(re.findall(r"SIG-\d+|SEC-\d+", json.dumps(c))) <= set(c["sources"])
    assert salesplan.competitors("NOPE") == {"error": "Unknown ticker NOPE. Use find_company first."}


def test_talk_track_opens_with_evidence_and_brings_a_peer_angle():
    t = salesplan.talk_track("UBSG")
    assert t["play"] == "finops" and t["opener"]["id"] == "SIG-046"
    assert t["peer_angle"]["id"] == "SIG-098" and t["proof"]["page"] == "bakeoff"
    assert set(t["sources"]) == {"SIG-046", "SIG-098"}


# ----------------------------------------------------------------------------- the plan assistant

@pytest.mark.parametrize("message,intent", [
    ("We only have 12 seller days this quarter. Where should they go?", "priority"),
    ("Where should we start?", "priority"),
    ("Does the Cowork hypothesis for UBS hold up?", "hypo"),
    ("Check all Cowork hypotheses", "hypo_all"),
    ("How does UBS compare with its competitors?", "competitors"),
    ("Compare UBS and Julius Baer", "compare"),
    ("Which Microsoft play fits UBS?", "plays"),
    ("How do we position FinOps at Clariant?", "plays"),
    ("Draft the first meeting with UBS", "talk"),
    ("Build the sales plan for all three accounts", "build_all"),
    ("Add the best play for VAT to the plan", "build"),
    ("Should I buy UBS shares?", "advice"),
    ("Is UBS ready to buy?", "intent"),
    ("hello", "help"),
])
def test_the_offline_router_understands_the_demo_questions(message, intent):
    assert salesplan.plan_offline(message, CTX)[0] == intent


def test_the_assistant_moves_the_seller_capacity_on_screen_and_answers_from_the_shortlist():
    events, a = run("We only have 12 seller days this quarter. Where should they go?", tickers=CTX["tickers"], days=20)
    assert {"type": "action", "action": "set_days", "days": 12} in events
    days = [int(x) for x in re.findall(r"(\d+) days?, priority", a["text"])]
    assert sum(days) == 12 and "UBS" in a["text"].split("\n")[1]
    assert not a["checks"]["unknown_sources"] and not a["checks"]["ungrounded"] and set(a["checks"]["cited"]) <= set(a["sources"])


def test_the_assistant_shows_the_account_it_talks_about():
    events, a = run("How does Clariant compare with its competitors?", tickers=CTX["tickers"], focus="UBSG")
    assert {"type": "action", "action": "show", "ticker": "CLN", "view": "competitors"} in events
    assert "[SEC-" in a["text"] and not a["checks"]["unknown_sources"]
    assert any("Clariant" in f for f in a["followups"]), "follow-ups move with the conversation"


def test_building_the_plan_adds_one_play_per_account_with_its_reason():
    events, a = run("Build the sales plan for all three accounts", tickers=CTX["tickers"])
    added = [(e["ticker"], e["play"]) for e in events if e["type"] == "action" and e["action"] == "add_play"]
    assert added == [("UBSG", "finops"), ("VACN", "scale"), ("CLN", "integration")]
    assert set(a["checks"]["cited"]) == {"SIG-046", "SIG-114", "SIG-028"}


def test_every_answer_is_grounded_and_free_of_advice():
    for q in ["Does the Cowork hypothesis for VAT hold up?", "Which Microsoft play fits UBS?", "Draft the first meeting with VAT", "Check all Cowork hypotheses"]:
        _events, a = run(q, tickers=CTX["tickers"])
        assert a["checks"]["cited"] and not a["checks"]["unknown_sources"] and not a["checks"]["ungrounded"], q
        assert not a["blocked"] and not a["live"]


def test_advice_and_purchase_intent_are_not_answered():
    _e, a = run("Should I buy UBS shares?")
    assert "can't give investment advice" in a["text"]
    _e, a = run("Is UBS ready to buy?")
    assert "not purchase intent" in a["text"]


def test_tool_specs_cover_every_tool_and_ui_actions_are_tools():
    names = {s["function"]["name"] for s in salesplan.TOOL_SPECS}
    assert names == set(salesplan.TOOLS) and salesplan.UI_ACTIONS <= names
    json.dumps(salesplan.TOOL_SPECS)


# ----------------------------------------------------------------------------- API

def test_plan_api_returns_the_shortlist_and_respects_the_requested_accounts():
    r = client.get("/api/plan").json()
    assert [a["ticker"] for a in r["accounts"]] == ["UBSG", "VACN", "CLN"] and r["days"] == 20 and len(r["suggestions"]) == 6
    assert set(re.findall(r"SIG-\d+", json.dumps(r["accounts"]))) <= set(r["sources"])
    r = client.get("/api/plan?tickers=UBSG,NOVN,BOGUS&days=10").json()
    assert [a["ticker"] for a in r["accounts"]] == ["UBSG", "NOVN"] and sum(a["days"] for a in r["accounts"]) == 10


def test_plan_competitor_and_talk_endpoints():
    assert client.get("/api/plan/competitors?ticker=VACN").json()["sector"] == "Industrials"
    assert client.get("/api/plan/competitors?ticker=XXX").status_code == 404
    assert client.get("/api/plan/talk?ticker=UBSG&play=resilience").json()["play"] == "resilience"


def test_plan_chat_streams_actions_and_an_answer():
    body = client.post("/api/plan/chat/stream", json={"message": "Which Microsoft play fits VAT?", "tickers": CTX["tickers"], "focus": "UBSG"}).text
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ") and line != "data: {}"]
    assert {"type": "action", "action": "show", "ticker": "VACN", "view": "plays"} in events
    assert events[-1]["type"] == "done" and any(e["type"] == "answer" for e in events)
