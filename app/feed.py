"""Real public market feed for the monitoring agents.

Quotes come from the Yahoo Finance chart endpoint (end-of-day closes on SIX), news from the Google News RSS
search. Nothing is generated: `python -m app.feed refresh` downloads the data once into
data/feed/market_feed.json and the app only reads that cache, so a demo works without internet.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from . import workbook
from .config import FEED_PATH

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
LOOKBACK_DAYS = 90
MAX_NEWS_PER_COMPANY = 12
QUOTE_URL = "https://finance.yahoo.com/quote/{symbol}"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval=1d"
NEWS_URL = "https://news.google.com/rss/search?"

LEGAL_SUFFIX = re.compile(r"\b(AG|SA|Inc\.?|Ltd\.?|Holding|Holdings|plc|Corp\.?)\b", re.I)
# Search aids for names that are too generic on their own.
QUERY_HINTS = {"SGSN": '"SGS" Switzerland inspection', "UHR": '"Swatch Group"', "SIGN": '"SIG Group" packaging',
               "HBAN": '"Helvetia Baloise"', "ADEN": '"Adecco Group"', "GF": '"Georg Fischer"', "ACLN": '"Accelleron"',
               "CFR": '"Richemont"', "LISN": '"Lindt" Sprüngli', "SUNN": '"Sunrise" Switzerland telecom', "GALE": '"Galenica"'}
GENERIC_WORDS = {"group", "international", "swiss", "compagnie", "financière", "financiere", "holding", "baloise"}
# Pages that only show a price chart, a valuation ratio or a mechanical forecast, not a news event.
NOISE_SOURCES = {"tradingview", "marketbeat", "stock traders daily", "stockstotrade", "stocktwits", "investing.com india"}
NOISE_TITLE = re.compile(r"stock price|share price|stock forecast|price target 20|risk zones|quote and history|stock chart|"
                         r"\(.{2,6}\) stock|key facts about|ownership|institutional|shares (sold|bought|acquired) by|"
                         r"position in|stake (raised|trimmed|lifted|cut) by|price[- ]to[- ]earnings|times earnings|fair value|"
                         r"stock (costs|sits|trades at|faces)|stock .*\d+(\.\d+)? percent (above|below)|slideshow|analysts offer insights", re.I)


def is_noise(title, source=""):
    return source.lower() in NOISE_SOURCES or bool(NOISE_TITLE.search(title))


def _get(url, timeout=25, tries=2):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1)
    raise last


def clean_company(name):
    return re.sub(r"\s+", " ", LEGAL_SUFFIX.sub("", name)).strip(" .,")


def _lookback_days():
    """At least 90 days, and always back to ten days before the workbook snapshot so the price check keeps working."""
    return max(LOOKBACK_DAYS, (datetime.now(timezone.utc).date() - workbook.sample().snapshot).days + 10)


def fetch_quotes(symbol, days=None):
    days = days or _lookback_days()
    now = int(time.time())
    data = json.loads(_get(CHART_URL.format(symbol=urllib.parse.quote(symbol), p1=now - days * 86400, p2=now + 86400)))
    res = data["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    series = [[datetime.fromtimestamp(t, timezone.utc).date().isoformat(), round(c, 4)] for t, c in zip(res["timestamp"], closes) if c is not None]
    return {"symbol": symbol, "currency": res["meta"].get("currency"), "exchange": res["meta"].get("fullExchangeName"),
            "url": QUOTE_URL.format(symbol=symbol), "series": series}


def _words(text):
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def fetch_news(name, hint=None, days=None):
    days = days or _lookback_days()
    query = (hint or f'"{clean_company(name)}"') + f" when:{days}d"
    url = NEWS_URL + urllib.parse.urlencode({"q": query, "hl": "en-CH", "gl": "CH", "ceid": "CH:en"})
    root = ET.fromstring(_get(url))
    tokens = [w for w in re.findall(r"[\wéèüöä]+", clean_company(name).lower()) if len(w) >= 3 and w not in GENERIC_WORDS]
    pattern = re.compile(r"\b(" + "|".join(re.escape(t) for t in (tokens or [clean_company(name).lower()])) + r")", re.I)
    items, seen = [], []
    for it in root.iter("item"):
        src = it.find("source")
        source = (src.text if src is not None else "").strip()
        title = (it.findtext("title") or "").strip()
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3].strip()
        try:
            when = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).date().isoformat()
        except (TypeError, ValueError):
            continue
        if is_noise(title, source) or not pattern.search(title):
            continue
        w = _words(title)
        if any(len(w & s) / max(1, len(w | s)) > 0.6 for s in seen):
            continue
        seen.append(w)
        items.append({"title": title, "source": source, "date": when, "url": it.findtext("link")})
    items.sort(key=lambda i: i["date"], reverse=True)
    return items[:MAX_NEWS_PER_COMPANY]


def _one(args):
    row, primary = args
    out = {"company": row["company"], "symbol": row["ticker"] + ".SW", "primary": primary, "error": None}
    try:
        out["quote"] = fetch_quotes(out["symbol"])
    except Exception as exc:  # noqa: BLE001
        out["quote"], out["error"] = None, f"quote: {type(exc).__name__}"
    out["news"] = []
    if primary:
        try:
            out["news"] = fetch_news(row["company"], QUERY_HINTS.get(row["ticker"]))
        except Exception as exc:  # noqa: BLE001
            out["error"] = (out["error"] or "") + f" news: {type(exc).__name__}"
    return row["ticker"], out


def refresh(tickers=None, log=print):
    """Download quotes and news for the sample workbook's securities (or only `tickers`) into the cache."""
    rows = workbook.sample().rows
    seen, jobs = set(), []
    for r in rows:
        primary = r["company"] not in seen
        seen.add(r["company"])
        if tickers is None or r["ticker"] in tickers:
            jobs.append((r, primary))
    old = json.loads(FEED_PATH.read_text(encoding="utf-8")) if FEED_PATH.exists() else {"tickers": {}}
    merged = dict(old.get("tickers", {}))
    with ThreadPoolExecutor(5) as ex:
        for ticker, out in ex.map(_one, jobs):
            if out["error"] and ticker in merged:
                log(f"  {ticker}: {out['error']} (kept the previous data)")
                continue
            merged[ticker] = out
            log(f"  {ticker}: {len(out['quote']['series']) if out['quote'] else 0} closes, {len(out['news'])} news items" + (f" ({out['error']})" if out["error"] else ""))
    payload = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {"quotes": "Yahoo Finance chart API (SIX end-of-day closes)", "news": "Google News RSS search"},
        "tickers": merged,
    }
    FEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEED_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


_cache = {}


def load():
    """The cached feed, re-read whenever the file changes."""
    if not FEED_PATH.exists():
        return {"retrieved_at": None, "sources": {}, "tickers": {}}
    stamp = FEED_PATH.stat().st_mtime_ns
    if _cache.get("stamp") != stamp:
        _cache.update(stamp=stamp, data=json.loads(FEED_PATH.read_text(encoding="utf-8")))
    return _cache["data"]


def status():
    d = load()
    t = d["tickers"]
    latest = max((q["quote"]["series"][-1][0] for q in t.values() if q.get("quote") and q["quote"]["series"]), default=None)
    return {"retrieved_at": d["retrieved_at"], "tickers": len(t), "quotes": sum(1 for q in t.values() if q.get("quote")),
            "news_items": sum(len(q.get("news", [])) for q in t.values()), "latest_quote_date": latest, "sources": d["sources"]}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "refresh":
        refresh(set(a.upper() for a in sys.argv[2:]) or None)
        print(json.dumps(status(), indent=1))
    else:
        print(json.dumps(status(), indent=1))
