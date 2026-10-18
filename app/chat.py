"""Chat with the peer and competitor insights in the loaded workbook.

Every fact comes from a tool that reads the workbook, the signal feed or a briefing from this session.
Live mode lets a Foundry model pick the tools; offline mode uses a rule-based router over the same tools.
"""
import asyncio
import json
import re
import time
import unicodedata
from collections import defaultdict

from . import agents, llm, reports, signals, store, workbook
from .feed import clean_company
from .config import MODELS

METRICS = {
    "score": ("momentum score", "pts"), "m3": ("3-month performance", "%"), "m6": ("6-month performance", "%"),
    "y1": ("1-year performance", "%"), "d1": ("daily performance", "%"),
}
MAX_TURNS = 8
MAX_TOOL_ROUNDS = 6

# ----------------------------------------------------------------------------- finding companies in text

_SUFFIX = re.compile(r"\b(ag|sa|ltd|group|holding|holdings|inc|se|plc|co|international|communications|company)\b", re.I)
_STOP = {"swiss", "group", "holding", "bank", "global", "international", "financial", "financi", "partners", "life"}


def short_name(company):
    s = _SUFFIX.sub(" ", re.sub(r"[().,&]", " ", company))
    return re.sub(r"\s+", " ", s).strip().lower()


def _fold(text):
    """Lower case without accents, so "Nestle" finds "Nestlé"."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def match_companies(text):
    """Companies mentioned in free text, in order of appearance. Returns workbook rows (one per company)."""
    rows = workbook.rows()
    low = _fold(text)
    hits = {}

    def add(pos, row):
        key = row["company"]
        if key not in hits or pos < hits[key][0]:
            hits[key] = (pos, workbook.by_ticker(row["share_classes"][0]) or row)

    token_owner = defaultdict(set)
    for r in rows:
        for tok in re.findall(r"[a-z]{5,}", _fold(short_name(r["company"]))):
            token_owner[tok].add(r["company"])
    for r in rows:
        name = _fold(short_name(r["company"]))
        if name:
            m = re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", low)
            if m:
                add(m.start(), r)
        m = re.search(rf"(?<![A-Za-z]){re.escape(r['ticker'])}(?![A-Za-z])", text)
        if m and r["ticker"].isupper():
            add(m.start(), r)
    for tok, owners in token_owner.items():
        if len(owners) == 1 and tok not in _STOP:
            m = re.search(rf"(?<![a-z]){tok}(?![a-z])", low)
            if m:
                company = next(iter(owners))
                add(m.start(), next(x for x in rows if x["company"] == company))
    return [row for _pos, row in sorted(hits.values(), key=lambda p: p[0])]


MAX_REFERENCES = 5
PLURAL_REF = re.compile(r"\b(these|them|those|selected|both|each|they|their)\b", re.I)


def primary_row(row):
    """The first share class of a company, so one company is one entry."""
    return workbook.by_ticker(row["share_classes"][0]) or row


def resolve_references(tickers):
    """Workbook rows for the companies the user clicked: one per company, in click order, unknown tickers dropped."""
    out, seen = [], set()
    for t in tickers or []:
        r = workbook.by_ticker(t)
        if r:
            r = primary_row(r)
            if r["company"] not in seen:
                seen.add(r["company"])
                out.append(r)
    return out[:MAX_REFERENCES]


def reference_note(refs):
    """Tells a model which companies the user attached; the visible message stays as typed."""
    if not refs:
        return ""
    names = ", ".join(f"{r['company']} ({r['ticker']})" for r in refs)
    return (f"\n\n[The user selected these companies in the app: {names}. They are the subject of the question unless it names other companies "
            "or asks about the whole workbook. Look them up with the tools.]")


def match_sector(text):
    low = text.lower()
    for s in sorted({r["sector"] for r in workbook.rows()}, key=len, reverse=True):
        if s.lower() in low:
            return s
    aliases = {"pharma": "Health care", "health": "Health care", "bank": "Financials", "insurance": "Financials", "finance": "Financials",
               "industrial": "Industrials", "material": "Materials", "tech": "Information technology", "telecom": "Communication services",
               "retail": "Retail discretionary", "staples": "Retail staples", "real estate": "Real estate"}
    present = {r["sector"] for r in workbook.rows()}
    for k, v in aliases.items():
        if k in low and v in present:
            return v
    return None


# ----------------------------------------------------------------------------- tools

def _brief(r):
    return {"ticker": r["ticker"], "company": r["company"], "sector": r["sector"], "ref": r["id"], "has_data": r["complete"]}


def _group_best(rows, key, reverse=True):
    """One row per company: the share class with the best value."""
    best = {}
    for r in rows:
        if r[key] is None:
            continue
        cur = best.get(r["company"])
        if cur is None or (r[key] > cur[key] if reverse else r[key] < cur[key]):
            best[r["company"]] = r
    return list(best.values())


def t_find_company(query=""):
    return {"matches": [_brief(r) for r in match_companies(str(query))[:5]]}


def t_get_company(ticker=""):
    r = workbook.by_ticker(ticker)
    if not r:
        return {"error": f"Unknown ticker {ticker}. Use find_company first."}
    ranked = sorted((x for x in _group_best(workbook.rows(), "score")), key=lambda x: -x["score"])
    in_sector = [x for x in ranked if x["sector"] == r["sector"]]
    return {
        **_brief(r), "price_chf": r["price"], "perf_1d_pct": r["d1"], "perf_3m_pct": r["m3"], "perf_6m_pct": r["m6"], "perf_1y_pct": r["y1"],
        "momentum_pts": r["score"], "signal": r["signal"], "snapshot": workbook.current().snapshot_str, "share_classes": r["share_classes"],
        "rank_overall": next((i + 1 for i, x in enumerate(ranked) if x["company"] == r["company"]), None), "of_overall": len(ranked),
        "rank_in_sector": next((i + 1 for i, x in enumerate(in_sector) if x["company"] == r["company"]), None), "of_sector": len(in_sector),
    }


def t_get_peers(ticker="", limit=6):
    r = workbook.by_ticker(ticker)
    if not r:
        return {"error": f"Unknown ticker {ticker}. Use find_company first."}
    others = [x for x in workbook.rows() if x["sector"] == r["sector"] and x["company"] != r["company"]]
    with_data = sorted(_group_best([x for x in others if x["complete"]], "score"), key=lambda x: -x["score"])
    no_data = sorted({x["company"] for x in others if not x["complete"]})
    out = {
        "company": _brief(r), "sector": r["sector"], "company_momentum_pts": r["score"], "company_signal": r["signal"],
        "peers_with_data": len(with_data), "peers_without_data": no_data,
        "peers": [{**_brief(x), "momentum_pts": x["score"], "signal": x["signal"], "perf_3m_pct": x["m3"], "perf_1y_pct": x["y1"],
                   "gap_pts": None if r["score"] is None else round(x["score"] - r["score"], 2)} for x in with_data[:int(limit)]],
        "note": "Peers are companies in the same sector in this workbook. The workbook has no market share, revenue or product data.",
    }
    if r["score"] is None:
        out["note"] = "This company has no complete market data, so it cannot be compared with its peers. " + out["note"]
    else:
        ahead = sum(1 for x in with_data if x["score"] > r["score"])
        out["rank_among_sector"] = ahead + 1
        out["of_companies_with_data"] = len(with_data) + 1
    return out


def t_compare_companies(tickers=None):
    rows = []
    for t in (tickers or [])[:4]:
        r = workbook.by_ticker(t)
        if r:
            rows.append(r)
    if len(rows) < 2:
        return {"error": "Give at least two valid tickers. Use find_company to look them up."}
    full = [r for r in rows if r["complete"]]
    leaders = {}
    for key in ("score", "m3", "m6", "y1"):
        if len(full) >= 2:
            leaders[key] = max(full, key=lambda r: r[key])["ticker"]
    return {
        "companies": [{**_brief(r), "price_chf": r["price"], "momentum_pts": r["score"], "signal": r["signal"], "perf_3m_pct": r["m3"],
                       "perf_6m_pct": r["m6"], "perf_1y_pct": r["y1"]} for r in rows],
        "leader_by": {"momentum_pts": leaders.get("score"), "perf_3m": leaders.get("m3"), "perf_6m": leaders.get("m6"), "perf_1y": leaders.get("y1")},
        "without_data": [r["ticker"] for r in rows if not r["complete"]],
        "same_sector": len({r["sector"] for r in rows}) == 1,
    }


def t_rank_companies(metric="score", order="desc", limit=5, sector=None):
    metric = metric if metric in METRICS else "score"
    rows = workbook.rows()
    if sector:
        rows = [r for r in rows if r["sector"].lower() == str(sector).lower()]
    desc = str(order).lower() != "asc"
    pool = _group_best([r for r in rows if r["complete"]], metric, reverse=desc)
    pool.sort(key=lambda r: r[metric], reverse=desc)
    label, unit = METRICS[metric]
    return {
        "metric": label, "unit": unit, "order": "highest first" if desc else "lowest first", "sector": sector,
        "ranking": [{"rank": i + 1, **_brief(r), "value": r[metric], "momentum_pts": r["score"], "signal": r["signal"]} for i, r in enumerate(pool[:int(limit)])],
        "companies_ranked": len(pool), "excluded_no_data": len({r["company"] for r in rows if not r["complete"]}),
    }


def t_sector_summary(sector=None):
    out = []
    for s in workbook.sector_stats():
        if sector and s["sector"].lower() != str(sector).lower():
            continue
        members = [r for r in workbook.rows() if r["sector"] == s["sector"] and r["complete"]]
        best = max(members, key=lambda r: r["score"]) if members else None
        worst = min(members, key=lambda r: r["score"]) if members else None
        out.append({
            "sector": s["sector"], "securities": s["n"], "with_data": s["n_complete"], "avg_3m_pct": s["avg_m3"], "avg_6m_pct": s["avg_m6"],
            "avg_1y_pct": s["avg_y1"], "avg_momentum_pts": s["avg_score"], "positive_signals": s["positive"], "negative_signals": s["negative"],
            "strongest": best and {**_brief(best), "momentum_pts": best["score"]}, "weakest": worst and {**_brief(worst), "momentum_pts": worst["score"]},
        })
    return {"sectors": out, "note": "Sectors are sorted by average momentum, strongest first."}


def t_recent_changes(ticker=None, material_only=True):
    comps = signals.compare()
    if ticker:
        comps = [c for c in comps if c["ticker"].upper() == str(ticker).upper()]
    elif material_only:
        comps = [c for c in comps if c["material"]]
    return {
        "since": workbook.current().snapshot_str, "feed": "real public feed: Yahoo Finance closing prices and news headlines, publisher named per event",
        "changes": [{"ticker": c["ticker"], "company": c["company"], "sector": c["sector"], "ref": c["row_id"], "material": c["material"],
                     "price_change_pct": c["price_delta_pct"], "reasons": c["reasons"],
                     "events": [{k: e[k] for k in ("id", "date", "type", "severity", "headline", "source")} for e in c["events"]]} for c in comps[:8]],
    }


def t_get_briefing(ticker=None):
    b = store.get(ticker) if ticker else None
    if not b:
        return {"available": False, "briefed_companies": store.tickers(), "hint": "No briefing exists for this company yet. Run the Account Monitor with this company in focus."}
    return {"available": True, "ticker": b["ticker"], "company": b["company"], "headline": b["headline"], "owner_team": b["owner_team"],
            "facts": b["facts"], "hypotheses": [h["text"] for h in b["hypotheses"]], "data_gaps": b["data_gaps"], "next_step": b["next_step"]}


def t_list_missing():
    rows = [r for r in workbook.rows() if not r["complete"]]
    return {"count": len(rows), "companies": [{**_brief(r), "status": r["status"]} for r in rows],
            "note": "These companies are in the workbook but lack a price or a performance value. They are excluded from rankings and never treated as zero."}


def t_data_quality():
    return {"findings": [{"severity": f["severity"], "title": f["title"], "detail": f["detail"], "action": f["action"]} for f in workbook.findings()],
            "source": workbook.current().info()}


def _no_report(row_or_ticker):
    row = row_or_ticker if isinstance(row_or_ticker, dict) else workbook.by_ticker(str(row_or_ticker))
    covered = [d["company"] for d in reports.documents() if d["available"] and reports.doc_for(d["ticker"])]
    name = row["company"] if row else str(row_or_ticker)
    return {"error": f"No public report is loaded for {name}. Reports are loaded for: {', '.join(covered) or 'no company'}."}


def t_get_financials(ticker=""):
    row = workbook.by_ticker(ticker)
    if not row:
        return {"error": f"Unknown ticker {ticker}. Use find_company first."}
    f = reports.financials(row["ticker"])
    if not f:
        return _no_report(row)
    return {**f, "snapshot": workbook.current().snapshot_str}


def t_compare_financials(tickers=None):
    out, missing = [], []
    for t in (tickers or [])[:4]:
        row = workbook.by_ticker(t)
        f = reports.financials(row["ticker"]) if row else None
        (out if f else missing).append(f or (row["company"] if row else str(t)))
    if len(out) < 2:
        return {"error": "Need reports for at least two of these companies. " + (_no_report(missing[0])["error"] if missing else "")}
    def growth(f, key):
        return next((i["growth_pct"] for i in f["items"] if i["key"] == key), None)
    rows = [{"ticker": f["ticker"], "company": f["company"], "standard": f["standard"], "currency": f["currency"],
             "revenue_growth_pct": growth(f, "revenue"), "operating_margin_pct": (f["margins"].get("operating_margin_pct") or {}).get("h1_2026"),
             "operating_label": next((i["label"] for i in f["items"] if i["key"] == "operating_profit"), None),
             "net_margin_pct": (f["margins"].get("net_margin_pct") or {}).get("h1_2026"), "net_income_growth_pct": growth(f, "net_income"),
             "refs": sorted({i["ref"] for i in f["items"]})} for f in out]
    return {"period": "H1 2026", "companies": rows, "without_report": missing,
            "note": "Growth is H1 2026 versus H1 2025. Margins are a share of revenue. Operating profit is labelled as each company reports it, so compare it with care."}


def t_search_reports(question="", ticker=None, limit=3):
    if not str(question).strip():
        return {"error": "Give a question to search for."}
    row = workbook.by_ticker(ticker) if ticker else None
    if ticker and not row:
        return {"error": f"Unknown ticker {ticker}. Use find_company first."}
    if row and not reports.doc_for(row):
        return _no_report(row)
    passages, mode = reports.search(str(question), reports.doc_for(row)["ticker"] if row else None, max(1, min(int(limit), 5)))
    if row is None:  # without a company, only report companies that are in the loaded workbook count
        passages = [p for p in passages if reports.doc_for(p["ticker"])]
    return {"question": question, "search": mode, "passages": passages, "note": "Passages are excerpts from public half-year reports (H1 2026). Quote them with their page reference."}


TOOLS = {
    "find_company": t_find_company, "get_company": t_get_company, "get_peers": t_get_peers, "compare_companies": t_compare_companies,
    "rank_companies": t_rank_companies, "sector_summary": t_sector_summary, "recent_changes": t_recent_changes,
    "get_briefing": t_get_briefing, "data_quality": t_data_quality, "list_missing_data": t_list_missing,
    "get_financials": t_get_financials, "compare_financials": t_compare_financials, "search_reports": t_search_reports,
}


def _spec(name, desc, props=None, required=None):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props or {}, "required": required or []}}}


TOOL_SPECS = [
    _spec("find_company", "Look up companies by name or ticker. Use this first when the user names a company.", {"query": {"type": "string"}}, ["query"]),
    _spec("get_company", "Full profile of one company: price, performance, momentum, signal, rank overall and in its sector.", {"ticker": {"type": "string"}}, ["ticker"]),
    _spec("get_peers", "Competitor view: peers in the same sector ranked by momentum, with the gap to the company.", {"ticker": {"type": "string"}, "limit": {"type": "integer"}}, ["ticker"]),
    _spec("compare_companies", "Side-by-side comparison of 2 to 4 companies and who leads on each measure.", {"tickers": {"type": "array", "items": {"type": "string"}}}, ["tickers"]),
    _spec("rank_companies", "Deterministic ranking. metric is one of score, m3, m6, y1, d1; order is desc or asc; optional sector.",
          {"metric": {"type": "string"}, "order": {"type": "string"}, "limit": {"type": "integer"}, "sector": {"type": "string"}}),
    _spec("sector_summary", "Average performance, signals, strongest and weakest company per sector. Omit sector for all sectors.", {"sector": {"type": "string"}}),
    _spec("recent_changes", "Changes since the market snapshot from the real public feed (closing prices and news headlines), material ones first.", {"ticker": {"type": "string"}}),
    _spec("get_briefing", "The account briefing written by the Account Monitor in this session, if one exists.", {"ticker": {"type": "string"}}, ["ticker"]),
    _spec("data_quality", "Findings about the loaded workbook: missing data, duplicates, scale problems, snapshot age."),
    _spec("list_missing_data", "Companies that have no complete market data in the workbook."),
    _spec("get_financials", "Verified headline figures from the company's public half-year report (H1 2026 versus H1 2025): revenue, operating profit, net income, growth, margins, each with a page reference. Only some companies have a report.", {"ticker": {"type": "string"}}, ["ticker"]),
    _spec("compare_financials", "Compare the reported fundamentals of 2 to 4 companies: revenue growth and margins from their public reports.", {"tickers": {"type": "array", "items": {"type": "string"}}}, ["tickers"]),
    _spec("search_reports", "Search the public half-year reports for passages that answer a question (outlook, risks, segments, explanations). Returns excerpts with page references. Pass a ticker to search one company's report.", {"question": {"type": "string"}, "ticker": {"type": "string"}, "limit": {"type": "integer"}}, ["question"]),
]


def run_tool(name, args):
    fn = TOOLS.get(name)
    if not fn:
        return {"error": f"Unknown tool {name}"}
    try:
        return fn(**{k: v for k, v in (args or {}).items() if v is not None})
    except TypeError as exc:
        return {"error": f"Bad arguments: {exc}"}


def summarize(name, res):
    if "error" in res:
        return res["error"]
    if name == "find_company":
        return ", ".join(m["ticker"] for m in res["matches"]) or "no match"
    if name == "get_company":
        return f"{res['company']} · {res['signal']} · rank {res['rank_overall']}/{res['of_overall']}"
    if name == "get_peers":
        return f"{res['peers_with_data']} peers with data in {res['sector']}"
    if name == "compare_companies":
        return " vs ".join(c["ticker"] for c in res["companies"])
    if name == "rank_companies":
        return f"{res['metric']}, {len(res['ranking'])} of {res['companies_ranked']}"
    if name == "sector_summary":
        return f"{len(res['sectors'])} sector(s)"
    if name == "recent_changes":
        return f"{len(res['changes'])} companies with changes"
    if name == "get_briefing":
        return "briefing found" if res["available"] else "no briefing yet"
    if name == "data_quality":
        return f"{len(res['findings'])} findings"
    if name == "list_missing_data":
        return f"{res['count']} companies without complete data"
    if name == "get_financials":
        return f"{res['company']} · {res['period']} · {res['standard']} · {len(res['items'])} figures"
    if name == "compare_financials":
        return " vs ".join(c["ticker"] for c in res["companies"])
    if name == "search_reports":
        return f"{len(res['passages'])} passages ({res['search']} search)"
    return "ok"


# ----------------------------------------------------------------------------- verification of answers

SOURCE_ID = r"\b(?:SEC|SIG)-\d+\b|\bREP-[A-Z]+-p\d+\b"


def verify(text, evidence):
    valid_ids = set(re.findall(SOURCE_ID, evidence))
    ids = re.findall(SOURCE_ID, text)
    ev_nums = agents.evidence_numbers(evidence)
    figures = [n for n in agents._numbers(text) if (n != int(n)) or n >= 100]
    ungrounded = [n for n in figures if not any(abs(n - e) <= 0.051 for e in ev_nums)]
    return {
        "cited": sorted(set(ids)), "unknown_sources": sorted({i for i in ids if i not in valid_ids}),
        "figures": len(figures), "ungrounded": ungrounded[:5],
        "advice": any(re.search(p, agents.strip_quotes(text), re.I) for p in agents.ADVICE_PATTERNS),
    }


def sources_for(text):
    """Source chips for every SEC-, SIG- and REP- id mentioned in an answer."""
    out = {}
    by_id = {r["id"]: r for r in workbook.rows()}
    events = {e["id"]: e for e in signals.feed()}
    for i in set(re.findall(SOURCE_ID, text)):
        if i.startswith("REP-"):
            meta = reports.source_meta(i)
            if meta:
                out[i] = meta
        elif i in by_id:
            r = by_id[i]
            out[i] = {"kind": "workbook", "label": f"Workbook row {i}", "detail": f"{r['company']} · {r['ticker']} · snapshot {workbook.current().snapshot_str}"}
        elif i in events:
            out[i] = agents.signal_source(events[i])
    return out


# ----------------------------------------------------------------------------- offline (rule-based) router

ADVICE_ASK = re.compile(r"\b(should i|shall i|do you recommend|would you)\b.*\b(buy|sell|invest|hold)\b|\bwill\b.{0,50}\b(go up|go down|rise|fall|drop|increase|outperform|underperform|beat|gain|lose)\b|\b(price target|forecast|predict|best (stock|pick)|top pick|guaranteed|which stock to buy|what to buy|recommend)\b", re.I)
SALES_ASK = re.compile(r"\b(ready to buy|likely to (buy|sign)|purchase intent|sign a deal|buy from us|buy our|close a deal|will they buy|budget)\b", re.I)
UNKNOWN_ASK = re.compile(r"\b(market share|revenue|turnover|profit|earnings|ebit|margin|ceo|cfo|executive|employees|headcount|products?|pricing|customers?|valuation|dividend|market cap)\b", re.I)
MISSING_ASK = re.compile(r"\b(no|missing|incomplete|without|lack(ing)?)\s+(market\s+)?data\b|\bwhich companies\b.*\b(missing|incomplete)\b|\bno market data\b", re.I)
QUALITY_ASK = re.compile(r"\b(data quality|issues?|problems?|findings?|gaps?|checks?|clean|errors?)\b", re.I)
BRIEF_ASK = re.compile(r"\b(briefing|brief|account plan|research plan|next step|hypothes[ie]s)\b", re.I)
CHANGE_ASK = re.compile(r"\b(chang(e|ed|es)|since|news|events?|alerts?|material|happened|latest|signals? feed|moved)\b", re.I)
COMPARE_ASK = re.compile(r"\b(compare|versus|vs\.?|against|better than|stronger than|differ)\b", re.I)
PEER_ASK = re.compile(r"\b(peers?|competitors?|competition|rivals?|compete|similar|closest|stack up|alongside|benchmark)\b", re.I)
SECTOR_ASK = re.compile(r"\b(sectors?|industr(y|ies)|branch)\b", re.I)
RANK_ASK = re.compile(r"\b(top|best|strongest|highest|leading|leaders?|weakest|worst|lowest|bottom|laggards?|pressure|negative|positive|rank|ranking|momentum)\b", re.I)
WEAK = re.compile(r"\b(weakest|worst|lowest|bottom|laggards?|pressure|negative|declin\w+|falling|lost)\b", re.I)
FIN_ASK = re.compile(r"\b(net sales|sales|revenues?|turnover|profit|earnings|ebit\w*|operating (income|profit|result)|margins?|net income|income|results?|fundamentals?|financials?|growth|grew|profitab\w*)\b", re.I)
REPORT_ASK = re.compile(r"\b(outlook|guidance|expects?|expected|risks?|strategy|segments?|according to|report says?|annual report|half[- ]year|h1|first half|interim|filings?|ifrs|cash flow|debt|employees|headcount|dividends?|market share|products?|pricing|customers?|ceo|cfo|executive)\b", re.I)


def _metric_from(text):
    low = text.lower()
    if re.search(r"\b3[- ]?m|three[- ]month|quarter", low):
        return "m3"
    if re.search(r"\b6[- ]?m|six[- ]month|half[- ]year", low):
        return "m6"
    if re.search(r"\b1[- ]?y|one[- ]year|12[- ]month|annual|year", low):
        return "y1"
    if re.search(r"\bdaily|today|day\b", low):
        return "d1"
    return "score"


def plan_offline(text, context, references=None):
    """Returns (intent, [(tool, args)]) for a user message. `references` are tickers the user clicked in the app."""
    low = text.lower()
    tickers = [r["ticker"] for r in match_companies(text)]
    refs = [r["ticker"] for r in resolve_references(references)]
    whole_workbook = (RANK_ASK.search(text) or SECTOR_ASK.search(text) or MISSING_ASK.search(text) or QUALITY_ASK.search(text)) and not PLURAL_REF.search(text)
    if refs and not whole_workbook:
        if not tickers:
            tickers = list(refs)
        elif COMPARE_ASK.search(text) or PLURAL_REF.search(text):
            tickers += [t for t in refs if t not in tickers]
    found = [workbook.by_ticker(t) for t in tickers]
    if not tickers and context and re.search(r"\b(it|its|them|they|their|that company|this company|the same|those)\b", low):
        tickers = list(context)[:2]
    sector = match_sector(text)
    if ADVICE_ASK.search(text):
        return "advice", []
    if SALES_ASK.search(text):
        return "sales", []
    covered = [t for t in tickers if reports.doc_for(t)]
    asks_fin, asks_rep = FIN_ASK.search(text), REPORT_ASK.search(text)
    if covered and (asks_fin or asks_rep):
        if asks_fin and len(covered) >= 2:
            return "fin_compare", [("compare_financials", {"tickers": covered[:4]})]
        if asks_fin and (PEER_ASK.search(text) or COMPARE_ASK.search(text)):
            me = workbook.by_ticker(covered[0])
            peers = [r["ticker"] for r in workbook.rows() if r["sector"] == me["sector"] and r["company"] != me["company"] and reports.doc_for(r)]
            if peers:
                return "fin_compare", [("compare_financials", {"tickers": [covered[0], *peers[:3]]})]
        if asks_fin:
            return "financials", [("get_financials", {"ticker": covered[0]})]
        return "report", [("search_reports", {"question": text, "ticker": covered[0]})]
    if UNKNOWN_ASK.search(text):
        return "unknown", []
    if MISSING_ASK.search(text):
        return "missing", [("list_missing_data", {})]
    if QUALITY_ASK.search(text):
        return "quality", [("data_quality", {})]
    if BRIEF_ASK.search(text):
        return "briefing", [("get_briefing", {"ticker": t}) for t in tickers[:1]] or [("get_briefing", {"ticker": ""})]
    if CHANGE_ASK.search(text) and not COMPARE_ASK.search(text):
        return "changes", [("recent_changes", {"ticker": t}) for t in tickers[:3]] or [("recent_changes", {})]
    if PEER_ASK.search(text) and tickers and len(found) < 2:
        return "peers", [("get_peers", {"ticker": tickers[0]})]
    if len(tickers) >= 2 or (COMPARE_ASK.search(text) and tickers):
        if len(tickers) == 1:
            return "peers", [("get_peers", {"ticker": tickers[0]})]
        return "compare", [("compare_companies", {"tickers": tickers[:4]})]
    if PEER_ASK.search(text) and tickers:
        return "peers", [("get_peers", {"ticker": tickers[0]})]
    if SECTOR_ASK.search(text) or (sector and not RANK_ASK.search(text)):
        return "sector", [("sector_summary", {"sector": sector} if sector else {})]
    if RANK_ASK.search(text):
        metric = _metric_from(text)
        n = re.search(r"\b(?:top|bottom|best|worst)\s+(\d+)\b|\b(\d+)\s+(?:strongest|weakest|best|worst|companies)\b", low)
        limit = int(next(g for g in n.groups() if g)) if n else 5
        both = re.search(r"(strongest|best|top).{0,25}(and|&|or).{0,25}(weakest|worst|bottom)", low) or re.search(r"(weakest|worst|bottom).{0,25}(and|&|or).{0,25}(strongest|best|top)", low)
        args = {"metric": metric, "limit": min(limit, 10), **({"sector": sector} if sector else {})}
        if both:
            return "rank2", [("rank_companies", {**args, "order": "desc", "limit": 3}), ("rank_companies", {**args, "order": "asc", "limit": 3})]
        return "rank", [("rank_companies", {**args, "order": "asc" if WEAK.search(text) else "desc"})]
    if tickers:
        return "company", [("get_company", {"ticker": tickers[0]}), ("get_peers", {"ticker": tickers[0], "limit": 3})]
    return "help", []


def _p(v, d=1):
    if v is None:
        return "n/a"
    v = 0.0 if abs(v) < 0.5 * 10 ** -d else v
    return f"{v:+.{d}f}%"


def _pts(v):
    if v is None:
        return "n/a"
    return f"{0.0 if abs(v) < 0.05 else v:.1f}"


def _sg(v):
    return f"{0.0 if abs(v) < 0.05 else v:+.1f}"


def _n(count, one, many):
    return f"{count} {one if count == 1 else many}"


def _amt(v):
    return f"{v:,.0f}" if abs(v) >= 1000 or float(v).is_integer() else f"{v:,.1f}"


def _gr(v):
    return "n/a" if v is None else f"{v:+.1f}%"


def render_offline(intent, results, text):
    ds = workbook.current()
    snap = ds.snapshot_str
    if intent == "advice":
        return ("I can't give investment advice, price targets or buy and sell views. I can show how companies compare on momentum and performance in the "
                f"workbook (snapshot {snap}), for example the strongest and weakest companies or a company against its peers.")
    if intent == "sales":
        return ("A share price does not show purchase intent, budget or demand, so I can't rank companies by how likely they are to buy. "
                "I can show where public-market momentum is strong or under pressure, and which companies had a material change since the snapshot, "
                "as a starting point for account research.")
    if intent == "unknown":
        covered = [d["company"] for d in reports.documents() if d["available"] and reports.doc_for(d["ticker"])]
        have = f" Public half-year reports are loaded for {', '.join(covered)}; ask about one of them." if covered else ""
        return (f"The workbook does not contain that. It has price and 1-day, 3-month, 6-month and 1-year performance for {len(ds.rows)} securities, "
                f"plus sector and index. There is no market share, revenue, profit, product, pricing or customer data for this company, so I can only describe peers by sector and momentum.{have}")
    if intent == "help":
        return ("I can answer questions about the companies in your workbook and how they compare with their peers. Try: the strongest and weakest companies, "
                "a company against its peers, a comparison of two companies, a sector overview, what changed since the snapshot, or which companies have no data.")
    r = results[0][2] if results else {}
    if "error" in r:
        return r["error"]
    if intent == "missing":
        if not r["count"]:
            return "Every company in the workbook has complete market data."
        lines = "\n".join(f"- {c['company']} ({c['ticker']}) [{c['ref']}]" for c in r["companies"][:10])
        more = f"\nand {r['count'] - 10} more." if r["count"] > 10 else ""
        return f"{_n(r['count'], 'company has', 'companies have')} no complete market data:\n{lines}{more}\nThey are excluded from rankings and are never treated as zero."
    if intent == "quality":
        lines = [f"- {f['title']}: {f['action']}" for f in r["findings"]]
        return "Here is what I found when checking the workbook:\n" + "\n".join(lines)
    if intent == "briefing":
        if not r["available"]:
            names = ", ".join(r["briefed_companies"]) or "none yet"
            return f"There is no briefing for that company yet. Briefings in this session: {names}. Run the Account Monitor with the company in focus to create one."
        facts = "\n".join(f"- {f['text']} [{f['source']}]" for f in r["facts"][:6])
        return f"Briefing for {r['company']}: {r['headline']}\n{facts}\nNext step: {r['next_step']}"
    if intent == "changes":
        changes = [c for _t, _a, res in results for c in res.get("changes", [])]
        if not changes:
            return "There are no changes for that company in the public feed since the snapshot."
        lines = []
        for c in changes[:5]:
            refs = " ".join(f"[{e['id']}]" for e in c["events"][:2])
            what = "; ".join(c["reasons"]) or (f"\u201c{c['events'][0]['headline']}\u201d" if c["events"] else "no event")
            by = ", ".join(dict.fromkeys(e["source"] for e in c["events"][:2]))
            lines.append(f"- {c['company']} ({c['ticker']}): {what} ({by}) {refs}".rstrip())
        return f"Changes since the snapshot of {snap} (public feed: Yahoo Finance closes and news headlines, most important first):\n" + "\n".join(lines)
    if intent in ("rank", "rank2"):
        parts = []
        for _t, _a, res in results:
            where = f" in {res['sector']}" if res["sector"] else ""
            unit = " pts" if res["unit"] == "pts" else "%"
            rows = "\n".join(f"- {x['rank']}. {x['company']} ({x['ticker']}): {_sg(x['value'])}{unit} [{x['ref']}]" for x in res["ranking"])
            parts.append(f"{res['metric'].capitalize()}{where}, {res['order']}:\n{rows}")
        extra = results[0][2]["excluded_no_data"]
        tail = f"\n{_n(extra, 'company', 'companies')} without complete data {'is' if extra == 1 else 'are'} excluded, not counted as zero." if extra else ""
        return "\n".join(parts) + tail
    if intent == "sector":
        secs = r["sectors"]
        if not secs:
            return "I couldn't find that sector in the workbook."
        if len(secs) == 1:
            s = secs[0]
            return (f"{s['sector']}: {s['with_data']} of {s['securities']} securities have data. Average 3M {_p(s['avg_3m_pct'])}, 1Y {_p(s['avg_1y_pct'])}, momentum {_pts(s['avg_momentum_pts'])} pts. "
                    f"Strongest: {s['strongest']['company']} ({_pts(s['strongest']['momentum_pts'])} pts) [{s['strongest']['ref']}]. Weakest: {s['weakest']['company']} ({_pts(s['weakest']['momentum_pts'])} pts) [{s['weakest']['ref']}].")
        top, bottom = secs[0], secs[-1]
        lines = "\n".join(f"- {s['sector']}: momentum {_pts(s['avg_momentum_pts'])} pts, 1Y {_p(s['avg_1y_pct'])}, {s['positive_signals']} positive and {s['negative_signals']} negative signals" for s in secs[:5])
        lead = top["strongest"]
        return (f"Sectors by average momentum: {top['sector']} is strongest and {bottom['sector']} is weakest.\n{lines}\n"
                f"Strongest company in {top['sector']}: {lead['company']} ({_pts(lead['momentum_pts'])} pts) [{lead['ref']}].")
    if intent == "compare":
        cs = r["companies"]
        lines = "\n".join(f"- {c['company']} ({c['ticker']}): momentum {_pts(c['momentum_pts'])} pts ({c['signal']}), 3M {_p(c['perf_3m_pct'])}, 1Y {_p(c['perf_1y_pct'])} [{c['ref']}]" if c["has_data"]
                          else f"- {c['company']} ({c['ticker']}): no complete market data in the workbook, so it can't be compared [{c['ref']}]" for c in cs)
        lead = r["leader_by"]
        names = {c["ticker"]: c["company"] for c in cs}
        tail = ""
        if lead.get("momentum_pts"):
            tail = f"\nHigher momentum: {names[lead['momentum_pts']]}. Higher 1-year performance: {names[lead['perf_1y']]}."
        if not r["same_sector"]:
            tail += "\nThese companies are in different sectors, so they are not direct peers."
        return "Comparison:\n" + lines + tail
    if intent == "peers":
        c = r["company"]
        if r["company_momentum_pts"] is None:
            return f"{c['company']} has no complete market data, so I can't rank it against its peers [{c['ref']}]. Peers in {r['sector']} with data: {r['peers_with_data']}."
        peers = r["peers"][:4]
        if not peers:
            return f"{c['company']} has no peers with data in {r['sector']} in this workbook [{c['ref']}]."
        lines = "\n".join(f"- {p['company']} ({p['ticker']}): {_pts(p['momentum_pts'])} pts, {abs(p['gap_pts']):.1f} pts {'ahead' if p['gap_pts'] > 0 else 'behind'} [{p['ref']}]" for p in peers)
        return (f"{c['company']} ({c['ticker']}) ranks {r['rank_among_sector']} of {r['of_companies_with_data']} in {r['sector']} with {_pts(r['company_momentum_pts'])} pts ({r['company_signal']}) [{c['ref']}].\n"
                f"Closest peers by momentum:\n{lines}\nPeers means same-sector companies in this workbook. It has no market share, revenue or product data.")
    if intent == "company":
        c, peers = results[0][2], results[1][2]
        if not c["has_data"]:
            return f"{c['company']} ({c['ticker']}) is in the workbook but has no complete market data, so there is no momentum or signal [{c['ref']}]."
        head = (f"{c['company']} ({c['ticker']}), {c['sector']}: price CHF {c['price_chf']}, 3M {_p(c['perf_3m_pct'])}, 1Y {_p(c['perf_1y_pct'])}, "
                f"momentum {_pts(c['momentum_pts'])} pts ({c['signal']}), rank {c['rank_overall']} of {c['of_overall']} overall and {c['rank_in_sector']} of {c['of_sector']} in its sector [{c['ref']}].")
        if peers.get("peers"):
            p = peers["peers"][0]
            head += f"\nNearest peer: {p['company']} ({p['ticker']}) with {_pts(p['momentum_pts'])} pts [{p['ref']}]."
        return head
    if intent == "financials":
        items = {i["key"]: i for i in r["items"]}
        lines = "\n".join(f"- {i['label']} {_amt(i['h1_2026'])} ({_gr(i['growth_pct'])} vs H1 2025) [{i['ref']}]" for i in r["items"])
        mg = r["margins"].get("operating_margin_pct")
        tail = f"\nOperating margin {mg['h1_2026']:.1f}% (H1 2025: {mg['h1_2025']:.1f}%)." if mg and "operating_profit" in items else ""
        return (f"{r['company']} ({r['ticker']}), {r['period']} report, {r['standard']}, {r['currency']} millions:\n{lines}{tail}\n"
                f"The report covers the first half of 2026. Market prices in the workbook are from {snap}.")
    if intent == "fin_compare":
        lines = []
        for c in r["companies"]:
            plain = c["operating_label"] in ("Operating income", "Operating profit", "EBIT")
            op = f", operating margin {c['operating_margin_pct']:.1f}%{'' if plain else ' (as ' + str(c['operating_label']) + ')'}" if c["operating_margin_pct"] is not None else ""
            nm = f", net margin {c['net_margin_pct']:.1f}%" if c["net_margin_pct"] is not None else ""
            lines.append(f"- {c['company']} ({c['ticker']}): revenue {_gr(c['revenue_growth_pct'])}{op}{nm} [{c['refs'][0]}]")
        miss = f"\nNo report is loaded for {', '.join(r['without_report'])}." if r["without_report"] else ""
        return "H1 2026 fundamentals from the public reports (revenue growth versus H1 2025, margins as a share of revenue):\n" + "\n".join(lines) + miss + "\nOperating profit is labelled as each company reports it, so compare it with care."
    if intent == "report":
        ps = r["passages"][:2]
        if not ps:
            return "I could not find a matching passage in the loaded reports."
        def cut(s, n=230):
            s = re.sub(r"\s+", " ", s).strip()
            return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"
        generic = {"report", "say", "says", "half", "year", "h1", "2026", "company", "according", "tell", "show"} | set(reports._tokens(ps[0]["company"]))
        terms = [w for w in reports._tokens(text) if w not in generic and not w.isdigit()]
        direct = any(w in re.sub(r"\s+", " ", p["text"]).lower() for p in ps for w in terms)
        lead = "The closest passages" if direct else "No passage in the report mentions that directly. The closest text"
        lines = "\n".join(f"- “{cut(p['text'])}” [{p['ref']}]" for p in ps)
        return f"{lead} in the {ps[0]['company']} {ps[0]['period']} report:\n{lines}\nI show the text as written. For exact headline figures ask for the company's results."
    return "I'm not sure how to answer that from the workbook. Try asking about a company, a sector, peers or what changed."


# ----------------------------------------------------------------------------- the conversation

def system_prompt():
    ds = workbook.current()
    return f"""You are the Insights Assistant. The user is chatting with the results of a peer and competitor analysis built from an Excel workbook of public-market data ("{ds.name}", snapshot {ds.snapshot_str}, {len(ds.rows)} securities).

How to work:
- Call tools to get facts. Never rely on memory, and never rank or do arithmetic in your head: use rank_companies, compare_companies and get_peers.
- "Competitors" means peers in the same sector in this workbook. The workbook itself has no market share, revenue, product, pricing or customer data. Say so when asked.
- For revenue, profit, margins and growth use get_financials or compare_financials: they hold verified figures from public half-year reports (H1 2026 versus H1 2025), but only for a few companies. Use search_reports for explanations, outlook and risks, and quote only what the passages say. If a company has no report, say so. Never state revenue or profit from memory.
- Report figures are for the first half of 2026. Market prices in the workbook are from a different date; say so when you mix them.
- Cite sources with the ref ids from tool results, like [SEC-028], [SIG-003] or [REP-NOVN-p3] (report page). Every figure needs a citation. Cite only ids that appeared in tool results for this question. Never invent or write placeholder ids. If you called no tool, cite nothing.
- SIG ids are real: end-of-day closes from Yahoo Finance and news headlines from public media. Name the publisher and the date when you use one, quote headlines instead of paraphrasing them, and say that headlines were not checked against company filings when reliability matters.
- If has_data is false the data is missing. Never treat it as zero.
- The only performance periods in the workbook are daily, 3 months, 6 months and 1 year, plus the momentum score. There is no 1-month, 5-year or year-to-date figure; never mention one.
- Never give investment advice, price targets, forecasts or buy and sell views. Share-price performance is not evidence of demand or purchase intent.
- Answer in at most 110 words. Use short bullet lines starting with "-" if helpful. No tables, no headings.
- If the message says the user selected companies in the app, treat them as the subject of the question, unless it names other companies or asks about the whole workbook.
- If the question is unrelated to the workbook, say what you can help with."""


def _clean_history(history):
    out = []
    for m in (history or [])[-MAX_TURNS:]:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            out.append({"role": m["role"], "content": m["content"][:2000]})
    return out


POLICY_BLOCK = ("I held back that answer because it contained advice-like wording. I can't give investment advice or predictions. "
                "Ask me to compare companies, show peers or summarise what changed and I'll answer from the workbook.")


async def chat_events(message, history=None, context=None, mode="offline", references=None):
    live = mode == "live" and llm.live_available()
    refs = resolve_references(references)
    reports.use_semantic(live)
    message = (message or "").strip()[:1000]
    t0 = time.perf_counter()
    tin = tout = 0
    cost = 0.0
    evidence = []
    steps = []
    yield {"type": "start", "mode": "live" if live else "offline", "model": MODELS["assistant"] if live else "rule-based router",
           "references": [{"ticker": r["ticker"], "company": r["company"]} for r in refs]}
    if not message:
        yield {"type": "error", "message": "Please type a question."}
        return

    def tool_events(name, args, res):
        evidence.append(json.dumps(res, default=str))
        steps.append({"tool": name, "args": args, "summary": summarize(name, res)})

    answer = None
    if live:
        messages = [{"role": "system", "content": system_prompt()}, *_clean_history(history), {"role": "user", "content": message + reference_note(refs)}]
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                yield {"type": "thinking", "model": MODELS["assistant"]}
                r = await llm.chat(MODELS["assistant"], messages, tools=TOOL_SPECS, max_tokens=3000)
                tin, tout, cost = tin + r["tokens_in"], tout + r["tokens_out"], cost + r["cost"]
                if r["tool_calls"]:
                    messages.append({"role": "assistant", "content": r["content"] or None, "tool_calls": [
                        {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}} for tc in r["tool_calls"]]})
                    for tc in r["tool_calls"]:
                        try:
                            args = json.loads(tc["arguments"] or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        yield {"type": "tool_call", "tool": tc["name"], "args": args}
                        await asyncio.sleep(0.25)
                        res = await asyncio.to_thread(run_tool, tc["name"], args)
                        tool_events(tc["name"], args, res)
                        yield {"type": "tool_result", "tool": tc["name"], "summary": summarize(tc["name"], res)}
                        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res, default=str)})
                    continue
                answer = r["content"].strip()
                break
        except Exception as exc:  # noqa: BLE001
            yield {"type": "warning", "message": f"Live call failed ({type(exc).__name__}). Answering offline."}
            live, answer = False, None
            evidence.clear()
            steps.clear()
    if answer is None:
        intent, calls = plan_offline(message, context, [r["ticker"] for r in refs])
        yield {"type": "thinking", "model": "rule-based router"}
        await asyncio.sleep(0.9)
        results = []
        for name, args in calls:
            yield {"type": "tool_call", "tool": name, "args": args}
            await asyncio.sleep(1.0)
            res = await asyncio.to_thread(run_tool, name, args)
            tool_events(name, args, res)
            results.append((name, args, res))
            yield {"type": "tool_result", "tool": name, "summary": summarize(name, res)}
        await asyncio.sleep(0.5)
        answer = render_offline(intent, results, message)
    check = verify(answer, "\n".join(evidence))
    blocked = check["advice"]
    if blocked:
        answer = POLICY_BLOCK
        check = verify(answer, "")
    mentioned = [t for t in re.findall(r"\(([A-Z]{2,5})\)", answer)] or [r["ticker"] for r in refs] or list(context or [])
    yield {
        "type": "answer", "text": answer, "sources": sources_for(answer), "checks": check, "blocked": blocked, "steps": steps,
        "context": mentioned[:3], "followups": followups(message, steps, mentioned, blocked), "live": live, "tokens_in": tin, "tokens_out": tout, "cost": round(cost, 5), "elapsed": round(time.perf_counter() - t0, 1),
    }
    yield {"type": "done"}


def followups(message, steps, tickers, blocked=False):
    """Up to three next questions that build on the answer just given. Each one can be answered from the loaded data."""
    by_ticker = {r["ticker"]: r for r in workbook.rows()}
    used = {s["tool"] for s in steps}
    known = [by_ticker[t] for t in tickers if t in by_ticker and by_ticker[t]["complete"]]
    out = []
    if known:
        a = known[0]["company"]
        if reports.doc_for(known[0]["ticker"]):
            if not {"get_financials", "compare_financials"} & used:
                out.append(f"What were {a}'s results in H1 2026?")
            elif "search_reports" not in used:
                out.append(f"What does the {a} report say about the outlook?")
        if len(known) >= 2 and "compare_companies" not in used:
            out.append(f"Compare {a} and {known[1]['company']}")
        if "get_peers" not in used:
            out.append(f"Who are {a}'s closest competitors?")
        if "recent_changes" not in used:
            out.append(f"What changed for {a}?")
        if "get_company" not in used:
            out.append(f"Tell me about {a}")
    if "rank_companies" not in used or blocked:
        out.append("Who are the strongest and weakest companies by momentum?")
    if "sector_summary" not in used:
        out.append("Which sector shows the strongest momentum?")
    out.append("What changed since the snapshot?")
    out.append("Which companies have no market data?")
    seen, result = {message.strip().lower()}, []
    for q in out:
        if q.lower() not in seen:
            seen.add(q.lower())
            result.append(q)
    return result[:3]


def _pick(r):
    """What the peer explorer shows for one company."""
    return {"ticker": r["ticker"], "tickers": r["share_classes"], "company": r["company"], "short": clean_company(r["company"]), "sector": r["sector"],
            "score": r["score"], "signal": r["signal"], "m3": r["m3"], "y1": r["y1"], "has_data": r["complete"],
            "has_report": bool(reports.doc_for(r["ticker"])), "events": len(signals.events_for(r["ticker"]))}


def company_list():
    """One entry per company, by name, for the picker and for turning (TICKER) mentions into clickable chips."""
    seen, out = set(), []
    for r in sorted(workbook.rows(), key=lambda x: x["company"].lower()):
        if r["company"] not in seen:
            seen.add(r["company"])
            out.append(_pick(primary_row(r)))
    return out


def peer_panel(ticker, limit=12):
    """A company and its sector peers, strongest momentum first. Companies without data are only counted."""
    r = workbook.by_ticker(ticker)
    if not r:
        return None
    r = primary_row(r)
    others = [primary_row(x) for x in workbook.rows() if x["sector"] == r["sector"] and x["company"] != r["company"]]
    others = list({x["company"]: x for x in others}.values())
    with_data = sorted((x for x in others if x["complete"]), key=lambda x: -x["score"])
    return {"company": _pick(r), "sector": r["sector"], "peers": [_pick(x) for x in with_data[:limit]],
            "more": max(0, len(with_data) - limit), "without_data": sum(1 for x in others if not x["complete"])}


def suggestions():
    """Starter questions built from the loaded data so they always work."""
    rows = workbook.rows()
    complete = [r for r in rows if r["complete"]]
    out = [
        {"label": "Strongest and weakest", "prompt": "Who are the strongest and weakest companies by momentum?", "kind": "rank"},
        {"label": "What changed?", "prompt": "What changed since the snapshot?", "kind": "changes"},
        {"label": "Sector overview", "prompt": "Which sector shows the strongest momentum?", "kind": "sector"},
    ]
    by_sector = defaultdict(list)
    for r in complete:
        by_sector[r["sector"]].append(r)
    big = max(by_sector.values(), key=len, default=[])
    if len(big) >= 3:
        best = sorted(big, key=lambda r: -r["score"])
        out.insert(1, {"label": f"{best[0]['company'].split(' ')[0]}'s competitors", "prompt": f"Who are {best[0]['company']}'s closest competitors and how does it compare?", "kind": "peers"})
        out.insert(2, {"label": "Compare two peers", "prompt": f"Compare {best[0]['company']} and {best[1]['company']}", "kind": "compare"})
    covered = [r for r in complete if reports.doc_for(r)]
    if covered:
        out.append({"label": f"{covered[0]['company'].split(' ')[0]} H1 results", "prompt": f"What were {covered[0]['company']}'s net sales and operating income in H1 2026?", "kind": "report"})
        twin = next((r for r in covered[1:] if r["sector"] == covered[0]["sector"]), None)
        if twin:
            out.append({"label": "Compare fundamentals", "prompt": f"Compare the financials of {covered[0]['company']} and {twin['company']}", "kind": "report"})
    if len(rows) != len(complete):
        out.append({"label": "Missing data", "prompt": "Which companies have no market data?", "kind": "quality"})
    out.append({"label": "Try a trap", "prompt": "Should I buy the strongest stock?", "kind": "trap"})
    return out







