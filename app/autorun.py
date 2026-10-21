"""Account run: one repeatable process that answers the business question for every account in the workbook.

"For every account on our list: what is happening in their industry, which of our past cases fit, and what should we offer?"
Four agents answer it account by account: the Industry Scout reads the real news feed by sector, the Case Matcher picks
reference cases from data/past_cases.json (synthetic demo data), the Offer Writer picks the Microsoft play from the Sales plan
playbook and the Compliance Reviewer decides what the process may do on its own. Only exceptions reach a person.

A run starts by hand or from the schedule (autopilot). Each run happens in its own thread, so it finishes and stays in the
history even when nobody has the page open.
"""
import asyncio
import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta

from . import agents, chat, llm, salesplan, signals, workbook
from .config import MODELS, ROOT

CASES_PATH = ROOT / "data" / "past_cases.json"
LANES = 6  # accounts worked on at the same time
STAGE_PACE = 0.22  # seconds per stage and account, so the grid can be followed on screen
HISTORY = 12

AGENTS = [
    {"key": "scout", "name": "Industry Scout", "role": "What is happening in the account's industry", "model": MODELS["scout"]},
    {"key": "matcher", "name": "Case Matcher", "role": "Which of our past cases fit", "model": MODELS["analyst"]},
    {"key": "writer", "name": "Offer Writer", "role": "What we should offer, with the evidence", "model": MODELS["analyst"]},
    {"key": "reviewer", "name": "Compliance Reviewer", "role": "Decides what can go out without a person", "model": MODELS["reviewer"]},
]
STAGES = [a["key"] for a in AGENTS]

ROUTES = {
    "ready": {"label": "Sent to account team", "detail": "Own evidence and a fitting case: the offer goes to the account owner."},
    "campaign": {"label": "Added to industry campaign", "detail": "Only an industry signal or no fitting case: the account joins the campaign for its industry."},
    "review": {"label": "Needs you", "detail": "The reviewer found a reason a person must decide first."},
    "parked": {"label": "No trigger yet", "detail": "Nothing in the news calls for an offer. The next run checks again."},
}
# Headlines a person must read before anyone contacts the account.
SENSITIVE = re.compile(r"\b(lawsuits?|court|fined?|fines|probe|investigations?|antitrust|sanctions?)\b", re.I)

CADENCES = {
    "demo": {"label": "Every 2 minutes (demo)", "short": "every 2 min"},
    "daily": {"label": "Every day at 07:00", "short": "daily 07:00"},
    "weekly": {"label": "Every Monday at 07:00", "short": "Mondays 07:00"},
}


# ----------------------------------------------------------------------------- the three answers per account

def case_file():
    try:
        return json.loads(CASES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"cases": []}


def cases():
    return case_file().get("cases", [])


def accounts():
    """One row per company (the primary share class), in workbook order."""
    out, seen = [], set()
    for r in workbook.rows():
        p = chat.primary_row(r)
        if p["company"] not in seen:
            seen.add(p["company"])
            out.append(p)
    return out


def industry(sector, rows=None):
    """Buying themes in the sector's news: which themes, how many headlines, which companies, and the headlines themselves."""
    rows = [r for r in (rows or accounts()) if r["sector"] == sector]
    themes, headlines = {}, []
    for r in rows:
        for e in signals.events_for(r["ticker"]):
            if e["kind"] != "news":
                continue
            ths = salesplan.themes_of(e["headline"], e["type"])
            if not ths:
                continue
            headlines.append({"id": e["id"], "ticker": r["ticker"], "company": r["company"], "headline": e["headline"], "source": e["source"],
                              "date": e["date"], "url": e.get("url"), "themes": ths})
            for th in ths:
                t = themes.setdefault(th, {"theme": th, "label": salesplan.THEMES[th]["label"], "count": 0, "companies": []})
                t["count"] += 1
                if r["ticker"] not in t["companies"]:
                    t["companies"].append(r["ticker"])
    ranked = sorted(themes.values(), key=lambda t: (-t["count"], -len(t["companies"]), t["theme"]))
    headlines.sort(key=lambda h: h["date"], reverse=True)
    top = ranked[0] if ranked else None
    if top:
        names = ", ".join(salesplan._short(c) for c in dict.fromkeys(h["company"] for h in headlines if top["theme"] in h["themes"]))
        summary = f"{len(headlines)} headline{'s' if len(headlines) != 1 else ''} with a buying theme. Strongest: {top['label'].lower()} ({names})."
    else:
        summary = "No headline with a buying theme since the workbook date."
    return {"sector": sector, "companies": len(rows), "themes": ranked, "top_theme": top and top["theme"], "headlines": headlines[:4], "summary": summary}


def match_cases(sector, theme, play):
    """Past cases for the same need (theme), the same industry first. A case for another need never fits."""
    scored = []
    for c in cases():
        if c.get("theme") != theme:
            continue
        same = c.get("sector") == sector
        score = (2 if same else 0) + (1 if c.get("play") == play else 0)
        scored.append((score, c.get("year", 0), {**c, "fit": "Same industry and need" if same else "Same need, other industry"}))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [c for _, _, c in scored[:2]]


def assess(row, ind):
    """The answer for one account: industry, cases, offer, the reviewer's checks and where the result goes."""
    ticker = row["ticker"]
    items = salesplan.evidence(ticker)
    plays = salesplan.plays_for(ticker, items)
    cowork = salesplan.cowork_entry(ticker)
    own = next((p for p in plays if p["evidence"]), None)
    play_key, basis, why = None, None, None
    if own:
        play_key, basis = own["key"], "account"
        e = own["evidence"][0]
        why = {"id": e["id"], "text": e["text"]}
    elif ind["top_theme"]:
        play_key, basis = salesplan.THEME_PLAY[ind["top_theme"]], "industry"
        h = next((h for h in ind["headlines"] if ind["top_theme"] in h["themes"]), None)
        why = h and {"id": h["id"], "text": f"In {row['sector']}: “{h['headline']}” ({h['source']}, {h['date']})"}
    elif plays:
        play_key, basis = plays[0]["key"], "cowork"
        why = {"id": None, "text": f"Cowork hypothesis: {cowork['hypothesis']}"} if cowork else None

    play = salesplan.PLAYS.get(play_key)
    theme = play and play["theme"]
    matched = match_cases(row["sector"], theme, play_key) if play else []
    counters = [i for i in items if i["stance"] == "counters" and i["theme"] == theme]
    sensitive = [e for e in signals.events_for(ticker) if e["kind"] == "news" and SENSITIVE.search(e["headline"])]
    offer_text = f"{play['name']}: {play['pitch']}" if play else ""
    advice = [p for p in agents.ADVICE_PATTERNS if re.search(p, offer_text, re.I)]
    checks = [
        {"key": "data", "label": "Workbook data complete", "passed": bool(row["complete"]),
         "detail": "Prices and returns are in the workbook." if row["complete"] else "The workbook has no market data for this company."},
        {"key": "source", "label": "Offer backed by a cited source", "passed": bool(why and why.get("id")),
         "detail": f"Source {why['id']}." if why and why.get("id") else "No headline or report figure supports an offer."},
        {"key": "case", "label": "A past case fits", "passed": bool(matched), "detail": matched[0]["id"] + " · " + matched[0]["fit"] if matched else "No reference case for this need."},
        {"key": "conflict", "label": "No conflicting evidence", "passed": not counters,
         "detail": counters[0]["text"] if counters else "Nothing in the sources speaks against the offer."},
        {"key": "sensitive", "label": "No sensitive news", "passed": not sensitive,
         "detail": f"“{sensitive[0]['headline']}” ({sensitive[0]['source']}): read it before anyone calls." if sensitive else "No lawsuit, fine or probe in the headlines."},
        {"key": "advice", "label": "No investment advice", "passed": not advice, "detail": "The offer talks about Microsoft solutions, not about the share."},
    ]
    reasons = []
    if not play:
        route = "parked"
    else:
        if not row["complete"]:
            reasons.append("Workbook data is missing for this company")
        if counters:
            reasons.append("Evidence points both ways")
        if sensitive:
            reasons.append("Sensitive headline: a person reads it before outreach")
        if advice:
            reasons.append("Wording sounds like investment advice")
        if cowork:
            reasons.append("Strategic account from the Cowork shortlist: the account owner signs off")
        route = "review" if reasons else "ready" if basis == "account" and matched else "campaign"
    confidence = "high" if basis == "account" and matched else "medium" if play else "low"
    ids = [row["id"], *([why["id"]] if why and why.get("id") else [])]
    return {
        "ticker": ticker, "company": row["company"], "short": salesplan._short(row["company"]), "sector": row["sector"], "ref": row["id"],
        "industry": {"summary": ind["summary"], "top_theme": ind["top_theme"], "label": salesplan.THEMES[ind["top_theme"]]["label"] if ind["top_theme"] else None},
        "own_themes": sorted({i["theme"] for i in items if i["stance"] == "supports"}),
        "basis": basis, "why": why, "cases": matched, "confidence": confidence,
        "offer": play and {"key": play_key, "name": play["name"], "products": play["products"], "pitch": play["pitch"], "meeting": play["meeting"],
                           "theme": theme, "theme_label": salesplan.THEMES[theme]["label"], "proof": play["proof"]},
        "checks": checks, "route": route, "route_label": ROUTES[route]["label"], "reasons": reasons, "cowork": bool(cowork),
        "sources": chat.sources_for(" ".join(ids)),
    }


# ----------------------------------------------------------------------------- one run as a stream of events

async def _sector_summaries(ctx, inds):
    """Live mode: the scout model writes one sentence per sector from the headlines. Falls back to the template sentence."""
    async def one(ind):
        if not ind["headlines"]:
            return ind, None, None
        try:
            r = await llm.chat(MODELS["scout"], [
                {"role": "system", "content": "You summarise what is happening in an industry for a Microsoft sales team. One sentence, max 28 words, "
                                              "only from the headlines given, no investment advice, no markdown."},
                {"role": "user", "content": json.dumps({"sector": ind["sector"], "headlines": [h["headline"] for h in ind["headlines"]]})}], max_tokens=800)
        except Exception as exc:  # noqa: BLE001
            return ind, None, exc
        return ind, r, None
    return await asyncio.gather(*(one(i) for i in inds))


async def run_events(mode="offline", trigger="manual", run_id=None):
    live = mode == "live" and llm.live_available()
    ctx = agents.Ctx(live)
    rows = accounts()
    sectors = list(dict.fromkeys(r["sector"] for r in rows))
    yield ctx.ev("run_start", run_id=run_id, trigger=trigger, mode="live" if live else "offline",
                 note="Live mode was requested but Foundry is not reachable; running offline." if mode == "live" and not live else None,
                 agents=[{k: a[k] for k in ("key", "name", "role", "model")} for a in AGENTS], routes=ROUTES,
                 accounts=[{"ticker": r["ticker"], "company": r["company"], "short": salesplan._short(r["company"]), "sector": r["sector"]} for r in rows],
                 question="For every account on our list: what is happening in their industry, which of our past cases fit, and what should we offer?",
                 cases=len(cases()))

    yield ctx.ev("agent_start", agent="scout", task=f"Read the news for {len(sectors)} industries")
    inds = {s: industry(s, rows) for s in sectors}
    if live:
        for ind, r, exc in await _sector_summaries(ctx, list(inds.values())):
            if exc:
                yield ctx.ev("warning", agent="scout", message=f"Live call failed for {ind['sector']} ({type(exc).__name__}); template sentence used.")
            elif r:
                ctx.add(r)
                ind["summary"] = (r["content"] or "").strip() or ind["summary"]
                yield ctx.ev("llm_result", agent="scout", model=r["model"], purpose=f"Summarise {ind['sector']}", tokens_in=r["tokens_in"], tokens_out=r["tokens_out"],
                             latency=r["latency"], cost=round(r["cost"], 5), totals=ctx.totals())
    for s in sectors:
        await agents.pace(0.12)
        yield ctx.ev("industry", agent="scout", **{k: v for k, v in inds[s].items()})

    queue, sem = asyncio.Queue(), asyncio.Semaphore(LANES)

    async def work(row):
        async with sem:
            for stage in STAGES:
                await queue.put(ctx.ev("acc_stage", ticker=row["ticker"], stage=stage))
                await agents.pace(STAGE_PACE)
            await queue.put(ctx.ev("acc_done", result=assess(row, inds[row["sector"]])))

    tasks = [asyncio.create_task(work(r)) for r in rows]
    done_n, results = 0, []
    while done_n < len(rows):
        e = await queue.get()
        if e["type"] == "acc_done":
            done_n += 1
            results.append(e["result"])
        yield e
    await asyncio.gather(*tasks)

    counts = {k: sum(1 for r in results if r["route"] == k) for k in ROUTES}
    for a in AGENTS:
        yield ctx.ev("agent_done", agent=a["key"], summary={
            "scout": f"{len(sectors)} industries, {sum(len(i['headlines']) for i in inds.values())} headlines read",
            "matcher": f"{sum(1 for r in results if r['cases'])} accounts matched to a past case",
            "writer": f"{sum(1 for r in results if r['offer'])} offers written",
            "reviewer": f"{counts['review']} need a person, {counts['ready'] + counts['campaign']} went out on their own"}[a["key"]])
    yield ctx.ev("run_done", counts=counts, processed=len(results), elapsed=round(time.perf_counter() - ctx.t0, 1), totals=ctx.totals(),
                 mode="live" if live else "offline", cost_per_account=round(ctx.cost / len(results), 5) if live and results else None)


# ----------------------------------------------------------------------------- runs in the background

class Run:
    def __init__(self, mode, trigger, by):
        self.id = "RUN-" + uuid.uuid4().hex[:6].upper()
        self.mode, self.trigger, self.by = mode, trigger, by
        self.started = datetime.now()
        self.finished = None
        self.events = []
        self.done = False
        self.final = None

    def summary(self):
        return {"id": self.id, "mode": self.final["mode"] if self.final else self.mode, "trigger": self.trigger, "by": self.by,
                "started": self.started.isoformat(timespec="seconds"), "finished": self.finished and self.finished.isoformat(timespec="seconds"),
                "done": self.done, "processed": sum(1 for e in self.events if e["type"] == "acc_done"),
                "counts": self.final and self.final["counts"], "elapsed": self.final and self.final["elapsed"]}


_lock = threading.Lock()
RUNS = []  # newest first
SCHEDULE = {"enabled": False, "cadence": "demo", "mode": "offline", "next_run": None, "since": None}
_scheduler = {"thread": None}


def active():
    with _lock:
        return next((r for r in RUNS if not r.done), None)


def get(run_id):
    with _lock:
        return next((r for r in RUNS if r.id == run_id), None)


def _drive(run, ds):
    async def go():
        workbook.pin(ds)  # the run keeps the workbook it started with
        try:
            async for e in run_events(run.mode, run.trigger, run.id):
                run.events.append(e)
                if e["type"] == "run_done":
                    run.final = e
        except Exception as exc:  # noqa: BLE001
            run.events.append({"type": "error", "message": str(exc)[:300]})
    try:
        asyncio.run(go())
    finally:
        run.finished = datetime.now()
        run.done = True


def start(mode="offline", trigger="manual", by="You"):
    """Starts a run in its own thread. A run that is still going is returned instead of starting a second one."""
    with _lock:
        cur = next((r for r in RUNS if not r.done), None)
        if cur:
            return cur, False
        run = Run(mode, trigger, by)
        RUNS.insert(0, run)
        del RUNS[HISTORY:]
    threading.Thread(target=_drive, args=(run, workbook.current()), daemon=True, name=f"account-run-{run.id}").start()
    return run, True


async def follow(run_id):
    """Every event of a run: the ones already produced at once, then the new ones as they come."""
    run = get(run_id)
    if not run:
        yield {"type": "error", "message": f"Unknown run {run_id}."}
        return
    i = 0
    while True:
        while i < len(run.events):
            yield run.events[i]
            i += 1
        if run.done and i >= len(run.events):
            return
        await asyncio.sleep(0.08)


# ----------------------------------------------------------------------------- the schedule (autopilot)

def next_after(cadence, now=None):
    now = now or datetime.now()
    if cadence == "demo":
        return now + timedelta(minutes=2)
    at = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if cadence == "daily":
        return at if at > now else at + timedelta(days=1)
    days = (0 - now.weekday()) % 7  # Monday
    at += timedelta(days=days)
    return at if at > now else at + timedelta(days=7)


def _tick(now=None):
    """One check of the schedule: starts a run when one is due. Returns the run it started, if any."""
    now = now or datetime.now()
    if not SCHEDULE["enabled"] or not SCHEDULE["next_run"] or now < SCHEDULE["next_run"]:
        return None
    SCHEDULE["next_run"] = next_after(SCHEDULE["cadence"], now)
    run, started = start(SCHEDULE["mode"], "schedule", "Autopilot")
    return run if started else None


def _loop():
    while True:
        try:
            _tick()
        except Exception:  # noqa: BLE001  the schedule must keep running
            pass
        time.sleep(1)


def set_schedule(enabled, cadence="demo", mode="offline"):
    cadence = cadence if cadence in CADENCES else "demo"
    SCHEDULE.update(enabled=bool(enabled), cadence=cadence, mode="live" if mode == "live" else "offline")
    SCHEDULE["next_run"] = next_after(cadence) if enabled else None
    SCHEDULE["since"] = datetime.now() if enabled else None
    if enabled and not _scheduler["thread"]:
        _scheduler["thread"] = threading.Thread(target=_loop, daemon=True, name="account-run-schedule")
        _scheduler["thread"].start()
    return schedule_info()


def schedule_info():
    nxt = SCHEDULE["next_run"]
    return {"enabled": SCHEDULE["enabled"], "cadence": SCHEDULE["cadence"], "cadence_label": CADENCES[SCHEDULE["cadence"]]["label"],
            "short": CADENCES[SCHEDULE["cadence"]]["short"], "mode": SCHEDULE["mode"],
            "next_run": nxt and nxt.isoformat(timespec="seconds"), "seconds_to_next": max(0, round((nxt - datetime.now()).total_seconds())) if nxt else None,
            "since": SCHEDULE["since"] and SCHEDULE["since"].isoformat(timespec="seconds")}


def status():
    cur = active()
    with _lock:
        history = [r.summary() for r in RUNS]
    return {"schedule": schedule_info(), "cadences": {k: v["label"] for k, v in CADENCES.items()}, "active": cur and cur.summary(), "runs": history,
            "agents": AGENTS, "routes": ROUTES, "accounts": len(accounts()), "cases": len(cases()), "case_source": case_file().get("source", "")}
