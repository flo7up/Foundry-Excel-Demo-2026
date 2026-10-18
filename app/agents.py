import asyncio
import json
import re
import time
import uuid

from . import llm, reports, signals, store, workbook
from .config import MODELS

AGENTS = [
    {"key": "steward", "name": "Data Steward", "role": "Validates the workbook before anyone relies on it", "model": MODELS["steward"]},
    {"key": "scout", "name": "Signal Scout", "role": "Compares new signals with the workbook baseline", "model": MODELS["scout"]},
    {"key": "analyst", "name": "Account Analyst", "role": "Drafts a source-grounded briefing with tools", "model": MODELS["analyst"]},
    {"key": "reviewer", "name": "Compliance Reviewer", "role": "Checks sources, facts and policy", "model": MODELS["reviewer"]},
]

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "get_company", "description": "Return the workbook row for a ticker (prices, performance, momentum, signal).",
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {
        "name": "get_sector_context", "description": "Return sector averages and the company's rank within its sector.",
        "parameters": {"type": "object", "properties": {"sector": {"type": "string"}, "ticker": {"type": "string"}}, "required": ["sector"]}}},
    {"type": "function", "function": {
        "name": "get_signals", "description": "Return new signals for a ticker from the monitoring feed, compared with the workbook baseline.",
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {
        "name": "get_financials", "description": "Return verified headline figures from the company's public half-year report (H1 2026 versus H1 2025) with page references. Only some companies have a report.",
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
]

ADVICE_PATTERNS = [
    r"\b(we|i)\s+(would\s+)?recommend\s+(buying|selling|to\s+buy|to\s+sell)", r"\byou\s+should\s+(buy|sell|invest)",
    r"\bprice\s+target\b", r"\b(strong\s+)?(buy|sell)\s+(rating|recommendation)\b", r"\bgood\s+(buy|investment)\b",
    r"\bundervalued\b", r"\boutperform\b",
]
HEDGES = r"\b(likely|might|may|could|probably|suggests?|indicates?|appears?|potentially)\b"
QUOTED = re.compile("\u201c[^\u201d]*\u201d")


def strip_quotes(text):
    """Headlines quoted word for word are a publisher's words, not the briefing's, so wording rules skip them.
    Any other quoted text, such as a passage from a report, is still checked."""
    known = {e["headline"] for e in signals.feed()}
    return QUOTED.sub(lambda m: " " if m.group(0)[1:-1] in known else m.group(0), text)


def evidence_numbers(text):
    """Every number in the evidence, including thousands-grouped ones read as a single value (1,180.00)."""
    grouped = re.sub(r"(?<=\d)[,\u2019']+(?=\d{3}(?!\d))", "", text)
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text) + re.findall(r"\d+(?:\.\d+)?", grouped)]


def pace(seconds):
    return asyncio.sleep(seconds)


class Ctx:
    def __init__(self, live):
        self.live = live
        self.t0 = time.perf_counter()
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost = 0.0
        self.evidence = []

    def ev(self, type_, **kw):
        return {"type": type_, "t": round(time.perf_counter() - self.t0, 2), **kw}

    def totals(self):
        return {"tokens_in": self.tokens_in, "tokens_out": self.tokens_out, "cost": round(self.cost, 5)}

    def add(self, r):
        self.tokens_in += r["tokens_in"]
        self.tokens_out += r["tokens_out"]
        self.cost += r["cost"]


# ----------------------------------------------------------------------------- tools

def tool_get_company(ticker):
    r = workbook.by_ticker(ticker)
    if not r:
        return {"error": f"Unknown ticker {ticker}"}
    return {
        "row_id": r["id"], "company": r["company"], "ticker": r["ticker"], "sector": r["sector"], "index": r["index"],
        "price_chf": r["price"], "perf_1d_pct": r["d1"], "perf_3m_pct": r["m3"], "perf_6m_pct": r["m6"], "perf_1y_pct": r["y1"],
        "momentum_pts": r["score"], "signal": r["signal"], "snapshot_date": workbook.current().snapshot_str,
        "has_market_data": r["complete"], "share_classes": r["share_classes"],
        "signal_rule": "Positive >= 20 pts, Negative <= -10 pts, otherwise Mixed",
    }


def tool_get_sector_context(sector, ticker=None):
    c = workbook.sector_context(sector, ticker)
    s = c["stats"]
    return {
        "sector": sector, "companies_with_data": s.get("n_complete"), "avg_3m_pct": s.get("avg_m3"), "avg_6m_pct": s.get("avg_m6"),
        "avg_1y_pct": s.get("avg_y1"), "avg_momentum_pts": s.get("avg_score"), "rank_in_sector": c["rank_in_sector"],
        "ranked_peers": c["ranked_peers"], "top_peers": c["top_peers"],
    }


def tool_get_signals(ticker):
    ch = next((c for c in signals.compare() if c["ticker"] == ticker.upper()), None)
    row = workbook.by_ticker(ticker)
    if not ch or not row:
        return {"ticker": ticker, "events": [], "note": "No new signals"}
    return {
        "ticker": ticker.upper(), "snapshot_price_chf": row["price"], "price_change_vs_snapshot_pct": ch["price_delta_pct"],
        "events": [{k: e[k] for k in ("id", "date", "type", "severity", "kind", "headline", "detail", "source") if k in e} | ({"price_chf": e["price"]} if e.get("price") else {}) for e in ch["events"]],
        "material": ch["material"], "feed": "real public feed: Yahoo Finance closing prices and news headlines (publisher named per event)",
    }


def tool_get_financials(ticker):
    f = reports.financials(ticker) if workbook.by_ticker(ticker) else None
    if not f:
        return {"error": f"No public report is loaded for {ticker}."}
    return {**f, "snapshot_date": workbook.current().snapshot_str}


def run_tool(name, args):
    if name == "get_company":
        return tool_get_company(args.get("ticker", ""))
    if name == "get_sector_context":
        return tool_get_sector_context(args.get("sector", ""), args.get("ticker"))
    if name == "get_signals":
        return tool_get_signals(args.get("ticker", ""))
    if name == "get_financials":
        return tool_get_financials(args.get("ticker", ""))
    return {"error": f"Unknown tool {name}"}


def summarize_result(name, res):
    if "error" in res:
        return res["error"]
    if name == "get_company":
        return f"{res['company']} · {res['signal']} · momentum {res['momentum_pts']} pts" if res["has_market_data"] else f"{res['company']} · no market data"
    if name == "get_sector_context":
        return f"{res['sector']} · avg 1Y {res['avg_1y_pct']}% · rank {res['rank_in_sector']}/{res['ranked_peers']}"
    if name == "get_signals":
        return f"{len(res['events'])} events · price Δ {res.get('price_change_vs_snapshot_pct')}%"
    if name == "get_financials":
        return f"{res['period']} report · {res['standard']} · {len(res['items'])} figures"
    return "ok"


# ----------------------------------------------------------------------------- helpers

async def tool_step(ctx, agent, name, args, sink):
    yield ctx.ev("tool_call", agent=agent, tool=name, args=args)
    await pace(0.45)
    res = run_tool(name, args)
    ctx.evidence.append(json.dumps(res, default=str))
    sink.append(res)
    yield ctx.ev("tool_result", agent=agent, tool=name, summary=summarize_result(name, res), data=res)


async def llm_step(ctx, agent, model, purpose, messages, sink, **kw):
    yield ctx.ev("llm_call", agent=agent, model=model, purpose=purpose)
    try:
        r = await llm.chat(model, messages, **kw)
    except Exception as exc:  # noqa: BLE001
        sink.append(None)
        yield ctx.ev("warning", agent=agent, message=f"Live call failed ({type(exc).__name__}); using offline template.")
        return
    ctx.add(r)
    sink.append(r)
    yield ctx.ev("llm_result", agent=agent, model=model, tokens_in=r["tokens_in"], tokens_out=r["tokens_out"],
                 latency=r["latency"], cost=round(r["cost"], 5), preview=(r["content"] or "")[:160], totals=ctx.totals())


def parse_json(text):
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.MULTILINE).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def fmt_pct(v):
    return "n/a" if v is None else f"{v:+.1f}%"


def fmt_m(v):
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}"


# ----------------------------------------------------------------------------- briefing

HYPOTHESES = {
    "trading_update": "Fresh results or a trading update may mean active planning that is worth exploring in a discovery conversation.",
    "management_change": "A leadership or board change may re-open tooling and vendor decisions.",
    "guidance_change": "A revised or reaffirmed outlook may trigger budget or cost-review discussions.",
    "restructuring": "Restructuring plans may shift internal priorities and budgets.",
    "deal": "The deal may point to an active technology or portfolio roadmap.",
    "regulatory": "Regulatory or legal topics may increase demand for reporting and governance capabilities.",
    "analyst_note": "Changed analyst coverage may raise management attention on communication and planning.",
    "product_update": "A product or site announcement may point to an active technology roadmap.",
}


PUBLIC_FEED_GAP = "News items are headlines from public media and prices are end-of-day closes; they were not checked against the companies' own filings."
NO_FEED_GAP = "The public feed (Yahoo Finance quotes and news headlines) has no data for this company, so no price move or news is included."


def template_briefing(ticker):
    row = workbook.by_ticker(ticker)
    sig = tool_get_signals(ticker)
    sec = tool_get_sector_context(row["sector"], ticker)
    facts, hyps, gaps, questions = [], [], [], []
    if row["complete"]:
        facts.append({"text": f"In the {workbook.current().snapshot_str} snapshot, {row['company']} ({row['ticker']}) traded at CHF {row['price']} with 3M {fmt_pct(row['m3'])}, 6M {fmt_pct(row['m6'])} and 1Y {fmt_pct(row['y1'])} performance.", "source": row["id"]})
        facts.append({"text": f"The corrected momentum score is {row['score']} points, which maps to a '{row['signal']}' signal; rank {sec['rank_in_sector']} of {sec['ranked_peers']} in {row['sector']}.", "source": row["id"]})
    else:
        facts.append({"text": f"{row['company']} ({row['ticker']}) is listed in the workbook as constituent metadata only, so no price or performance data is available.", "source": row["id"]})
        gaps.append("No market data in the workbook for this security, so momentum cannot be computed.")
    fin = reports.financials(ticker)
    if fin:
        by = {i["key"]: i for i in fin["items"]}
        cur = fin["currency"]
        if "revenue" in by:
            r = by["revenue"]
            facts.append({"text": f"In its {fin['period']} report ({fin['standard']}), {row['company']} reported {r['label'].lower()} of {cur} {fmt_m(r['h1_2026'])} million ({fmt_pct(r['growth_pct'])} versus {fin['period'].replace('2026', '2025')}).", "source": r["ref"]})
        if "operating_profit" in by and "net_income" in by:
            o, n = by["operating_profit"], by["net_income"]
            mg = fin["margins"].get("operating_margin_pct")
            facts.append({"text": f"{o['label']} was {cur} {fmt_m(o['h1_2026'])} million" + (f" (margin {mg['h1_2026']}% versus {mg['h1_2025']}%)" if mg else "") + f" and net income {cur} {fmt_m(n['h1_2026'])} million ({fmt_pct(n['growth_pct'])}).", "source": n["ref"]})
    events = sorted(sig["events"], key=lambda e: (signals.SEVERITY_WEIGHT[e["severity"]], e["kind"] == "news", e["date"]), reverse=True)
    for e in events:
        if e["type"] == "price_move" and sig.get("price_change_vs_snapshot_pct") is not None:
            facts.append({"text": f"The {e['source']} close of CHF {e['price_chf']} on {e['date']} is {fmt_pct(sig['price_change_vs_snapshot_pct'])} versus the workbook price.", "source": e["id"]})
        else:
            facts.append({"text": f"{e['source']} reported on {e['date']}: \u201c{e['headline']}\u201d", "source": e["id"]})
        if e["type"] in HYPOTHESES:
            hyps.append({"text": HYPOTHESES[e["type"]], "confidence": "low", "validate_by": "Discovery call and annual-report review"})
    delta = sig.get("price_change_vs_snapshot_pct")
    if delta is not None and abs(delta) >= signals.MATERIAL_PRICE_MOVE:
        text = ("Visible market pressure may increase focus on efficiency" if delta < 0 else "Positive market momentum may coincide with growth investment")
        hyps.append({"text": f"{text}. This is not evidence of purchase intent.", "confidence": "low", "validate_by": "Stakeholder interviews"})
    if not hyps:
        hyps.append({"text": "No additional hypothesis is supported by the available evidence.", "confidence": "low", "validate_by": "Further research"})
    if fin:
        gaps += [f"Market prices are from {workbook.current().snapshot_str}; the report figures are for the first half of 2026 (to 30 June), so the two cover different periods.",
                 PUBLIC_FEED_GAP if sig["events"] else NO_FEED_GAP]
    else:
        gaps += [f"Market snapshot dated {workbook.current().snapshot_str}; the workbook contains no revenue or earnings data and no public report is loaded for this company.",
                 PUBLIC_FEED_GAP if sig["events"] else NO_FEED_GAP]
    if len(row["share_classes"]) > 1:
        gaps.append(f"Share classes {', '.join(row['share_classes'])} belong to the same company.")
    questions += ["Which business unit and executive sponsor own the relevant budget?", "What does the latest report say about priorities and outlook?" if fin else "What does the latest annual report say about priorities?"]
    return {
        "headline": f"{row['company']}: " + (("\u201c" + events[0]["headline"] + "\u201d" if events[0]["kind"] == "news" else events[0]["headline"]) if events else "no new signal"),
        "signal_summary": f"{row['company']} shows a '{row['signal']}' public-market signal in the workbook and {len(sig['events'])} public signal(s) (price move or news) since the snapshot.",
        "facts": facts[:7], "hypotheses": hyps[:3], "data_gaps": gaps, "open_questions": questions,
        "next_step": "Prepare a 30-minute discovery conversation with the account owner and validate the hypotheses with public sources.",
    }


ANALYST_SYSTEM = """You are the Account Analyst agent in an account-intelligence team at a Swiss enterprise sales organisation.
Use the tools to gather evidence about ONE company, then write a briefing for the responsible account team.

Rules:
- Use only information returned by the tools. Never invent numbers, events or names.
- Every item in "facts" must cite one source id: a workbook row id (SEC-xxx), a signal id (SIG-xxx) or a report page id (REP-xxx-pN) returned by get_financials.
- If get_financials returns figures, include one or two facts from the public report (revenue, margin, net income) and say they cover the first half of 2026 while prices are from the snapshot date.
- Signals (SIG-xxx) are real: share-price closes and news headlines from public media. In the fact text name the publisher and the date, and quote the headline instead of paraphrasing it. A headline is a report, not proof, and the briefing must say in data_gaps that news was not checked against company filings.
- Put interpretations ONLY in "hypotheses" (they are not claims). Facts must not contain words like may, might, likely.
- Do NOT give investment advice, price targets or buy/sell views. Share price is not evidence of demand or purchase intent.
- Always state data gaps: snapshot date, missing revenue or earnings data, missing market data if any.
- If the company has no market data, say that momentum cannot be computed. Never treat missing data as zero.

First call get_company, get_sector_context and get_signals, and get_financials (it returns an error when the company has no report; then say so in data_gaps). Then reply with ONLY a JSON object:
{"headline": str, "signal_summary": str (max 2 sentences),
 "facts": [{"text": str, "source": "SEC-xxx, SIG-xxx or REP-xxx-pN"}] (4-6 items),
 "hypotheses": [{"text": str, "confidence": "low|medium", "validate_by": str}] (2-3 items),
 "data_gaps": [str], "open_questions": [str] (2-3 items), "next_step": str}"""


def normalize_briefing(raw):
    if not isinstance(raw, dict) or not raw.get("facts"):
        return None
    facts = [{"text": str(f.get("text", "")).strip(), "source": str(f.get("source", "")).strip()} for f in raw["facts"] if isinstance(f, dict)]
    hyps = []
    for h in raw.get("hypotheses", []):
        if isinstance(h, dict):
            hyps.append({"text": str(h.get("text", "")), "confidence": str(h.get("confidence", "low")), "validate_by": str(h.get("validate_by", ""))})
        elif isinstance(h, str):
            hyps.append({"text": h, "confidence": "low", "validate_by": ""})
    return {
        "headline": str(raw.get("headline", "")), "signal_summary": str(raw.get("signal_summary", "")), "facts": facts,
        "hypotheses": hyps, "data_gaps": [str(x) for x in raw.get("data_gaps", [])],
        "open_questions": [str(x) for x in raw.get("open_questions", [])], "next_step": str(raw.get("next_step", "")),
    }


def signal_source(e):
    return {"kind": e["kind"], "label": f"{e['id']} · {e['source']}", "detail": f"{e['date']} · {e['headline']}", "url": e.get("url")}


def source_map(ticker):
    row = workbook.by_ticker(ticker)
    out = {}
    for t in row["share_classes"]:
        r = workbook.by_ticker(t)
        out[r["id"]] = {"kind": "workbook", "label": f"Workbook row {r['id']}", "detail": f"{r['company']} · {r['ticker']} · snapshot {workbook.current().snapshot_str}"}
    for e in signals.events_for(ticker):
        out[e["id"]] = signal_source(e)
    fin = reports.financials(ticker)
    for i in (fin["items"] if fin else []):
        out[i["ref"]] = reports.source_meta(i["ref"])
    return out


# ----------------------------------------------------------------------------- review

def _numbers(text):
    text = re.sub(r"\b(?:SEC|SIG)-\d+\b|\bREP-[A-Z]+-p\d+\b", " ", text)
    text = re.sub(r"(?<=\d)[,\u2019']+(?=\d{3}(?!\d))", "", text)  # 27,521 and 1'121 are single numbers
    text = re.sub(r"\d{1,2}\.\d{1,2}\.\d{4}", " ", text)
    text = re.sub(r"\b20\d\d\b", " ", text)
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]


def _plain(name, publisher=True):
    """Letters and digits only, so "MarketScreener" matches "www.marketscreener.com" and "Bloomberg" matches "Bloomberg.com"."""
    out = re.sub(r"[^a-z0-9]", "", name.lower())
    return re.sub(r"^www|com$", "", out) if publisher else out


def rule_checks(briefing, ticker, evidence_text):
    valid = set(source_map(ticker))
    facts = briefing["facts"]
    all_text = " ".join([briefing["headline"], briefing["signal_summary"], briefing["next_step"]] + [f["text"] for f in facts]
                        + [h["text"] for h in briefing["hypotheses"]] + briefing["data_gaps"] + briefing["open_questions"])
    bad_sources = [f["source"] for f in facts if f["source"] not in valid]
    hedged = [f["text"] for f in facts if re.search(HEDGES, strip_quotes(f["text"]), re.I)]
    advice = [p for p in ADVICE_PATTERNS if re.search(p, strip_quotes(all_text), re.I)]
    ev_nums = evidence_numbers(evidence_text)
    ungrounded = []
    for f in facts:
        for n in _numbers(f["text"]):
            if (("." in str(n) and n != int(n)) or n >= 100) and not any(abs(n - e) <= 0.051 for e in ev_nums):
                ungrounded.append(n)
    gap_text = " ".join(briefing["data_gaps"]).lower()
    events = {e["id"]: e for e in signals.feed()}
    unnamed = [f["source"] for f in facts if f["source"] in events and _plain(events[f["source"]]["source"]) not in _plain(f["text"], False)]
    return [
        {"key": "sources", "label": "Every fact cites a valid source", "passed": not bad_sources and bool(facts),
         "detail": f"{len(facts)} facts, all cited" if not bad_sources else f"Invalid sources: {', '.join(bad_sources)}"},
        {"key": "numbers", "label": "Numbers trace back to tool evidence", "passed": not ungrounded,
         "detail": "All figures found in evidence" if not ungrounded else f"Not found in evidence: {ungrounded[:4]}"},
        {"key": "separation", "label": "Facts and hypotheses are separated", "passed": not hedged and bool(briefing["hypotheses"]),
         "detail": f"{len(briefing['hypotheses'])} hypotheses labelled" if not hedged else "Speculative wording found in facts"},
        {"key": "advice", "label": "No investment advice or price targets", "passed": not advice,
         "detail": "No advice language detected" if not advice else "Advice-like wording detected"},
        {"key": "gaps", "label": "Data gaps and snapshot date disclosed", "passed": bool(briefing["data_gaps"]) and ("snapshot" in gap_text or workbook.current().snapshot_str in gap_text),
         "detail": f"{len(briefing['data_gaps'])} gaps disclosed"},
        {"key": "provenance", "label": "News and prices name their publisher", "passed": not unnamed,
         "detail": "Every signal names its publisher" if not unnamed else f"Publisher missing for {', '.join(unnamed)}"},
    ]


REVIEWER_SYSTEM = """You are the Compliance Reviewer agent. You review an account briefing against policy:
facts must be sourced, hypotheses must be separate and hedged, no investment advice, data gaps must be disclosed.
You also receive the results of automated checks. Reply with ONLY JSON:
{"verdict": "approve" | "revise", "summary": str (max 2 sentences for a business reader), "comments": [str] (max 3)}"""


# ----------------------------------------------------------------------------- pipeline

async def run_cycle(mode="offline", focus=None):
    live = mode == "live" and llm.live_available()
    ctx = Ctx(live)
    yield ctx.ev("cycle_start", mode="live" if live else "offline", agents=AGENTS,
                 note=None if live or mode != "live" else "Live mode unavailable; running offline.")

    # 1 - Data Steward
    A = "steward"
    yield ctx.ev("agent_start", agent=A, task="Validate the workbook")
    sink = []
    ds = workbook.current()
    async for e in tool_step_simple(ctx, A, "load_workbook", {"file": ds.name},
                                    {"sheet": ds.report["sheet"], "rows": len(ds.rows), "snapshot": ds.snapshot_str},
                                    f"sheet '{ds.report['sheet']}' · {len(ds.rows)} securities"):
        yield e
    found = workbook.findings()
    async for e in tool_step_simple(ctx, A, "validate_workbook", {"checks": ["scale", "missing", "duplicates", "freshness"]},
                                    {"findings": [f["title"] for f in found]}, f"{len(found)} findings"):
        yield e
    note = ""
    if live:
        async for e in llm_step(ctx, A, MODELS["steward"], "Summarise findings for business users", [
            {"role": "system", "content": "You are a data steward. In 2 plain sentences, summarise the findings for a business audience and name the single most important fix. No markdown."},
            {"role": "user", "content": json.dumps([{k: f[k] for k in ("title", "detail", "action")} for f in found])}], sink, max_tokens=1500):
            yield e
        if sink and sink[-1]:
            note = sink[-1]["content"].strip()
    else:
        await pace(0.9)
    if not note:
        top = found[0]
        note = f"{top['title']}. {top['action']} In total the agent raised {len(found)} findings before any other agent used the data."
    yield ctx.ev("findings", agent=A, findings=found, note=note)
    yield ctx.ev("agent_done", agent=A, summary=f"{len(found)} findings, data checked for downstream agents")

    # 2 - Signal Scout
    A = "scout"
    yield ctx.ev("agent_start", agent=A, task="Detect material changes")
    since = ds.snapshot.isoformat()
    feed_events = signals.fetch(since)
    async for e in tool_step_simple(ctx, A, "fetch_signals", {"since": since, "feed": "public"},
                                    {"events": len(feed_events)}, f"{len(feed_events)} new events"):
        yield e
    changes = signals.compare()
    material = [c for c in changes if c["material"]]
    async for e in tool_step_simple(ctx, A, "compare_to_baseline", {"price_move_threshold_pct": signals.MATERIAL_PRICE_MOVE},
                                    {"companies": len(changes), "material": len(material)}, f"{len(changes)} companies compared · {len(material)} material"):
        yield e
    shortlist = [c["ticker"] for c in material[:3]]
    triage = {}
    if live:
        sink = []
        async for e in llm_step(ctx, A, MODELS["scout"], "Explain triage for the shortlist", [
            {"role": "system", "content": 'You triage account signals. For each company return one short business reason (max 18 words) why it deserves research. Reply ONLY JSON: {"triage":[{"ticker":str,"why":str}]}'},
            {"role": "user", "content": json.dumps([{"ticker": c["ticker"], "company": c["company"], "price_delta_pct": c["price_delta_pct"], "reasons": c["reasons"], "workbook_signal": c["signal"]} for c in material[:3]])}],
                sink, json_mode=True, max_tokens=1500):
            yield e
        parsed = parse_json(sink[-1]["content"]) if sink and sink[-1] else None
        if parsed:
            triage = {t.get("ticker"): t.get("why") for t in parsed.get("triage", []) if isinstance(t, dict)}
    else:
        await pace(0.8)
    for c in material[:3]:
        c["why"] = triage.get(c["ticker"]) or "; ".join(c["reasons"])
    chosen = (focus or "").upper()
    if chosen not in {c["ticker"] for c in changes}:
        strongest = max((r for r in ds.rows if r["complete"]), key=lambda r: abs(r["score"]))
        chosen = shortlist[0] if shortlist else changes[0]["ticker"] if changes else strongest["ticker"]
    yield ctx.ev("changes", agent=A, changes=[{k: v for k, v in c.items() if k != "events"} | {"event_count": len(c["events"])} for c in changes],
                 shortlist=shortlist, focus=chosen)
    yield ctx.ev("agent_done", agent=A, summary=f"{len(material)} material changes, focusing on {chosen}")

    # 3 - Account Analyst
    A = "analyst"
    row = workbook.by_ticker(chosen)
    yield ctx.ev("agent_start", agent=A, task=f"Briefing for {row['company']}")
    briefing, generated_by = None, "template"
    if live:
        messages = [{"role": "system", "content": ANALYST_SYSTEM}, {"role": "user", "content": f"Prepare the briefing for ticker {chosen} ({row['company']}, sector {row['sector']})."}]
        final = None
        for _ in range(7):
            sink = []
            async for e in llm_step(ctx, A, MODELS["analyst"], "Plan / write briefing", messages, sink, tools=TOOL_SPECS, max_tokens=5000):
                yield e
            r = sink[-1] if sink else None
            if not r:
                break
            if r["tool_calls"]:
                messages.append({"role": "assistant", "content": r["content"] or None, "tool_calls": [
                    {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}} for tc in r["tool_calls"]]})
                for tc in r["tool_calls"]:
                    try:
                        args = json.loads(tc["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    res = []
                    async for e in tool_step(ctx, A, tc["name"], args, res):
                        yield e
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res[0], default=str)})
                continue
            final = parse_json(r["content"])
            break
        briefing = normalize_briefing(final)
        if briefing:
            generated_by = "live"
        else:
            yield ctx.ev("warning", agent=A, message="Model output could not be used; using offline template.")
    if not briefing:
        calls = [("get_company", {"ticker": chosen}), ("get_sector_context", {"sector": row["sector"], "ticker": chosen}), ("get_signals", {"ticker": chosen})]
        if reports.financials(chosen):
            calls.append(("get_financials", {"ticker": chosen}))
        for name, args in calls:
            res = []
            async for e in tool_step(ctx, A, name, args, res):
                yield e
        await pace(0.9)
        briefing = normalize_briefing(template_briefing(chosen))
    briefing_id = uuid.uuid4().hex[:8]
    team = workbook.SECTOR_TEAMS.get(row["sector"], "Account team")
    briefing |= {"id": briefing_id, "ticker": chosen, "company": row["company"], "sector": row["sector"], "owner_team": team,
                 "sources": source_map(chosen), "generated_by": generated_by, "model": MODELS["analyst"] if generated_by == "live" else "offline template"}
    store.remember(briefing)
    yield ctx.ev("briefing", agent=A, briefing=briefing)
    yield ctx.ev("agent_done", agent=A, summary=f"{len(briefing['facts'])} facts · {len(briefing['hypotheses'])} hypotheses")

    # 4 - Compliance Reviewer
    A = "reviewer"
    yield ctx.ev("agent_start", agent=A, task="Review against policy")
    await pace(0.5)
    checks = rule_checks(briefing, chosen, "\n".join(ctx.evidence))
    yield ctx.ev("tool_call", agent=A, tool="policy_checks", args={"rules": len(checks)})
    await pace(0.5)
    yield ctx.ev("tool_result", agent=A, tool="policy_checks", summary=f"{sum(c['passed'] for c in checks)}/{len(checks)} checks passed", data={"checks": checks})
    verdict_ok = all(c["passed"] for c in checks)
    summary = "All automated checks passed. The briefing separates facts from hypotheses and is ready for human review." if verdict_ok else "Some checks failed. A human reviewer should correct the briefing before it is used."
    if live:
        sink = []
        async for e in llm_step(ctx, A, MODELS["reviewer"], "Policy review of the briefing", [
            {"role": "system", "content": REVIEWER_SYSTEM},
            {"role": "user", "content": json.dumps({"briefing": {k: briefing[k] for k in ("headline", "signal_summary", "facts", "hypotheses", "data_gaps", "next_step")}, "automated_checks": checks})}],
                sink, json_mode=True, max_tokens=2500):
            yield e
        parsed = parse_json(sink[-1]["content"]) if sink and sink[-1] else None
        if parsed:
            summary = str(parsed.get("summary", summary))
            verdict_ok = verdict_ok and parsed.get("verdict") == "approve"
    else:
        await pace(0.8)
    yield ctx.ev("review", agent=A, checks=checks, verdict="approve" if verdict_ok else "revise", summary=summary)
    yield ctx.ev("agent_done", agent=A, summary="Approved for human review" if verdict_ok else "Needs revision")

    # 5 - Human in the loop
    yield ctx.ev("approval_required", briefing_id=briefing_id, owner_team=team, company=row["company"], verdict="approve" if verdict_ok else "revise")
    yield ctx.ev("done", totals=ctx.totals(), mode="live" if live else "offline", elapsed=round(time.perf_counter() - ctx.t0, 1))


async def tool_step_simple(ctx, agent, name, args, result, summary):
    yield ctx.ev("tool_call", agent=agent, tool=name, args=args)
    await pace(0.5)
    ctx.evidence.append(json.dumps(result, default=str))
    yield ctx.ev("tool_result", agent=agent, tool=name, summary=summary, data=result)





