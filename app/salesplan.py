"""Sales plan: picks up the Cowork shortlist and turns it into a competitive, evidence-backed plan for selling Microsoft products.

The shortlist and its hypotheses come from Cowork (data/cowork_shortlist.json). This module checks each hypothesis against the
workbook, the real news feed and the public reports, compares each account with its sector peers, maps the buying triggers it
finds to Microsoft solution plays and spreads a limited number of seller days across the accounts.
The plays are the partner's own playbook, not data about the companies. Every company fact cites its source.
"""
import asyncio
import json
import re
import time

from . import agents, chat, llm, reports, signals, workbook
from .config import MODELS, ROOT

SHORTLIST_PATH = ROOT / "data" / "cowork_shortlist.json"
DEFAULT_DAYS = 20
MAX_DAYS = 60
MAX_ACCOUNTS = 5

# Which buying theme a headline speaks to. Headlines are matched word by word; price moves are never a theme.
THEMES = {
    "cost": {"label": "Cost pressure", "words": re.compile(r"\b(costs?|savings?|efficien\w*|levy|backstop|restructur\w*|job cuts?|cuts? jobs|layoffs?|capital rules)\b", re.I)},
    "regulation": {"label": "Regulation", "words": re.compile(r"\b(regulat\w*|capital rules|lawmakers|levy|backstop|complian\w*|probe|fines?|sanctions?)\b", re.I)},
    "growth": {"label": "Demand growth", "words": re.compile(r"\b(demand|surges?|sales grow|record|orders|capacity|expan(ds|sion)|above (its )?guidance|raises? (its )?outlook)\b", re.I)},
    "portfolio": {"label": "Portfolio change", "words": re.compile(r"\b(proceeds|divest\w*|disposal|acqui\w*|merger|spin[- ]?off|carve[- ]?out|takeover|stake)\b", re.I)},
}

# The partner's playbook: which Microsoft offer answers which theme. Edit freely; nothing here is a fact about a company.
PLAYS = {
    "finops": {
        "name": "FinOps for cloud and AI", "theme": "cost",
        "products": ["Microsoft Cost Management", "FinOps toolkit", "Azure savings plans", "Model router in Microsoft Foundry"],
        "pitch": "Make cloud and AI spend visible per business line, and run each AI task on the cheapest model that meets the quality bar.",
        "questions": ["Who owns cloud and AI spend today, and how is it charged back?", "Which AI use cases have a cost per transaction target?",
                      "How do you pick a model when a cheaper one is good enough?"],
        "proof": {"label": "Model Bake-off: same quality for a fraction of the cost", "page": "bakeoff"},
        "meeting": "CIO office and the FinOps lead",
    },
    "resilience": {
        "name": "Compliance and resilience", "theme": "regulation",
        "products": ["Microsoft Purview", "Microsoft Defender for Cloud", "Microsoft Sentinel", "Evaluations in Microsoft Foundry"],
        "pitch": "Show the regulator, at any time, where data sits, who can reach it and how every AI agent was tested before it went live.",
        "questions": ["Which new rules change your reporting or capital planning this year?", "How do you prove an AI agent is safe before it goes live?",
                      "Where would a change of domicile or entity structure hit your IT?"],
        "proof": {"label": "Trust Lab: an agent is tested before it goes live", "page": "trust"},
        "meeting": "CISO and the head of compliance",
    },
    "scale": {
        "name": "Scale operations with data and AI", "theme": "growth",
        "products": ["Microsoft Fabric", "Dynamics 365 Supply Chain Management", "Foundry Agent Service"],
        "pitch": "Turn demand signals into production and supply plans faster, with agents that watch orders, capacity and suppliers.",
        "questions": ["How far ahead can you see demand from your largest customers?", "Where does planning still run on spreadsheets?",
                      "What slows you down when orders jump?"],
        "proof": {"label": "Account Monitor: agents run a process, a person decides", "page": "monitor"},
        "meeting": "COO and the head of supply chain",
    },
    "integration": {
        "name": "Carve-out and data platform", "theme": "portfolio",
        "products": ["Azure Migrate", "Microsoft Entra ID", "Microsoft Fabric"],
        "pitch": "Separate or combine businesses cleanly: identities, applications and data on one platform with a clear cost per unit.",
        "questions": ["Which systems are still shared with a business you sold or bought?", "How long do transition services run?",
                      "What does the leaner operating model mean for IT?"],
        "proof": {"label": "Upload workbook: data is checked before anyone relies on it", "page": "upload"},
        "meeting": "CFO office and the transformation lead",
    },
}
THEME_PLAY = {p["theme"]: k for k, p in PLAYS.items()}
HYPOTHESIS_POINTS = {"Evidence found": 3, "Mixed evidence": 1.5, "Contradicted": 0, "Not in our sources": 0}


# ----------------------------------------------------------------------------- the shortlist from Cowork

def shortlist_file():
    try:
        data = json.loads(SHORTLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"accounts": []}
    return data


def default_tickers():
    """Shortlisted tickers that exist in the loaded workbook. Falls back to the three strongest companies for another file."""
    out = [a["ticker"] for a in shortlist_file().get("accounts", []) if workbook.by_ticker(a["ticker"])]
    if not out:
        out = [r["ticker"] for r in chat.t_rank_companies("score", "desc", 3)["ranking"]] if workbook.rows() else []
    return out[:MAX_ACCOUNTS]


def cowork_entry(ticker):
    row = workbook.by_ticker(ticker)
    for a in shortlist_file().get("accounts", []):
        if row and a["ticker"] in row["share_classes"]:
            return a
    return None


def resolve(tickers):
    """Workbook rows for the requested accounts, one per company, unknown tickers dropped."""
    return chat.resolve_references(tickers)[:MAX_ACCOUNTS] if tickers else chat.resolve_references(default_tickers())


# ----------------------------------------------------------------------------- evidence per account

def _short(company):
    return re.sub(r"\s+(AG|SA|Ltd\.?|Group|Holding|Inc\.?)\b.*$", "", company, flags=re.I).strip()


TYPE_THEME = {"restructuring": "cost", "regulatory": "regulation"}  # the feed's own headline rules, used next to ours


def themes_of(headline, kind=None):
    out = [k for k, t in THEMES.items() if t["words"].search(headline or "")]
    if TYPE_THEME.get(kind) and TYPE_THEME[kind] not in out:
        out.append(TYPE_THEME[kind])
    return out


def evidence(ticker):
    """Every item that speaks to a buying theme: news headlines (word rules) and report figures. Each item cites its source."""
    row = workbook.by_ticker(ticker)
    if not row:
        return []
    items = []
    for e in signals.events_for(row["ticker"]):
        if e["kind"] != "news":
            continue
        for th in themes_of(e["headline"], e["type"]):
            items.append({"id": e["id"], "kind": "news", "theme": th, "stance": "supports", "date": e["date"],
                          "text": f"“{e['headline']}” ({e['source']}, {e['date']})"})
    fin = reports.financials(row["ticker"])
    if fin:
        by = {i["key"]: i for i in fin["items"]}
        rev, margin = by.get("revenue"), fin["margins"].get("operating_margin_pct")
        if rev and rev["growth_pct"] is not None:
            items.append({"id": rev["ref"], "kind": "report", "theme": "growth", "stance": "supports" if rev["growth_pct"] > 0 else "counters", "date": fin["period_end"],
                          "text": f"{rev['label']} {chat._amt(rev['h1_2026'])} vs {chat._amt(rev['h1_2025'])} {fin['currency']} m ({chat._gr(rev['growth_pct'])}), H1 2026 vs H1 2025"})
        if margin and "operating_profit" in by:
            up = margin["h1_2026"] > margin["h1_2025"]
            label = by["operating_profit"]["label"]
            items.append({"id": by["operating_profit"]["ref"], "kind": "report", "theme": "cost", "stance": "supports", "date": fin["period_end"],
                          "text": f"{label} margin {'up' if up else 'down'} from {margin['h1_2025']}% to {margin['h1_2026']}% in H1 2026"
                                  + (" while sales fell: cost discipline is working" if up and rev and (rev["growth_pct"] or 0) < 0 else "" if up else ": costs grew faster than sales")})
    return items


def check_hypothesis(ticker, items=None):
    entry = cowork_entry(ticker)
    items = evidence(ticker) if items is None else items
    if not entry:
        return {"hypothesis": None, "theme": None, "status": "No Cowork hypothesis", "supports": [], "counters": []}
    th = entry.get("theme")
    sup = [i for i in items if i["theme"] == th and i["stance"] == "supports"]
    con = [i for i in items if i["theme"] == th and i["stance"] == "counters"]
    status = "Mixed evidence" if sup and con else "Evidence found" if sup else "Contradicted" if con else "Not in our sources"
    return {"hypothesis": entry["hypothesis"], "why": entry.get("why"), "theme": th, "theme_label": THEMES.get(th, {}).get("label", th),
            "status": status, "supports": sup, "counters": con}


def plays_for(ticker, items=None):
    """The Microsoft plays whose theme has evidence for this account, strongest first, plus the play for the Cowork theme."""
    items = evidence(ticker) if items is None else items
    entry = cowork_entry(ticker)
    out = []
    for key, p in PLAYS.items():
        ev = [i for i in items if i["theme"] == p["theme"] and i["stance"] == "supports"]
        from_cowork = bool(entry and entry.get("theme") == p["theme"])
        if ev or from_cowork:
            out.append({"key": key, **p, "theme_label": THEMES[p["theme"]]["label"], "evidence": ev, "from_cowork": from_cowork,
                        "fit": "Evidence and Cowork agree" if ev and from_cowork else "Evidence" if ev else "Cowork hypothesis only"})
    out.sort(key=lambda p: (-len(p["evidence"]), not p["from_cowork"]))
    return out


def account(ticker):
    row = workbook.by_ticker(ticker)
    if not row:
        return {"error": f"Unknown ticker {ticker}. Use find_company first."}
    row = chat.primary_row(row)
    items = evidence(row["ticker"])
    hyp = check_hypothesis(row["ticker"], items)
    plays = plays_for(row["ticker"], items)
    supporting = {i["id"] for i in items if i["stance"] == "supports"}
    parts = {"evidence": min(4, len(supporting)), "hypothesis": HYPOTHESIS_POINTS.get(hyp["status"], 0),
             "plays": min(3, 1.5 * sum(1 for p in plays if p["evidence"]))}
    prof = chat.t_get_company(row["ticker"])
    return {
        "ticker": row["ticker"], "company": row["company"], "short": _short(row["company"]), "sector": row["sector"], "ref": row["id"],
        "has_data": row["complete"], "momentum_pts": row["score"], "signal": row["signal"], "perf_3m_pct": row["m3"], "perf_1y_pct": row["y1"],
        "rank_in_sector": prof.get("rank_in_sector"), "of_sector": prof.get("of_sector"),
        "cowork": cowork_entry(row["ticker"]), "hypothesis": hyp, "evidence": items, "plays": plays,
        "priority": round(sum(parts.values()) * 2) / 2, "priority_parts": parts, "has_report": bool(reports.financials(row["ticker"])),
        "note": "Priority counts evidence for buying triggers, not share-price moves: a price move says nothing about demand for Microsoft products.",
    }


def allocate(accounts, days):
    """Spreads seller days in proportion to priority (largest remainder). Accounts with priority 0 get none."""
    days = max(0, min(MAX_DAYS, int(days)))
    total = sum(a["priority"] for a in accounts)
    if not total or not days:
        return {a["ticker"]: 0 for a in accounts}
    raw = {a["ticker"]: days * a["priority"] / total for a in accounts}
    out = {t: int(v) for t, v in raw.items()}
    for t in sorted(raw, key=lambda t: (-(raw[t] - out[t]), t))[:days - sum(out.values())]:
        out[t] += 1
    return out


def overview(tickers=None, days=DEFAULT_DAYS):
    accs = [account(r["ticker"]) for r in resolve(tickers)]
    alloc = allocate(accs, days)
    for a in accs:
        a["days"] = alloc[a["ticker"]]
    order = sorted(accs, key=lambda a: -a["priority"])  # stable: a tie keeps the Cowork order
    shortlist = shortlist_file()
    return {"accounts": accs, "order": [a["ticker"] for a in order], "days": max(0, min(MAX_DAYS, int(days))), "source": shortlist.get("source", "Cowork shortlist"),
            "plays": {k: {"name": p["name"], "products": p["products"], "theme": p["theme"]} for k, p in PLAYS.items()},
            "themes": {k: t["label"] for k, t in THEMES.items()}, "workbook": workbook.current().info(), "snapshot": workbook.current().snapshot_str,
            "candidates": chat.company_list(), "sources": chat.sources_for(" ".join([a["ref"] for a in accs] + [i["id"] for a in accs for i in a["evidence"]]))}


# ----------------------------------------------------------------------------- competitors

def competitors(ticker, limit=6):
    """The account against its sector peers: momentum, performance, report figures and the themes peers face in the news."""
    row = workbook.by_ticker(ticker)
    if not row:
        return {"error": f"Unknown ticker {ticker}. Use find_company first."}
    row = chat.primary_row(row)
    peers = chat.t_get_peers(row["ticker"], limit)
    peer_rows = [workbook.by_ticker(p["ticker"]) for p in peers.get("peers", [])]
    sector_rows = [r for r in workbook.rows() if r["sector"] == row["sector"] and r["complete"]]
    avg_1y = round(sum(r["y1"] for r in sector_rows) / len(sector_rows), 2) if sector_rows else None
    own = set(i["theme"] for i in evidence(row["ticker"]) if i["stance"] == "supports")
    shared, peer_news = {}, []
    seen_peer = set()
    for pr in [chat.primary_row(r) for r in workbook.rows() if r["sector"] == row["sector"] and r["company"] != row["company"]]:
        if pr["company"] in seen_peer:
            continue
        seen_peer.add(pr["company"])
        for e in signals.events_for(pr["ticker"]):
            if e["kind"] != "news":
                continue
            ths = themes_of(e["headline"], e["type"])
            for th in ths:
                shared.setdefault(th, set()).add(pr["ticker"])
            peer_news.append({"id": e["id"], "ticker": pr["ticker"], "company": pr["company"], "date": e["date"], "headline": e["headline"], "source": e["source"],
                              "themes": ths, "type": e["type"]})
    peer_news.sort(key=lambda n: (not n["themes"], -int(n["date"].replace("-", ""))))
    fin = reports.financials(row["ticker"])
    peer_fin = [f for f in (reports.financials(r["ticker"]) for r in peer_rows if r) if f]
    ids = [row["id"], *(p["ref"] for p in peers.get("peers", [])), *(n["id"] for n in peer_news[:5]), *((i["ref"] for i in fin["items"]) if fin else [])]
    return {
        "sources": chat.sources_for(" ".join(ids)),
        "company": {**chat._brief(row), "momentum_pts": row["score"], "perf_3m_pct": row["m3"], "perf_1y_pct": row["y1"], "signal": row["signal"]},
        "sector": row["sector"], "peers": peers.get("peers", []), "peers_without_data": peers.get("peers_without_data", []),
        "rank_in_sector": peers.get("rank_among_sector"), "of_sector": peers.get("of_companies_with_data"), "sector_avg_1y_pct": avg_1y,
        "shared_themes": [{"theme": th, "label": THEMES[th]["label"], "peers": sorted(ts), "account_has_it": th in own} for th, ts in sorted(shared.items(), key=lambda x: -len(x[1]))],
        "peer_news": peer_news[:5],
        "financials": fin and {"ref": fin["report"]["ref"], "items": fin["items"], "margins": fin["margins"], "currency": fin["currency"]},
        "peers_with_report": [f["ticker"] for f in peer_fin],
        "note": "Peers are companies in the same sector in this workbook. The workbook has no market share or product data.",
    }


# ----------------------------------------------------------------------------- talk track

def talk_track(ticker, play=None):
    acc = account(ticker)
    if "error" in acc:
        return acc
    plays = {p["key"]: p for p in acc["plays"]}
    key = play if play in plays else (acc["plays"][0]["key"] if acc["plays"] else None)
    if not key:
        return {"error": f"No Microsoft play has evidence for {acc['company']} yet."}
    p = plays[key]
    comp = competitors(acc["ticker"])
    shared = next((s for s in comp.get("shared_themes", []) if s["theme"] == p["theme"]), None)
    peer_item = next((n for n in comp.get("peer_news", []) if p["theme"] in n["themes"]), None)
    ids = [i["id"] for i in p["evidence"][:1]] + ([peer_item["id"]] if peer_item else [])
    return {"ticker": acc["ticker"], "company": acc["company"], "play": key, "play_name": p["name"], "products": p["products"], "sources": chat.sources_for(" ".join(ids)),
            "opener": p["evidence"][0] if p["evidence"] else None, "peer_angle": peer_item and {**peer_item, "peers_with_theme": shared["peers"] if shared else []},
            "rank_in_sector": acc["rank_in_sector"], "of_sector": acc["of_sector"], "sector": acc["sector"], "ref": acc["ref"],
            "questions": p["questions"], "proof": p["proof"], "meeting": p["meeting"], "pitch": p["pitch"]}


# ----------------------------------------------------------------------------- the plan assistant

UI_ACTIONS = {"show_account", "add_to_plan", "set_seller_days"}


def t_get_shortlist(tickers=None, days=DEFAULT_DAYS):
    ov = overview(tickers, days)
    return {"days": ov["days"], "source": ov["source"], "accounts": [
        {"ticker": a["ticker"], "company": a["company"], "ref": a["ref"], "priority": a["priority"], "priority_parts": a["priority_parts"], "seller_days": a["days"],
         "hypothesis_status": a["hypothesis"]["status"], "cowork_why": (a["cowork"] or {}).get("why"),
         "evidence_ids": sorted({i["id"] for i in a["evidence"] if i["stance"] == "supports"}), "plays": [p["key"] for p in a["plays"]]}
        for a in sorted(ov["accounts"], key=lambda a: -a["priority"])], "note": ov["accounts"][0]["note"] if ov["accounts"] else ""}


def t_get_account(ticker=""):
    a = account(ticker)
    if "error" in a:
        return a
    return {k: a[k] for k in ("ticker", "company", "sector", "ref", "momentum_pts", "signal", "perf_3m_pct", "perf_1y_pct", "rank_in_sector", "of_sector",
                              "hypothesis", "evidence", "priority", "priority_parts", "note")} | {"plays": [{"key": p["key"], "name": p["name"], "fit": p["fit"]} for p in a["plays"]]}


def t_get_plays(ticker=""):
    a = account(ticker)
    if "error" in a:
        return a
    return {"ticker": a["ticker"], "company": a["company"], "plays": [
        {"key": p["key"], "name": p["name"], "products": p["products"], "pitch": p["pitch"], "fit": p["fit"], "evidence": p["evidence"]} for p in a["plays"]],
        "note": "Plays come from the partner playbook. The evidence items are the facts that justify each play."}


def t_get_talk_track(ticker="", play=None):
    return talk_track(ticker, play)


def t_show_account(ticker="", view="plays"):
    row = workbook.by_ticker(ticker)
    if not row:
        return {"error": f"Unknown ticker {ticker}."}
    return {"ok": True, "ticker": chat.primary_row(row)["ticker"], "view": view if view in ("evidence", "competitors", "plays") else "plays"}


def t_add_to_plan(ticker="", play=""):
    row = workbook.by_ticker(ticker)
    if not row or play not in PLAYS:
        return {"error": f"Need a known ticker and one of the plays {', '.join(PLAYS)}."}
    return {"ok": True, "ticker": chat.primary_row(row)["ticker"], "play": play, "play_name": PLAYS[play]["name"]}


def t_set_seller_days(days=DEFAULT_DAYS):
    return {"ok": True, "days": max(1, min(MAX_DAYS, int(days)))}


TOOLS = {
    "get_shortlist": t_get_shortlist, "get_account": t_get_account, "get_competitors": competitors, "get_plays": t_get_plays,
    "get_talk_track": t_get_talk_track, "show_account": t_show_account, "add_to_plan": t_add_to_plan, "set_seller_days": t_set_seller_days,
    "recent_changes": chat.t_recent_changes, "get_financials": chat.t_get_financials, "search_reports": chat.t_search_reports,
    "compare_companies": chat.t_compare_companies, "find_company": chat.t_find_company,
}
_T = {"type": "string"}
TOOL_SPECS = [
    chat._spec("get_shortlist", "The accounts from Cowork with priority, seller days, hypothesis status and the evidence behind them. days is the seller capacity.",
               {"tickers": {"type": "array", "items": _T}, "days": {"type": "integer"}}),
    chat._spec("get_account", "One account: the Cowork hypothesis and whether the evidence supports it, every evidence item with its source, and the Microsoft plays that fit.", {"ticker": _T}, ["ticker"]),
    chat._spec("get_competitors", "The account against its sector peers: momentum and performance, rank, report figures, and the themes peers face in the news.", {"ticker": _T}, ["ticker"]),
    chat._spec("get_plays", "Microsoft solution plays for an account, with products, the pitch and the evidence that justifies each.", {"ticker": _T}, ["ticker"]),
    chat._spec("get_talk_track", "Facts for a first meeting: an opener from the evidence, a peer angle, discovery questions, a proof point and who to meet. play is optional.", {"ticker": _T, "play": _T}, ["ticker"]),
    chat._spec("show_account", "Show an account on the dashboard. view is evidence, competitors or plays.", {"ticker": _T, "view": _T}, ["ticker"]),
    chat._spec("add_to_plan", "Add a Microsoft play for an account to the sales plan on screen. play is one of " + ", ".join(PLAYS) + ".", {"ticker": _T, "play": _T}, ["ticker", "play"]),
    chat._spec("set_seller_days", "Change the seller capacity on screen (days available this quarter). The dashboard then reallocates the days.", {"days": {"type": "integer"}}, ["days"]),
    *[s for s in chat.TOOL_SPECS if s["function"]["name"] in ("recent_changes", "get_financials", "search_reports", "compare_companies", "find_company")],
]
TOOL_LABEL = {"get_shortlist": "shortlist and priorities", "get_account": "account evidence", "get_competitors": "competitor view", "get_plays": "Microsoft plays",
              "get_talk_track": "talk track facts", "show_account": "update the dashboard", "add_to_plan": "add to the plan", "set_seller_days": "seller capacity"}


def run_tool(name, args, ctx):
    fn = TOOLS.get(name)
    if not fn:
        return {"error": f"Unknown tool {name}"}
    args = {k: v for k, v in (args or {}).items() if v is not None}
    if name == "get_shortlist":
        args.setdefault("tickers", ctx["tickers"])
        args.setdefault("days", ctx["days"])
    try:
        return fn(**args)
    except (TypeError, ValueError) as exc:
        return {"error": f"Bad arguments: {exc}"}


def summarize(name, res):
    if "error" in res:
        return res["error"]
    if name == "get_shortlist":
        return " · ".join(f"{a['ticker']} {a['seller_days']}d" for a in res["accounts"])
    if name == "get_account":
        return f"{res['company']} · {res['hypothesis']['status']} · {len(res['plays'])} plays"
    if name == "get_competitors":
        return f"{len(res['peers'])} peers in {res['sector']}"
    if name == "get_plays":
        return ", ".join(p["name"] for p in res["plays"]) or "no play"
    if name == "get_talk_track":
        return f"{res['company']} · {res['play_name']}"
    if name == "show_account":
        return f"showing {res['ticker']} · {res['view']}"
    if name == "add_to_plan":
        return f"{res['ticker']} · {res['play_name']} added"
    if name == "set_seller_days":
        return f"{res['days']} seller days"
    return chat.summarize(name, res)


def action_for(name, res):
    if name not in UI_ACTIONS or "error" in res:
        return None
    if name == "show_account":
        return {"action": "show", "ticker": res["ticker"], "view": res["view"]}
    if name == "add_to_plan":
        return {"action": "add_play", "ticker": res["ticker"], "play": res["play"]}
    return {"action": "set_days", "days": res["days"]}


# ----------------------------------------------------------------------------- offline router and answers

PRIORITY_ASK = re.compile(r"\b(priorit\w*|where (should|do) we (start|spend|focus)|first|focus|seller days?|days?|capacity|resources?|limited|allocat\w*|time)\b", re.I)
HYPO_ASK = re.compile(r"\b(hypothes[ie]s|cowork|true|hold up|verify|check|evidence|proof|support\w*)\b", re.I)
COMP_ASK = re.compile(r"\b(competitors?|competition|peers?|rivals?|compare|versus|vs\.?|benchmark|stack up|sector)\b", re.I)
TALK_ASK = re.compile(r"\b(talk track|meeting|agenda|opener|open the conversation|first call|call|email|pitch|say|questions?)\b", re.I)
PLAY_ASK = re.compile(r"\b(plays?|position\w*|microsoft|products?|finops|offer\w*|solutions?|sell|bridge|azure|foundry|fabric|purview|copilot)\b", re.I)
BUILD_ASK = re.compile(r"\b(add|build|create|put|draft)\b.*\b(plan)\b|\bsales plan\b", re.I)
ALL_ASK = re.compile(r"\b(all|each|every|shortlist|three|accounts)\b", re.I)
DAYS_IN = re.compile(r"\b(\d{1,2})\s*(seller\s*)?(days?|person[- ]days|sales days)\b", re.I)


def plan_offline(text, ctx):
    """Returns (intent, [(tool, args)]) for a message. ctx carries the selected account, the shortlist and the capacity."""
    named = [r["ticker"] for r in chat.match_companies(text)]
    target = named[0] if named else ctx["focus"]
    days = DAYS_IN.search(text)
    play = next((k for k, p in PLAYS.items() if k in text.lower() or p["name"].lower() in text.lower()), None)
    if chat.ADVICE_ASK.search(text):
        return "advice", []
    if chat.SALES_ASK.search(text) or re.search(r"\b(want|ready|going) to buy\b", text, re.I):
        return "intent", [("get_account", {"ticker": target})]
    if days or (PRIORITY_ASK.search(text) and not named):
        calls = [("set_seller_days", {"days": int(days.group(1))})] if days else []
        return "priority", calls + [("get_shortlist", {"days": int(days.group(1)) if days else ctx["days"]})]
    if BUILD_ASK.search(text):
        if named or not ALL_ASK.search(text):
            return "build", [("get_plays", {"ticker": target})]
        return "build_all", [("get_plays", {"ticker": t}) for t in ctx["tickers"]]
    if TALK_ASK.search(text):
        return "talk", [("get_talk_track", {"ticker": target, **({"play": play} if play else {})}), ("show_account", {"ticker": target, "view": "plays"})]
    if HYPO_ASK.search(text):
        if not named and ALL_ASK.search(text):
            return "hypo_all", [("get_account", {"ticker": t}) for t in ctx["tickers"]]
        return "hypo", [("get_account", {"ticker": target}), ("show_account", {"ticker": target, "view": "evidence"})]
    if COMP_ASK.search(text):
        if len(named) >= 2:
            return "compare", [("compare_companies", {"tickers": named[:4]})]
        return "competitors", [("get_competitors", {"ticker": target}), ("show_account", {"ticker": target, "view": "competitors"})]
    if PLAY_ASK.search(text) or named:
        return "plays", [("get_plays", {"ticker": target}), ("show_account", {"ticker": target, "view": "plays"})]
    return "help", []


def _cite_item(i):
    return f"{i['text']} [{i['id']}]"


def render_offline(intent, results, ctx):
    res = {name: r for name, _a, r in results}
    first_err = next((r["error"] for _n, _a, r in results if "error" in r), None)
    if intent == "advice":
        return ("I can't give investment advice or forecasts. I can show which accounts deserve your seller time, why, and which Microsoft play fits each one.")
    if intent == "intent":
        a = res.get("get_account", {})
        n = len({i["id"] for i in a.get("evidence", []) if i["stance"] == "supports"})
        return (f"No data here can tell whether {a.get('company', 'an account')} will buy. Share prices and headlines show buying triggers, not purchase intent. "
                f"I see {chat._n(n, 'trigger', 'triggers')} for {a.get('company', 'it')}; confirm budget and timing in the first meeting.")
    if intent == "help":
        return ("I plan the sales motion for the Cowork shortlist. Try:\n- Where should our seller days go?\n- Does the Cowork hypothesis for UBS hold up?\n"
                "- How does UBS compare with its competitors?\n- Which Microsoft play fits UBS?\n- Draft the first meeting with UBS")
    if first_err and intent not in ("build_all", "hypo_all"):
        return first_err
    if intent == "priority":
        s = res["get_shortlist"]
        lines = [f"With {s['days']} seller days, I'd spread them by evidence, not by share price:"]
        for a in s["accounts"]:
            ids = ", ".join(f"[{i}]" for i in a["evidence_ids"][:3])
            lines.append(f"- **{a['company']}** ({a['ticker']}): {chat._n(a['seller_days'], 'day', 'days')}, priority {a['priority']:g} of 10. "
                         f"Hypothesis: {a['hypothesis_status'].lower()}{f' {ids}' if ids else ''}.")
        lines.append("Share-price moves are left out on purpose: they say nothing about demand for Microsoft products.")
        return "\n".join(lines)
    if intent in ("hypo", "hypo_all"):
        accs = [r for n, _a, r in results if n == "get_account" and "error" not in r]
        out = []
        for a in accs:
            h = a["hypothesis"]
            if not h["hypothesis"]:
                out.append(f"- **{a['company']}** ({a['ticker']}) has no Cowork hypothesis.")
                continue
            ev = "; ".join(_cite_item(i) for i in h["supports"][:2])
            con = "; ".join(_cite_item(i) for i in h["counters"][:1])
            line = f"**{a['company']}** ({a['ticker']}), Cowork: “{h['hypothesis']}” Verdict: {h['status'].lower()}."
            if ev:
                line += f" For it: {ev}."
            if con:
                line += f" Against it: {con}."
            if h["status"] == "Not in our sources":
                line += " Nothing in the feed or the reports speaks to it, so make it the first discovery question."
            out.append(("- " if len(accs) > 1 else "") + line)
        return "\n".join(out) or first_err
    if intent == "competitors":
        c = res["get_competitors"]
        co = c["company"]
        lines = []
        if c["rank_in_sector"]:
            lead = c["peers"][0] if c["peers"] and c["peers"][0]["momentum_pts"] > (co["momentum_pts"] or 0) else None
            lines.append(f"{co['company']} ranks {c['rank_in_sector']} of {c['of_sector']} in {c['sector']} on momentum ({chat._pts(co['momentum_pts'])}) [{co['ref']}]"
                         + (f"; {lead['company']} leads with {chat._pts(lead['momentum_pts'])} [{lead['ref']}]." if lead else ", ahead of every peer."))
        if c["sector_avg_1y_pct"] is not None and co["perf_1y_pct"] is not None:
            lines.append(f"- 1-year: {chat._p(co['perf_1y_pct'])} against a sector average of {chat._p(c['sector_avg_1y_pct'])}.")
        for s in c["shared_themes"][:2]:
            n = next((x for x in c["peer_news"] if s["theme"] in x["themes"]), None)
            if n:
                lines.append(f"- {s['label']} is a sector theme: {chat._n(len(s['peers']), 'peer', 'peers')} in the news, e.g. “{n['headline']}” ({n['source']}, {n['date']}) [{n['id']}].")
        if c["financials"]:
            m = c["financials"]["margins"].get("operating_margin_pct")
            if m:
                lines.append(f"- Reported operating margin: {m['h1_2026']}% in H1 2026 against {m['h1_2025']}% a year earlier [{c['financials']['items'][0]['ref']}].")
        lines.append("Peers are sector peers in the workbook; it has no market share data.")
        return "\n".join(lines)
    if intent == "compare":
        return chat.render_offline("compare", [(n, a, r) for n, a, r in results], "")
    if intent == "plays":
        p = res["get_plays"]
        if not p["plays"]:
            return f"No Microsoft play has evidence for {p['company']} yet. Start with discovery."
        lines = [f"For {p['company']} ({p['ticker']}):"]
        used = set()
        for pl in p["plays"][:2]:
            item = next((i for i in pl["evidence"] if i["id"] not in used), pl["evidence"][0] if pl["evidence"] else None)
            used.add(item and item["id"])
            why = _cite_item(item) if item else "the Cowork hypothesis only, so test it first"
            lines.append(f"- **{pl['name']}** ({', '.join(pl['products'][:3])}). Why: {why}.")
        lines.append("Press + on a play, or ask me to add it to the plan.")
        return "\n".join(lines)
    if intent == "talk":
        t = res["get_talk_track"]
        lines = [f"First meeting with {t['company']}: {t['play_name']}, with the {t['meeting']}."]
        if t["opener"]:
            lines.append(f"- Open with: {_cite_item(t['opener'])}.")
        if t["peer_angle"]:
            pa = t["peer_angle"]
            lines.append(f"- Peer angle: {pa['company']} faces the same theme: “{pa['headline']}” ({pa['source']}, {pa['date']}) [{pa['id']}].")
        lines.append(f"- Ask: {t['questions'][0]}")
        lines.append(f"- Ask: {t['questions'][1]}")
        lines.append(f"- Show: {t['proof']['label']}.")
        return "\n".join(lines)
    if intent in ("build", "build_all"):
        added = [r for n, _a, r in results if n == "add_to_plan" and "error" not in r]
        if not added:
            return "No play with evidence to add yet."
        why = {r["ticker"]: next((p["evidence"][0]["id"] for p in r["plays"] if p["evidence"]), None) for n, _a, r in results if n == "get_plays" and "error" not in r}
        return "Added to the plan:\n" + "\n".join(f"- **{a['play_name']}** for {_short(workbook.by_ticker(a['ticker'])['company'])} ({a['ticker']})"
                                                  + (f", because of [{why[a['ticker']]}]" if why.get(a["ticker"]) else ", resting on the Cowork hypothesis") for a in added) \
            + "\nSet an owner and a week for each row, then download the plan."
    return "I couldn't work that out. Ask about priorities, a hypothesis, competitors or a Microsoft play."


def system_prompt(ctx):
    ds = workbook.current()
    names = ", ".join(ctx["tickers"])
    return f"""You are the Sales Plan Assistant for a Microsoft partner. Cowork shortlisted these accounts with hypotheses: {names}. The user is on a dashboard that shows them; {ctx['focus']} is selected and {ctx['days']} seller days are available this quarter.
Your job: help decide where limited seller time goes, test the Cowork hypotheses against evidence, compare each account with its competitors (sector peers in the workbook "{ds.name}", snapshot {ds.snapshot_str}) and position Microsoft products with a play.

How to work:
- Get facts with tools, never from memory. Priorities and seller days come from get_shortlist; never compute them yourself.
- You can change the dashboard: show_account, add_to_plan and set_seller_days. Use them when the user asks to see, add, plan or change capacity, then say what you changed.
- Plays (FinOps, compliance, scale, carve-out) are the partner's playbook. Justify a play only with evidence items from tools, and say when a play rests on the Cowork hypothesis alone.
- Cite every company fact with the ids from tool results, like [SEC-012], [SIG-046] or [REP-VACN-p2]. Quote headlines word for word with publisher and date.
- Share-price moves are not evidence of demand or of a wish to buy Microsoft products. Never claim an account is ready to buy.
- Never give investment advice, price targets or forecasts.
- Answer in at most 120 words, with short "-" bullet lines when useful. No tables, no headings."""


async def plan_events(message, history=None, mode="offline", focus=None, tickers=None, days=DEFAULT_DAYS):
    live = mode == "live" and llm.live_available()
    reports.use_semantic(live)
    rows = resolve(tickers)
    ctx = {"tickers": [r["ticker"] for r in rows], "days": max(1, min(MAX_DAYS, int(days or DEFAULT_DAYS)))}
    f = workbook.by_ticker(focus or "")
    ctx["focus"] = chat.primary_row(f)["ticker"] if f else (ctx["tickers"][0] if ctx["tickers"] else "")
    message = (message or "").strip()[:1000]
    t0 = time.perf_counter()
    tin = tout = 0
    cost = 0.0
    evidence_text, steps, actions = [], [], []
    yield {"type": "start", "mode": "live" if live else "offline", "model": MODELS["assistant"] if live else "rule-based router"}
    if not message:
        yield {"type": "error", "message": "Please type a question."}
        return

    def record(name, args, res):
        evidence_text.append(json.dumps(res, default=str))
        steps.append({"tool": name, "args": args, "summary": summarize(name, res)})
        act = action_for(name, res)
        if act:
            actions.append(act)
        return act

    answer = None
    if live:
        messages = [{"role": "system", "content": system_prompt(ctx)}, *chat._clean_history(history), {"role": "user", "content": message}]
        try:
            for _ in range(chat.MAX_TOOL_ROUNDS):
                yield {"type": "thinking", "model": MODELS["assistant"]}
                r = await llm.chat(MODELS["assistant"], messages, tools=TOOL_SPECS, max_tokens=3000)
                tin, tout, cost = tin + r["tokens_in"], tout + r["tokens_out"], cost + r["cost"]
                if not r["tool_calls"]:
                    answer = r["content"].strip()
                    break
                messages.append({"role": "assistant", "content": r["content"] or None, "tool_calls": [
                    {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}} for tc in r["tool_calls"]]})
                for tc in r["tool_calls"]:
                    try:
                        args = json.loads(tc["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    yield {"type": "tool_call", "tool": tc["name"], "args": args}
                    res = await asyncio.to_thread(run_tool, tc["name"], args, ctx)
                    act = record(tc["name"], args, res)
                    yield {"type": "tool_result", "tool": tc["name"], "summary": summarize(tc["name"], res)}
                    if act:
                        yield {"type": "action", **act}
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res, default=str)})
        except Exception as exc:  # noqa: BLE001
            yield {"type": "warning", "message": f"Live call failed ({type(exc).__name__}). Answering offline."}
            live, answer = False, None
            evidence_text.clear(); steps.clear(); actions.clear()
    if answer is None:
        intent, calls = plan_offline(message, ctx)
        ctx["focus"] = next((a["ticker"] for _n, a in calls if a.get("ticker")), ctx["focus"])
        yield {"type": "thinking", "model": "rule-based router"}
        await asyncio.sleep(0.5)
        results = []
        for name, args in calls:
            yield {"type": "tool_call", "tool": name, "args": args}
            await asyncio.sleep(0.6)
            res = await asyncio.to_thread(run_tool, name, args, ctx)
            act = record(name, args, res)
            results.append((name, args, res))
            yield {"type": "tool_result", "tool": name, "summary": summarize(name, res)}
            if act:
                yield {"type": "action", **act}
            if name == "get_plays" and intent in ("build", "build_all") and "error" not in res and res["plays"]:
                top = res["plays"][0]
                add_args = {"ticker": res["ticker"], "play": top["key"]}
                yield {"type": "tool_call", "tool": "add_to_plan", "args": add_args}
                await asyncio.sleep(0.4)
                added = run_tool("add_to_plan", add_args, ctx)
                act = record("add_to_plan", add_args, added)
                results.append(("add_to_plan", add_args, added))
                yield {"type": "tool_result", "tool": "add_to_plan", "summary": summarize("add_to_plan", added)}
                if act:
                    yield {"type": "action", **act}
        answer = render_offline(intent, results, ctx)
    ctx["focus"] = next((a["ticker"] for a in reversed(actions) if a["action"] == "show"), ctx["focus"])
    check = chat.verify(answer, "\n".join(evidence_text))
    blocked = check["advice"]
    if blocked:
        answer = chat.POLICY_BLOCK
        check = chat.verify(answer, "")
    yield {"type": "answer", "text": answer, "sources": chat.sources_for(answer), "checks": check, "blocked": blocked, "steps": steps, "actions": actions,
           "followups": followups(ctx, steps), "live": live, "tokens_in": tin, "tokens_out": tout, "cost": round(cost, 5), "elapsed": round(time.perf_counter() - t0, 1)}
    yield {"type": "done"}


def followups(ctx, steps):
    used = {s["tool"] for s in steps}
    co = workbook.by_ticker(ctx["focus"])
    name = _short(co["company"]) if co else "this account"
    out = []
    if "get_account" not in used:
        out.append(f"Does the Cowork hypothesis for {name} hold up?")
    if "get_competitors" not in used:
        out.append(f"How does {name} compare with its competitors?")
    if "get_talk_track" not in used:
        out.append(f"Draft the first meeting with {name}")
    if "add_to_plan" not in used:
        out.append("Build the sales plan for all three accounts")
    return out[:3]


def suggestions(ctx_tickers=None):
    rows = resolve(ctx_tickers)
    first = _short(rows[0]["company"]) if rows else "UBS"
    return [
        {"label": "Only 12 seller days", "prompt": "We only have 12 seller days this quarter. Where should they go?", "kind": "rank"},
        {"label": "Check Cowork's hypothesis", "prompt": f"Does the Cowork hypothesis for {first} hold up?", "kind": "brief"},
        {"label": "Competitors", "prompt": f"How does {first} compare with its competitors?", "kind": "peer"},
        {"label": "Microsoft play", "prompt": f"Which Microsoft play fits {first}?", "kind": "compare"},
        {"label": "First meeting", "prompt": f"Draft the first meeting with {first}", "kind": "change"},
        {"label": "Build the plan", "prompt": "Build the sales plan for all three accounts", "kind": "sector"},
    ]
