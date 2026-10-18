"""The monitoring feed is real (cached Yahoo Finance closes and Google News headlines) and must be consistent with the workbook; the offline agent pipeline must behave on every company."""
import asyncio
import itertools
import re

import pytest

from app import agents, signals, workbook
from app import feed as public_feed
from tests.conftest import MISSING_TICKERS


@pytest.fixture(autouse=True)
def fast_agents(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(agents, "pace", instant)


# ------------------------------------------------------------------ the cached public feed

def test_cache_holds_real_quote_series_and_news_for_every_security(raw):
    cache = public_feed.load()
    assert cache["retrieved_at"] and set(cache["tickers"]) >= {r["Ticker"] for r in raw}
    for ticker, entry in cache["tickers"].items():
        series = entry["quote"]["series"]
        assert entry["quote"]["currency"] == "CHF" and len(series) > 20, ticker
        assert [d for d, _ in series] == sorted(d for d, _ in series) and all(c > 0 for _, c in series), ticker
        for n in entry["news"]:
            assert n["title"] and n["source"] and n["url"].startswith("http") and re.fullmatch(r"\d{4}-\d\d-\d\d", n["date"]), ticker


def test_workbook_prices_match_the_real_close_on_the_snapshot_date():
    check = signals.baseline_check()
    off = {c["ticker"] for c in check if not c["matches"]}
    assert len(check) == 44 and len(check) - len(off) >= 40, "the workbook prices should be real closing prices"
    assert off <= {"RO", "ROP"}, "only the two Roche lines may differ from the Yahoo symbols"


def test_share_classes_share_one_set_of_news():
    news = [e["headline"] for e in signals.feed() if e["kind"] == "news"]
    assert len(news) == len(set(news)), "the same headline must not appear for two share classes"


# ------------------------------------------------------------------ events built from the cache

def test_events_have_unique_ids_named_sources_and_dates_after_the_snapshot(raw):
    ev = signals.feed()
    tickers = {r["Ticker"] for r in raw}
    latest = public_feed.load()["retrieved_at"][:10]
    assert ev and len({e["id"] for e in ev}) == len(ev)
    for e in ev:
        assert e["ticker"] in tickers and re.fullmatch(r"SIG-\d{3}", e["id"]), e["id"]
        assert e["kind"] in ("news", "quote") and e["source"] and e["url"].startswith("https://"), e["id"]
        assert "2026-08-28" < e["date"] <= latest, e["id"]


def test_price_events_match_the_cached_quote_and_the_workbook_price(raw):
    price = {r["Ticker"]: r["Price (CHF)"] for r in raw}
    cache = public_feed.load()["tickers"]
    quotes = [e for e in signals.feed() if e["kind"] == "quote"]
    assert quotes
    for e in quotes:
        last_day, last_close = cache[e["ticker"]]["quote"]["series"][-1]
        change = last_close / price[e["ticker"]] - 1
        assert e["price"] == pytest.approx(last_close, abs=0.01) and e["date"] == last_day, e["id"]
        assert f"CHF {price[e['ticker']]:.2f}" in e["detail"] and f"CHF {last_close:.2f}" in e["detail"], e["id"]
        assert ("above" in e["headline"]) == (change > 0) and abs(change) * 100 >= signals.PRICE_EVENT_MIN - 0.05, e["id"]


def test_news_events_are_real_headlines_from_the_cache_and_not_noise():
    titles = {(t, n["title"], n["url"]) for t, entry in public_feed.load()["tickers"].items() for n in entry["news"]}
    news = [e for e in signals.feed() if e["kind"] == "news"]
    assert news
    for e in news:
        assert (e["ticker"], e["headline"], e["url"]) in titles, e["id"]
        assert not public_feed.is_noise(e["headline"], e["source"]), e["id"]
        assert signals.classify(e["headline"]) == (e["type"], e["severity"]), e["id"]


def test_at_most_two_news_events_per_company():
    per = {}
    for e in signals.feed():
        if e["kind"] == "news":
            per[e["ticker"]] = per.get(e["ticker"], 0) + 1
    assert per and max(per.values()) <= signals.NEWS_PER_COMPANY


def test_compare_is_consistent_with_the_events_and_the_workbook(raw):
    price = {r["Ticker"]: r["Price (CHF)"] for r in raw}
    changes = signals.compare()
    assert changes and any(c["material"] for c in changes)
    for c in changes:
        delta = c["price_delta_pct"]
        assert c["material"] == (c["max_severity"] == 3 or (delta is not None and abs(delta) >= signals.MATERIAL_PRICE_MOVE)), c["ticker"]
        if delta is not None:
            latest = max((e for e in signals.events_for(c["ticker"]) if "price" in e), key=lambda e: e["date"])
            assert delta == pytest.approx((latest["price"] / price[c["ticker"]] - 1) * 100, abs=0.06)
        assert c["top"]["url"].startswith("https://") and c["top"]["id"] in {e["id"] for e in c["events"]}


@pytest.mark.parametrize("headline, expected", [
    ("Lonza sets new mid-term targets, confirms 2026 outlook", ("guidance_change", "high")),
    ("UBS raises target for Barry Callebaut stock to CHF 1,180.00", ("analyst_note", "medium")),
    ("Georg Fischer's Board to Nominate New Chair", ("management_change", "high")),
    ("Swiss telecoms operator Sunrise mulls 450 job cuts", ("restructuring", "high")),
    ("Sika Acquires Azpects in the UK", ("deal", "medium")),
    ("Court throws out CHF18m Swisscom fine in fibre-optic dispute", ("regulatory", "medium")),
    ("Clariant stock reports 0.6 percent Q2 sales growth", ("trading_update", "medium")),
    ("Logitech Unveils New Enterprise Video Collaboration Lineup", ("product_update", "low")),
    ("Holcim Egypt appoints sustainability director", None),
    ("Amrize donates to outdoor fitness court", None),
    ("Sonova CEO sees new need for hearing aid documentation", None),
])
def test_headlines_are_classified_by_what_they_report(headline, expected):
    assert signals.classify(headline) == expected


def test_stock_quote_pages_and_valuation_spam_are_not_news():
    for title, source in [("SLHN Stock Price and Chart - SIX:SLHN", "TradingView"), ("Belimo stock has a 46.5 price-to-earnings ratio", "Investing.com"),
                          ("Alcon (ALC) Stock Forecast and Price Target 2026", "MarketBeat")]:
        assert public_feed.is_noise(title, source), title
    assert not public_feed.is_noise("VAT Group sees 2027 sales well above its guidance as AI demand surges", "Investing.com")


# ------------------------------------------------------------------ deterministic scenario with a tiny feed

_stamps = itertools.count()


def tiny_feed(monkeypatch, news):
    data = {"retrieved_at": f"test-feed-{next(_stamps)}", "sources": {}, "tickers": {
        "NOVN": {"quote": {"symbol": "NOVN.SW", "currency": "CHF", "url": "https://finance.yahoo.com/quote/NOVN.SW",
                           "series": [["2026-08-28", 123.74], ["2026-10-15", 140.0]]}, "news": news},
        "NESN": {"quote": {"symbol": "NESN.SW", "currency": "CHF", "url": "https://finance.yahoo.com/quote/NESN.SW",
                           "series": [["2026-08-28", 78.62], ["2026-10-15", 79.0]]}, "news": []}}}
    monkeypatch.setattr(public_feed, "load", lambda: data)


def item(title, day="2026-10-01", source="Reuters"):
    return {"title": title, "source": source, "date": day, "url": "https://example.org/" + title[:8].replace(" ", "-")}


def test_tiny_feed_builds_exactly_the_expected_events(monkeypatch):
    tiny_feed(monkeypatch, [
        item("Novartis appoints new CEO", "2026-09-10"), item("Novartis cuts full-year outlook", "2026-10-02"),
        item("Novartis opens new plant in Basel", "2026-10-03"), item("Novartis to acquire a gene therapy start-up", "2026-10-04"),
        item("Novartis annual outing photos", "2026-10-05"), item("Novartis wins court ruling", "2026-08-20"),
        item("Novartis stock price and chart", "2026-10-06", "TradingView")])
    ev = signals.feed()
    novn = [e for e in ev if e["ticker"] == "NOVN"]
    assert {e["type"] for e in novn if e["kind"] == "news"} == {"management_change", "guidance_change"}, "two most important, dated after the snapshot"
    price = next(e for e in novn if e["kind"] == "quote")
    assert price["severity"] == "high" and price["price"] == 140.0 and "13.1% above" in price["headline"]
    assert not [e for e in ev if e["ticker"] == "NESN"], "a 0.5% move is not an event"
    assert next(c for c in signals.compare() if c["ticker"] == "NOVN")["material"] is True


def test_tickers_outside_the_feed_get_no_events_and_no_invented_ones(monkeypatch):
    tiny_feed(monkeypatch, [])
    assert signals.events_for("ROG") == [] and not [e for e in signals.feed() if e["ticker"] not in {"NOVN", "NESN"}]


def test_feed_is_rebuilt_when_the_cache_is_refreshed(monkeypatch):
    tiny_feed(monkeypatch, [])
    assert len(signals.feed()) == 1
    tiny_feed(monkeypatch, [item("Novartis appoints new CEO")])
    assert len(signals.feed()) == 2


def test_company_without_market_data_never_gets_a_price_comparison():
    c = next(c for c in signals.compare() if c["ticker"] == "SDZ")
    assert c["has_baseline"] is False and c["price_delta_pct"] is None and c["material"] is False


def test_ranking_puts_material_changes_first():
    order = [c["material"] for c in signals.compare()]
    assert order == sorted(order, reverse=True)


# ------------------------------------------------------------------ briefings

def evidence_for(ticker):
    row = workbook.by_ticker(ticker)
    return "\n".join(str(x) for x in (agents.tool_get_company(ticker), agents.tool_get_sector_context(row["sector"], ticker), agents.tool_get_signals(ticker), agents.tool_get_financials(ticker)))


@pytest.mark.parametrize("ticker", sorted({e["ticker"] for e in signals.feed()}))
def test_template_briefing_passes_every_policy_check(ticker):
    briefing = agents.normalize_briefing(agents.template_briefing(ticker))
    checks = agents.rule_checks(briefing, ticker, evidence_for(ticker))
    failed = [c["label"] for c in checks if not c["passed"]]
    assert not failed, f"{ticker}: {failed}"


def test_briefing_for_company_without_data_says_momentum_cannot_be_computed():
    b = agents.template_briefing("SDZ")
    text = " ".join(f["text"] for f in b["facts"]) + " ".join(b["data_gaps"])
    assert "no price or performance data" in text and "cannot be computed" in text
    assert not re.search(r"\b0(\.0)?%", text)


def test_briefing_numbers_match_the_excel(raw):
    r = next(x for x in raw if x["Ticker"] == "VACN")
    first = agents.template_briefing("VACN")["facts"][0]["text"]
    assert f"CHF {r['Price (CHF)']}" in first and first.count("%") == 3
    assert f"{r['1Y Perf.'] * 100:+.1f}%" in first


# ------------------------------------------------------------------ the policy checks must catch problems

def good(ticker="VACN"):
    return agents.normalize_briefing(agents.template_briefing(ticker))


def failing(briefing, ticker="VACN"):
    return {c["key"] for c in agents.rule_checks(briefing, ticker, evidence_for(ticker)) if not c["passed"]}


def test_checks_catch_investment_advice():
    b = good()
    b["next_step"] = "We recommend buying the shares and a price target of CHF 700."
    assert "advice" in failing(b)


def test_checks_catch_invented_numbers():
    b = good()
    b["facts"][0]["text"] = "VAT Group traded at CHF 777.7 in the snapshot."
    assert "numbers" in failing(b)


def test_checks_catch_unknown_sources_and_uncited_facts():
    b = good()
    b["facts"][0]["source"] = "SEC-999"
    assert "sources" in failing(b)
    b = good()
    b["facts"][1]["source"] = ""
    assert "sources" in failing(b)


def test_checks_catch_speculation_inside_facts():
    b = good()
    b["facts"][0]["text"] += " The company might raise its outlook."
    assert "separation" in failing(b)


def test_checks_require_data_gaps_to_be_stated():
    b = good()
    b["data_gaps"] = []
    assert "gaps" in failing(b)
    b = good()
    b["data_gaps"] = ["News items are headlines from public media."]
    assert "gaps" in failing(b), "the snapshot date must be named in the data gaps, not only in the facts"


def test_checks_require_news_and_prices_to_name_their_publisher():
    b = good()
    sig = next(f for f in b["facts"] if f["source"].startswith("SIG-"))
    assert "provenance" not in failing(b)
    sig["text"] = "A headline appeared on 2026-10-15."
    assert "provenance" in failing(b)


def test_publishers_are_recognised_by_their_plain_name():
    assert agents._plain("www.marketscreener.com") == "marketscreener" and agents._plain("Bloomberg.com") == "bloomberg"
    assert agents._plain("Yahoo Finance") == "yahoofinance" and agents._plain("Reuters") == "reuters"
    b = good("VACN")
    ev = next(e for e in signals.events_for("VACN") if e["kind"] == "news")
    b["facts"][0] = {"text": f"{ev['source'].upper().replace('WWW.', '').replace('.COM', '')} reported on {ev['date']}: \u201c{ev['headline']}\u201d", "source": ev["id"]}
    assert "provenance" not in failing(b), "the publisher may be written without www and .com"


def test_quoted_headlines_are_not_judged_as_briefing_wording():
    b = good("VACN")
    ev = next(e for e in signals.events_for("VACN") if e["kind"] == "news")
    b["facts"][0] = {"text": f"{ev['source']} reported on {ev['date']}: \u201c{ev['headline']} may rise, Sell rating\u201d", "source": ev["id"]}
    assert "separation" in failing(b), "text that is not a verbatim headline is still judged"
    b["facts"][0]["text"] = f"{ev['source']} reported on {ev['date']}: \u201c{ev['headline']}\u201d"
    assert not {"separation", "advice"} & failing(b)


def test_source_must_belong_to_the_company():
    b = good("VACN")
    b["facts"][0]["source"] = "SEC-018"  # a real row, but Partners Group
    assert "sources" in failing(b)


# ------------------------------------------------------------------ offline pipeline

def run(focus=None, mode="offline"):
    async def collect():
        return [e async for e in agents.run_cycle(mode, focus)]

    return asyncio.run(collect())


@pytest.mark.parametrize("ticker", ["PGHN", "CLN", "ALC", "NOVN", "VACN", "ADEN", "GIVN"])
def test_offline_cycle_produces_an_approved_briefing_for_companies_with_and_without_a_report(ticker):
    events = run(ticker)
    types = [e["type"] for e in events]
    assert types[0] == "cycle_start" and types[-1] == "done"
    assert [e["agent"] for e in events if e["type"] == "agent_start"] == ["steward", "scout", "analyst", "reviewer"]
    briefing = next(e for e in events if e["type"] == "briefing")["briefing"]
    assert briefing["ticker"] == ticker and briefing["generated_by"] == "template"
    review = next(e for e in events if e["type"] == "review")
    assert review["verdict"] == "approve" and all(c["passed"] for c in review["checks"])
    approval = next(e for e in events if e["type"] == "approval_required")
    assert approval["briefing_id"] == briefing["id"] and approval["owner_team"] == briefing["owner_team"]
    assert "llm_call" not in types, "offline mode must not call a model"


def test_auto_focus_picks_the_largest_change():
    events = run(None)
    changes = next(e for e in events if e["type"] == "changes")
    material = [c["ticker"] for c in changes["changes"] if c["material"]]
    assert changes["focus"] == changes["shortlist"][0] and changes["shortlist"] == material[:3]
    assert len(changes["changes"]) == len(signals.compare()) and all(c["top"] for c in changes["changes"])


def test_unknown_focus_falls_back_to_auto():
    changes = next(e for e in run("NOPE") if e["type"] == "changes")
    assert changes["focus"] == changes["shortlist"][0]


def test_company_without_baseline_can_still_be_briefed():
    events = run("SDZ")
    review = next(e for e in events if e["type"] == "review")
    assert review["verdict"] == "approve"


def test_live_mode_falls_back_to_offline_when_azure_is_unavailable(monkeypatch):
    monkeypatch.setattr("app.llm.live_available", lambda: False)
    events = run(None, mode="live")
    assert events[0]["mode"] == "offline" and events[0]["note"]
    assert events[-1]["mode"] == "offline"


def test_data_steward_reports_the_excel_defects():
    findings = next(e for e in run() if e["type"] == "findings")["findings"]
    assert findings[0]["key"] == "scale" and findings[0]["severity"] == "critical"
    assert {f["key"] for f in findings} == {"scale", "missing", "share_classes", "stale"}

