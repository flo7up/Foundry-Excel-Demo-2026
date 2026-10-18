"""Monitoring events built from the real public feed (see app.feed): share-price moves and news headlines."""
import re

from . import feed as public_feed
from . import workbook

SEVERITY_WEIGHT = {"low": 1, "medium": 2, "high": 3}
MATERIAL_PRICE_MOVE = 10.0  # percent versus the workbook price; the feed covers about seven weeks
PRICE_EVENT_MIN = 3.0  # smaller moves are not reported as events
NEWS_PER_COMPANY = 2

# First matching rule wins. Headlines that match no rule are not monitoring events.
_ROLE = r"(?:ceo|cfo|chief (?:executive|financial|operating)|chair\w*|president|board|executive (?:board|committee)|leadership team|management (?:board|team))"
_CHANGE = r"(?:appoint\w*|names?|nominat\w*|elect\w*|proposed as|steps? down|resign\w*|to succeed|successor|retire\w*)"
NEWS_RULES = [
    ("analyst_note", "medium", r"\b(?:downgrad\w+|upgrad\w+|price target|(?:raises|cuts|lowers|lifts|starts|initiates|reiterates|maintains)\b.*\b(?:target|rating|coverage)|target (?:for|to)|rating|coverage|analysts?|moody\w*|morningstar|fitch)\b"),
    ("guidance_change", "high", r"\b(?:guidance|profit warning|(?:fy ?\d{2,4}|full[- ]year|annual|2026|2027|its|company)\s+outlook|outlook (?:reiterated|affirmed|confirmed|reaffirmed|raised|lowered|upgraded|cut)|(?:confirms|affirms|raises|lowers|cuts|reiterates|updates)\s+(?:\w+\s+){0,3}outlook|(?:raises?|cuts?|lowers?) (?:its )?(?:full[- ]year|annual)|mid-term targets?)\b"),
    ("management_change", "high", rf"^(?=.*\b{_CHANGE}\b)(?=.*\b{_ROLE}\b)"),
    ("restructuring", "high", r"\b(?:job cuts?|cuts? (?:up to )?\d* ?jobs|layoffs?|restructur\w+|redundanc\w+|divest\w*|spin-?off|wind-down|plant clos\w+)\b"),
    ("deal", "medium", r"\b(?:acqui\w+|takeover|merger|bidders?|buyout|joint venture|stake in|partnership|collaborat\w+ (?:with|agreement)|licen[cs]\w+|agreement|to pay|to sell)\b"),
    ("regulatory", "medium", r"\b(?:lawsuit|(?:supreme|federal|appeals?|district) court|court (?:rules?|ruled|throws|dismiss\w*|orders?|rejects?|upholds?)|ruling|fines?|fined|probe|investigation|regulators?|fda|approv\w+|tariffs?|antitrust|sanctions?|capital (?:rules|requirements|demands))\b"),
    ("trading_update", "medium", r"\b(?:results|earnings|quarter|q[1-4]|half-year|net sales|revenues?|profits?|order intake|sales (?:grow|growth|rose|fell|up|down))\b"),
    ("product_update", "low", r"\b(?:launch\w*|introduc\w+|unveil\w*|expands?|opens?|new (?:plant|site|facility)|invests?)\b"),
]
_RULES = [(t, s, re.compile(p, re.I | re.S)) for t, s, p in NEWS_RULES]


def classify(headline):
    for type_, severity, pattern in _RULES:
        if pattern.search(headline):
            return type_, severity
    return None


def _price_event(ticker, row, quote):
    base, (day, close) = row["price"], quote["series"][-1]
    if not base or not close:
        return None
    pct = (close / base - 1) * 100
    if abs(pct) < PRICE_EVENT_MIN:
        return None
    severity = "high" if abs(pct) >= MATERIAL_PRICE_MOVE else "medium" if abs(pct) >= 5 else "low"
    where = "above" if pct > 0 else "below"
    return {
        "ticker": ticker, "date": day, "type": "price_move", "severity": severity, "kind": "quote",
        "headline": f"Share price {abs(pct):.1f}% {where} the workbook level",
        "detail": f"Close of CHF {close:.2f} on {day} versus CHF {base:.2f} in the workbook (snapshot {workbook.current().snapshot_str}).",
        "price": round(close, 2), "source": "Yahoo Finance", "url": quote["url"],
    }


def build(ds):
    """Events since the workbook snapshot for every security that has data in the public feed cache."""
    cache = public_feed.load()["tickers"]
    since = ds.snapshot.isoformat()
    events = []
    for row in ds.rows:
        entry = cache.get(row["ticker"].upper())
        if not entry:
            continue
        if entry.get("quote") and entry["quote"]["series"]:
            e = _price_event(row["ticker"], row, entry["quote"])
            if e:
                events.append(e)
        news = []
        for n in entry.get("news", []):
            cls = None if public_feed.is_noise(n["title"], n["source"]) else classify(n["title"])
            if cls and n["date"] > since:
                news.append((SEVERITY_WEIGHT[cls[1]], n["date"], cls, n))
        for _, _, (type_, severity), n in sorted(news, key=lambda x: (x[0], x[1]), reverse=True)[:NEWS_PER_COMPANY]:
            events.append({"ticker": row["ticker"], "date": n["date"], "type": type_, "severity": severity, "kind": "news",
                           "headline": n["title"], "detail": f"{n['source']}, {n['date']}", "source": n["source"], "url": n["url"]})
    events.sort(key=lambda e: (e["date"], e["ticker"], e["type"]))
    for n, e in enumerate(events, start=1):
        e["id"] = f"SIG-{n:03d}"
    return events


def feed():
    ds = workbook.current()
    stamp = public_feed.load().get("retrieved_at")
    if ds.feed is None or ds.feed[0] != stamp:
        ds.feed = (stamp, build(ds))
    return ds.feed[1]


def coverage():
    """How many securities of the active workbook the public feed covers, and from when."""
    ds = workbook.current()
    cache = public_feed.load()
    have = [r["ticker"] for r in ds.rows if r["ticker"].upper() in cache["tickers"]]
    return {"securities": len(ds.rows), "covered": len(have), "retrieved_at": cache["retrieved_at"],
            "latest_quote_date": public_feed.status()["latest_quote_date"], "sources": cache["sources"]}


def events_for(ticker):
    return [e for e in feed() if e["ticker"].upper() == ticker.upper()]


def fetch(since=None):
    return [e for e in feed() if since is None or e["date"] >= since]


def baseline_check():
    """Compare each workbook price with the real close on the snapshot date; differences point to data errors."""
    ds, cache = workbook.current(), public_feed.load()["tickers"]
    out = []
    for row in ds.rows:
        q = (cache.get(row["ticker"].upper()) or {}).get("quote")
        if not q or not row["price"]:
            continue
        closes = [c for d, c in q["series"] if d <= ds.snapshot.isoformat()]
        if not closes:
            continue
        diff = (closes[-1] / row["price"] - 1) * 100
        out.append({"ticker": row["ticker"], "company": row["company"], "workbook_price": row["price"], "market_close": round(closes[-1], 2),
                    "diff_pct": round(diff, 1), "matches": abs(diff) <= 1.0})
    return out


def compare():
    """Compare feed events against the workbook baseline, one entry per security."""
    out = []
    for ticker in sorted({e["ticker"] for e in feed()}):
        row = workbook.by_ticker(ticker)
        if not row:
            continue
        evs = events_for(ticker)
        priced = [e for e in evs if e.get("price")]
        delta = None
        if priced and row["price"]:
            latest = max(priced, key=lambda e: e["date"])
            delta = round((latest["price"] / row["price"] - 1) * 100, 1)
        sev = max((SEVERITY_WEIGHT[e["severity"]] for e in evs), default=0)
        material = sev >= 3 or (delta is not None and abs(delta) >= MATERIAL_PRICE_MOVE)
        reasons = []
        if delta is not None and abs(delta) >= MATERIAL_PRICE_MOVE:
            reasons.append(f"price {delta:+.1f}% vs workbook")
        reasons += [f"\u201c{e['headline']}\u201d" for e in evs if e["severity"] == "high" and e["type"] != "price_move"]
        news = [e for e in evs if e["kind"] == "news"]
        pick = max(news, key=lambda e: (SEVERITY_WEIGHT[e["severity"]], e["date"])) if news else (evs[0] if evs else None)
        rank = (1 if material else 0, abs(delta or 0) / 10 + sev + (0.5 if not row["complete"] else 0))
        out.append(
            {
                "ticker": ticker, "company": row["company"], "sector": row["sector"], "row_id": row["id"],
                "snapshot_price": row["price"], "price_delta_pct": delta, "events": evs,
                "max_severity": sev, "material": material, "reasons": reasons, "signal": row["signal"],
                "has_baseline": row["complete"], "_rank": rank,
                "top": {k: pick[k] for k in ("id", "headline", "source", "date", "url")} if pick else None,
            }
        )
    out.sort(key=lambda c: c["_rank"], reverse=True)
    for c in out:
        c.pop("_rank")
    return out
