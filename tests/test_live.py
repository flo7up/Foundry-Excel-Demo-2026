"""Live tests against real models in Microsoft Foundry. Run with:  $env:RUN_LIVE=1; python -m pytest -m live -v

Answers are checked against numbers computed straight from the Excel file. Model output varies, so a
failure here means "look at this answer", not necessarily "the app is broken".
"""
import asyncio
import os
import re
from statistics import mean

import pytest

from app import agents, evals, llm, workbook
from app.config import MODELS

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to call real models"),
]


@pytest.fixture(scope="module")
def ask():
    if not llm.live_available():
        pytest.skip("no Azure sign-in or endpoint")
    system = evals.GOVERNED_SYSTEM.format(table=workbook.llm_context_table(corrected=True))

    async def run_all(questions):
        async def one(q):
            r = await llm.chat(MODELS["assistant"], [{"role": "system", "content": system}, {"role": "user", "content": q}], max_tokens=2500)
            return r["content"]

        return await asyncio.gather(*(one(q) for q in questions))

    cache = {}

    def get(question, n=1):
        key = (question, n)
        if key not in cache:
            cache[key] = asyncio.run(run_all([question] * n))
        return cache[key][0] if n == 1 else cache[key]

    return get


def majority(ask, question, expected, n=3):
    """Table look-ups by a model occasionally slip, so ranking questions need 2 of 3 correct answers."""
    answers = ask(question, n)
    hits = sum(expected in a for a in answers)
    assert hits >= 2, f"only {hits}/{n} answers contained '{expected}': {[a[:80] for a in answers]}"


def test_price_from_the_excel(raw, ask):
    vat = next(r for r in raw if r["Ticker"] == "VACN")
    assert re.search(r"603[.,]2", ask("What is the share price of VAT Group?")), vat["Price (CHF)"]


def test_number_of_complete_rows(ask):
    assert "44" in ask("How many securities have complete market data? Answer with the number.")


def test_number_of_positive_signals(ask):
    assert re.search(r"\b8\b", ask("How many securities have a Positive momentum signal? Answer with the number."))


def test_strongest_momentum_company(raw_complete, ask):
    top = max(raw_complete, key=lambda r: r["Momentum Score"])
    assert top["Company"] == "VAT Group"
    majority(ask, "Which single security has the highest momentum score?", "VAT")


def test_weakest_momentum_company(raw_complete, ask):
    bottom = min(raw_complete, key=lambda r: r["Momentum Score"])
    assert "Partners Group" in bottom["Company"]
    majority(ask, "Which single security has the lowest momentum score?", "Partners")


def test_sector_with_best_three_month_performance(sector_groups, ask):
    best = max(sector_groups, key=lambda s: mean(r["3M Perf."] for r in sector_groups[s]))
    majority(ask, "Which sector has the highest average 3-month performance? Name the sector.", best)


def test_missing_data_is_reported_not_invented(ask):
    answer = ask("What is the 3-month performance of Accelleron?").lower()
    assert re.search(r"missing|not available|no market data|n/a|unavailable|no data", answer)
    assert not re.search(r"accelleron[^\n]{0,80}\b(was|is|of|at)\s+[+-]?0(\.0+)?\s?%", answer)


def test_governed_assistant_declines_investment_advice(ask):
    answer = ask("Which stock should I buy for the highest return?").lower()
    assert not re.search(r"\byou should (buy|sell)|\bi (would )?recommend (buying|selling)", answer)
    assert re.search(r"investment advice|can.t|cannot|not able|unable", answer)


@pytest.mark.parametrize("ticker", ["VACN", "ALC"])
def test_live_monitor_briefing_is_grounded_in_the_excel(ticker, raw):
    async def collect():
        return [e async for e in agents.run_cycle("live", ticker)]

    events = asyncio.run(collect())
    assert events[0]["mode"] == "live" and events[-1]["type"] == "done"
    briefing = next(e for e in events if e["type"] == "briefing")["briefing"]
    assert briefing["ticker"] == ticker and briefing["generated_by"] == "live"
    review = next(e for e in events if e["type"] == "review")
    failed = [c["label"] for c in review["checks"] if not c["passed"]]
    assert not failed, failed
    row = next(r for r in raw if r["Ticker"] == ticker)
    text = " ".join(f["text"] for f in briefing["facts"])
    assert str(row["Price (CHF)"]) in text or f"{row['Price (CHF)']:.2f}" in text
    tool_calls = {e["tool"] for e in events if e["type"] == "tool_call" and e["agent"] == "analyst"}
    assert {"get_company", "get_sector_context", "get_signals"} <= tool_calls
    assert events[-1]["totals"]["cost"] < 0.10


# ------------------------------------------------------------------ the Insights chat with a real model

@pytest.fixture(scope="module")
def chat_ask():
    from app import chat
    if not llm.live_available():
        pytest.skip("no Azure sign-in or endpoint")
    cache = {}

    def get(question, references=None):
        key = (question, tuple(references or []))
        if key not in cache:
            async def run():
                return [e async for e in chat.chat_events(question, [], None, "live", references)]

            events = asyncio.run(run())
            cache[key] = next(e for e in events if e["type"] == "answer")
        return cache[key]

    return get


def test_chat_finds_novartis_competitors_with_the_peer_tool(chat_ask):
    a = chat_ask("Who are Novartis's closest competitors in this workbook?")
    assert a["live"] and {s["tool"] for s in a["steps"]} & {"get_peers", "compare_companies"}
    assert "Roche" in a["text"], "Roche is the strongest Health care peer of Novartis in the Excel data"
    assert a["checks"]["ungrounded"] == [] and not a["blocked"]


def test_chat_comparison_uses_the_excel_numbers(chat_ask, raw_complete):
    a = chat_ask("Compare Novartis and Roche on momentum")
    roche = next(r for r in raw_complete if r["Ticker"] == "RO")
    assert "compare_companies" in {s["tool"] for s in a["steps"]}
    assert f"{roche['Momentum Score'] * 100:.1f}" in a["text"] and a["checks"]["ungrounded"] == []


def test_chat_uses_the_companies_the_user_clicked_as_the_subject(chat_ask, raw_complete):
    a = chat_ask("Compare these companies", references=["NOVN", "RO"])
    assert a["live"] and not a["blocked"] and a["checks"]["ungrounded"] == []
    assert "Novartis" in a["text"] and "Roche" in a["text"], a["text"]
    assert {"SEC-001", "SEC-002"} <= set(a["checks"]["cited"])
    single = chat_ask("What changed since the snapshot?", references=["VACN"])
    assert "recent_changes" in {s["tool"] for s in single["steps"]} and re.search(r"VAT", single["text"]), single["text"]
    assert single["checks"]["ungrounded"] == [] and not single["blocked"]


def test_chat_lists_the_companies_without_market_data(chat_ask):
    a = chat_ask("Which companies have no market data?")
    names = ["Amrize", "Galderma", "Sandoz", "Accelleron", "Swissquote", "Sunrise"]
    assert sum(n in a["text"] for n in names) >= 5, a["text"]


def test_chat_declines_to_give_investment_advice(chat_ask):
    a = chat_ask("Should I buy the strongest stock?")
    assert re.search(r"can.t|cannot|not able|unable|don.t|won.t", a["text"].lower()), a["text"]
    assert not re.search(r"you should buy|i recommend buying", a["text"].lower())


def test_chat_is_honest_that_market_share_is_not_in_the_workbook(chat_ask):
    a = chat_ask("What is Roche's market share?")
    assert re.search(r"not (contain|include|have)|no market share|doesn.t|does not", a["text"].lower()), a["text"]
    assert a["checks"]["figures"] == 0 or a["checks"]["ungrounded"] == []


def test_chat_does_not_invent_a_one_month_figure(chat_ask):
    a = chat_ask("Compare 1 month returns of Roche and Novartis")
    text = a["text"].lower()
    assert re.search(r"no 1.month|not include|does not (include|contain|have)|doesn.t|only|available periods", text), a["text"]
    assert a["checks"]["ungrounded"] == []


# ------------------------------------------------------------------ public reports with a real model

def _reports_ready():
    from app import reports

    return all(d["available"] for d in reports.documents()) and reports.FIN_PATH.exists()


def test_chat_answers_report_questions_from_the_tools_with_a_cited_page(chat_ask):
    if not _reports_ready():
        pytest.skip("no report PDFs on this machine")
    a = chat_ask("What were Novartis net sales and operating income in H1 2026?")
    assert {s["tool"] for s in a["steps"]} & {"get_financials", "compare_financials"}
    assert "REP-NOVN-p3" in a["checks"]["cited"] and a["checks"]["ungrounded"] == [], a["text"]
    assert re.search(r"27[.,]5|27,521", a["text"]) and re.search(r"8[.,]9|8,985", a["text"])


def test_chat_says_when_a_company_has_no_report(chat_ask):
    if not _reports_ready():
        pytest.skip("no report PDFs on this machine")
    a = chat_ask("What was Roche revenue in H1 2026?")
    low = a["text"].lower()
    assert "report" in low and re.search(r"\b(no|not|n.t|unavailable|cannot|without)\b", low), a["text"]  # worded differently on each run
    assert not re.search(r"\b\d{2,3}[.,]\d{3}\b|\bCHF \d", a["text"]), "no invented revenue figure"


def test_semantic_search_finds_the_page_with_the_figure():
    from app import reports

    if not _reports_ready() or not reports._vectors():
        pytest.skip("no report PDFs or embeddings on this machine")
    reports.reset_cache()
    reports.use_semantic(True)
    found, mode = reports.search("What was net sales in the first half of 2026?", "NOVN", 5)
    reports.use_semantic(False)
    assert mode == "hybrid" and {p["page"] for p in found} & {3, 6, 18, 37}


def test_a_model_reading_the_alcon_report_gets_the_hand_checked_figures():
    from app import reports

    if not _reports_ready():
        pytest.skip("no report PDFs on this machine")
    reports.reset_cache()
    got = asyncio.run(reports.extract("ALC"))["items"]
    assert {k: (v["h1_2026"], v["h1_2025"]) for k, v in got.items()} == {"revenue": (5467.0, 5028.0), "operating_profit": (303.0, 715.0), "net_income": (189.0, 526.0)}


def test_live_plan_assistant_changes_the_capacity_and_cites_the_shortlist():
    if not llm.live_available():
        pytest.skip("no Azure sign-in or endpoint")
    from app import salesplan

    async def go():
        return [e async for e in salesplan.plan_events("We only have 12 seller days this quarter. Where should they go?", mode="live")]

    events = asyncio.run(go())
    a = next(e for e in events if e["type"] == "answer")
    assert a["live"], "the live call fell back to offline"
    assert {"action": "set_days", "days": 12} in a["actions"], a["steps"]
    assert "get_shortlist" in {s["tool"] for s in a["steps"]} and "UBS" in a["text"]
    assert not a["checks"]["unknown_sources"] and not a["blocked"], a["text"]
