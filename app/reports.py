"""Public reports: the half-year reports companies publish, searchable by passage and reduced to a few verified headline figures.

The PDFs are public but copyrighted. They stay in data/reports on this machine and are never changed. Answers quote short passages with the page number.

  python -m app.reports fetch       # download the PDFs listed in manifest.json (a fresh clone has none)
  python -m app.reports build       # read the PDFs, split them into passages, embed them (embedding needs Azure sign-in)
  python -m app.reports extract     # let a model read the headline figures; each one is checked against the page text
  python -m app.reports status
"""
import array
import asyncio
import base64
import hashlib
import json
import math
import operator
import re
import sys
import time
from contextvars import ContextVar

from . import llm, workbook
from .config import MODELS, ROOT

DIR = ROOT / "data" / "reports"
MANIFEST_PATH = DIR / "manifest.json"
INDEX_PATH = DIR / "index.json"
FIN_PATH = DIR / "financials.json"
CHUNK_CHARS = 900
KEYS = ("revenue", "operating_profit", "net_income")
PERIOD_NOTE = "The report covers the first half of 2026 (to 30 June). Market prices in the workbook are from a different date."

_semantic = ContextVar("reports_semantic", default=False)
_cache = {"manifest": None, "index": None, "chunks": None, "vectors": None, "fin": None, "qvec": {}, "df": None}


def use_semantic(flag):
    """Lets searches in the current task use embeddings (live mode). Offline mode stays on keywords and never calls Azure."""
    _semantic.set(bool(flag))


def reset_cache():
    for k in _cache:
        _cache[k] = {} if k == "qvec" else None


# ----------------------------------------------------------------------------- documents

def _norm(s):
    return re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ").replace("\u202f", " ")).strip().lower()


def manifest():
    if _cache["manifest"] is None:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.exists() else {"documents": []}
        for d in data["documents"]:
            d["ref"] = f"REP-{d['ticker']}"
            d["available"] = (DIR / d["file"]).exists()
        _cache["manifest"] = data
    return _cache["manifest"]


def documents():
    return manifest()["documents"]


def doc_for(ticker_or_row):
    """The report that belongs to a workbook company, or None. The company name must match, so a foreign ticker in an uploaded file is not mistaken for ours."""
    row = ticker_or_row if isinstance(ticker_or_row, dict) else workbook.by_ticker(str(ticker_or_row))
    if not row:
        return None
    for d in documents():
        if d["available"] and d["match"].lower() in row["company"].lower() and row["ticker"] in {d["ticker"], *row.get("share_classes", [])}:
            return d
    return None


def source_meta(ref):
    """Label and details for a source chip like REP-NOVN-p3."""
    m = re.fullmatch(r"REP-([A-Z]+)(?:-p(\d+))?", ref)
    d = next((x for x in documents() if m and x["ticker"] == m.group(1)), None)
    if not d:
        return None
    page = f" p.{m.group(2)}" if m.group(2) else ""
    return {"kind": "report", "label": f"{d['company']} · {d['period']} report{page}", "detail": f"{d['title']} · {d['standard']} · period ended {d['period_end']}",
            "url": f"/api/reports/{d['ticker']}/file" + (f"#page={m.group(2)}" if m.group(2) else "")}


# ----------------------------------------------------------------------------- download

def fetch():
    """Downloads the reports that are missing from data/reports. A file is kept only when it is the exact document the figures were checked on."""
    import urllib.request

    out = {}
    for d in documents():
        path = DIR / d["file"]
        if path.exists():
            out[d["ticker"]] = "present"
            continue
        try:
            req = urllib.request.Request(d["url"], headers={"User-Agent": "Mozilla/5.0 (Foundry Excel demo; report download)"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
        except Exception as e:  # noqa: BLE001 - one unreachable site must not stop the others
            out[d["ticker"]] = f"download failed ({type(e).__name__}); get it from {d['url']}"
            continue
        if d.get("sha256") and hashlib.sha256(data).hexdigest() != d["sha256"]:
            out[d["ticker"]] = f"the company now serves a different file ({len(data):,} bytes, expected {d.get('bytes', 0):,}); not saved, so the checked figures stay valid"
            continue
        path.write_bytes(data)
        out[d["ticker"]] = "downloaded"
    reset_cache()
    return out


# ----------------------------------------------------------------------------- pages and passages

def _read_pdf_pages(path):
    from pypdf import PdfReader

    out = []
    for p in PdfReader(str(path)).pages:
        text = (p.extract_text() or "").replace("\u00a0", " ").replace("\u202f", " ")
        out.append("\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines() if ln.strip()))
    return out


def _index():
    """Page texts per document, cached in data/reports/index.json and rebuilt when a PDF changes."""
    if _cache["index"] is not None:
        return _cache["index"]
    idx = json.loads(INDEX_PATH.read_text(encoding="utf-8")) if INDEX_PATH.exists() else {}
    docs, dirty = idx.get("docs", {}), False
    for d in documents():
        if not d["available"]:
            continue
        size = (DIR / d["file"]).stat().st_size
        if docs.get(d["ticker"], {}).get("size") != size:
            docs[d["ticker"]] = {"size": size, "pages": _read_pdf_pages(DIR / d["file"])}
            dirty = True
    idx = {"version": 1, "docs": docs, "embed": idx.get("embed") if not dirty else None, "vectors": idx.get("vectors") if not dirty else None, "vector_hash": idx.get("vector_hash") if not dirty else None}
    if dirty and docs:
        INDEX_PATH.write_text(json.dumps(idx), encoding="utf-8")
    _cache["index"] = idx
    return idx


def pages(ticker):
    return _index()["docs"].get(ticker, {}).get("pages", [])


def page_text(ticker, page):
    p = pages(ticker)
    return p[page - 1] if 1 <= page <= len(p) else ""


def _chunks():
    if _cache["chunks"] is None:
        out = []
        for d in documents():
            for pn, text in enumerate(pages(d["ticker"]), start=1):
                lines, buf, size, n = text.splitlines(), [], 0, 0
                for ln in lines:
                    buf.append(ln)
                    size += len(ln) + 1
                    if size >= CHUNK_CHARS:
                        out.append({"ticker": d["ticker"], "page": pn, "n": n, "text": " ".join(buf)})
                        n, buf, size = n + 1, buf[-2:], sum(len(x) + 1 for x in buf[-2:])
                if buf and (not out or out[-1]["ticker"] != d["ticker"] or out[-1]["page"] != pn or len(buf) > 2):
                    out.append({"ticker": d["ticker"], "page": pn, "n": n, "text": " ".join(buf)})
        _cache["chunks"] = out
    return _cache["chunks"]


STOP = set("the a an of and or to in on for with by at from as is are was were be been this that these those it its into than then which who what when where how why do does did not no we our".split())
SYNONYMS = {
    "revenue": ["sales", "revenues", "net sales"], "revenues": ["sales"], "turnover": ["sales"], "sales": ["revenue", "net sales"],
    "profit": ["income", "earnings"], "earnings": ["income", "profit"], "ebit": ["operating income", "operating"], "income": ["profit"],
    "outlook": ["guidance", "expect", "expects"], "guidance": ["outlook", "expect"], "margin": ["margins"], "cash": ["cash flow", "liquidity"],
    "debt": ["borrowings", "net debt", "leverage"], "employees": ["headcount", "fte"], "risk": ["risks", "uncertainties"],
}


def _tokens(s):
    return [t for t in re.findall(r"[a-z]+|\d[\d.,']*", s.lower()) if t not in STOP]


def _doc_freq():
    if _cache["df"] is None:
        df, total = {}, 0
        for c in _chunks():
            c["_tok"] = _tokens(c["text"])
            c["_len"] = sum(1 for t in c["_tok"] if t[0].isalpha()) or 1  # tables are mostly numbers; length counts words only
            total += c["_len"]
            for t in set(c["_tok"]):
                df[t] = df.get(t, 0) + 1
        _cache["df"] = (df, total / max(1, len(_chunks())))
    return _cache["df"]


def _keyword_scores(query, ticker):
    """BM25 over the passages. Words from the question count fully, synonyms half, and an exact two-word phrase from the question earns a bonus."""
    df, avg = _doc_freq()
    n = len(_chunks())
    base = _tokens(query)
    weights = {t: 1.0 for t in base}
    for t in base:
        for syn in SYNONYMS.get(t, []):
            for x in _tokens(syn):
                weights.setdefault(x, 0.5)
    phrases = [" ".join(base[i:i + 2]) for i in range(len(base) - 1)]
    scored = []
    for i, c in enumerate(_chunks()):
        if ticker and c["ticker"] != ticker:
            continue
        tf, score = {}, 0.0
        for t in c["_tok"]:
            tf[t] = tf.get(t, 0) + 1
        for t, w in weights.items():
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                score += w * idf * tf[t] * 2.5 / (tf[t] + 1.5 * (0.25 + 0.75 * c["_len"] / avg))
        if score > 0:
            low = c["text"].lower()
            score += 2.0 * sum(1 for ph in phrases if ph in low)
            scored.append((score, i))
    return sorted(scored, reverse=True)

# ----------------------------------------------------------------------------- embeddings

def _unit(v):
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _chunk_hash():
    h = hashlib.sha256()
    for c in _chunks():
        h.update(c["text"].encode("utf-8"))
    return h.hexdigest()[:16]


def _vectors():
    """Vectors aligned with the passages, or None when no matching embedding is stored."""
    if _cache["vectors"] is None:
        idx = _index()
        if not idx.get("vectors") or idx.get("vector_hash") != _chunk_hash():
            _cache["vectors"] = False
        else:
            dims = idx["embed"]["dimensions"]
            arr = array.array("f")
            arr.frombytes(base64.b64decode(idx["vectors"]))
            _cache["vectors"] = [arr[i * dims:(i + 1) * dims].tolist() for i in range(len(arr) // dims)]
    return _cache["vectors"] or None


def build(embed=True):
    """Parses the PDFs, splits them into passages and, when Azure is available, embeds every passage."""
    _cache.update({"index": None, "chunks": None, "vectors": None, "df": None})
    idx = _index()
    chunks = _chunks()
    info = {"documents": len(idx["docs"]), "pages": sum(len(d["pages"]) for d in idx["docs"].values()), "passages": len(chunks), "embedded": False}
    if embed and llm.live_available():
        from .config import EMBED_DIMENSIONS, EMBED_MODEL

        vecs = [_unit(v) for v in llm.embed([c["text"] for c in chunks])]
        flat = array.array("f")
        for v in vecs:
            flat.extend(v)
        idx.update({"embed": {"model": EMBED_MODEL, "dimensions": EMBED_DIMENSIONS, "at": time.strftime("%Y-%m-%d %H:%M")},
                    "vectors": base64.b64encode(flat.tobytes()).decode(), "vector_hash": _chunk_hash()})
        INDEX_PATH.write_text(json.dumps(idx), encoding="utf-8")
        _cache["vectors"] = None
        info["embedded"] = True
    return info


def _query_vector(query):
    if query not in _cache["qvec"]:
        _cache["qvec"][query] = _unit(llm.embed([query])[0])
    return _cache["qvec"][query]


def search(query, ticker=None, k=4):
    """Best passages for a question. Returns (passages, mode). Mode is 'hybrid' (keywords and embeddings) or 'keyword'."""
    chunks = _chunks()
    kw = _keyword_scores(query, ticker)
    ranks = {i: 1 / (60 + r) for r, (_s, i) in enumerate(kw)}
    mode = "keyword"
    vecs = _vectors()
    if vecs and _semantic.get() and llm.live_available():
        try:
            qv = _query_vector(query)
            sem = sorted(((sum(map(operator.mul, qv, vecs[i])), i) for i, c in enumerate(chunks) if not ticker or c["ticker"] == ticker), reverse=True)[:40]
            for r, (_s, i) in enumerate(sem):
                ranks[i] = ranks.get(i, 0) + 1 / (60 + r)
            mode = "hybrid"
        except Exception:  # noqa: BLE001
            mode = "keyword"
    out = []
    boiler = re.compile(r"forward-looking statements|private securities litigation|disclaimer", re.I)
    asked = bool(re.search(r"forward|disclaimer|legal", query, re.I))
    for i, score in sorted(ranks.items(), key=lambda x: -(x[1] * (0.35 if boiler.search(chunks[x[0]]["text"]) and not asked else 1)))[: max(1, k)]:
        c, d = chunks[i], next(x for x in documents() if x["ticker"] == chunks[i]["ticker"])
        out.append({"ref": f"REP-{c['ticker']}-p{c['page']}", "ticker": c["ticker"], "company": d["company"], "page": c["page"], "period": d["period"],
                    "text": c["text"][:700], "score": round(score, 4)})
    return out, mode


# ----------------------------------------------------------------------------- verified headline figures

def fin():
    if _cache["fin"] is None:
        _cache["fin"] = json.loads(FIN_PATH.read_text(encoding="utf-8")) if FIN_PATH.exists() else {"companies": {}}
    return _cache["fin"]


def _variants(v):
    """Ways a number can be printed in a report: 27521 as 27,521 / 27 521 / 27'521, 558 as 558.0, 1859.3 as 1 859.3."""
    v = abs(float(v))
    forms = {f"{v:.3f}".rstrip("0").rstrip("."), f"{v:.1f}", f"{v:.2f}"}
    out = set()
    for s in forms:
        whole, _, frac = s.partition(".")
        seps = [",", " ", "'", ".", "", "\u2019"] if len(whole) > 3 else [""]
        for sep in seps:
            grouped = f"{int(whole):,}".replace(",", sep) if whole else whole
            out.add(grouped + (f".{frac}" if frac else ""))
            out.add(grouped + (f",{frac}" if frac else ""))
    return out

def _spans(value, text):
    """Where a number appears in a text, in any of its printed forms."""
    t = _norm(text)
    found = []
    for var in _variants(value):
        for m in re.finditer(rf"(?<![\d.,'\u2019]){re.escape(var)}(?![\d]|[.,]\d)", t):
            found.append((m.start(), m.end()))
    return found


def number_in(value, text):
    return bool(_spans(value, text))


def same_row_columns(cur, prev, quote, max_gap=14):
    """The two figures must be neighbouring columns of one row (a percent column may sit between them), not two numbers from different lines."""
    best = None
    for a in _spans(cur, quote):
        for b in _spans(prev, quote):
            gap = max(a[0], b[0]) - min(a[1], b[1])
            if gap >= 0 and (best is None or gap < best):
                best = gap
    return best is not None and best <= max_gap


def check_item(ticker, item):
    """Is this figure really on the page? Returns (ok, reason). The quote must be on the page, hold both numbers as printed, and show them as neighbouring columns."""
    page, quote = item.get("page"), item.get("quote", "")
    if not isinstance(page, int) or not 1 <= page <= len(pages(ticker)):
        return False, "page number out of range"
    if not quote or _norm(quote) not in _norm(page_text(ticker, page)):
        return False, "the quote is not on that page"
    for key in ("printed_2026", "printed_2025"):
        if not isinstance(item.get(key), (int, float)):
            return False, f"{key} is not a number"
        if not number_in(item[key], quote):
            return False, f"{key} ({item[key]}) is not in the quote exactly as printed"
    if not same_row_columns(item["printed_2026"], item["printed_2025"], quote):
        return False, "the two numbers are not neighbouring columns of one row; use the row for the same label and the half-year columns"
    return True, "ok"


def financials(ticker):
    """Verified headline figures for a company: revenue, operating profit, net income, growth and margins. None when not available."""
    d = doc_for(ticker)
    comp = fin()["companies"].get(d["ticker"]) if d else None
    if not comp:
        return None
    items = []
    for key in KEYS:
        it = comp["items"].get(key)
        if not it or not it.get("verified"):
            continue
        cur, prev = it["h1_2026"], it["h1_2025"]
        bn = (lambda v: round(v / 1000, 3)) if max(abs(cur), abs(prev)) >= 1000 else (lambda v: None)
        items.append({"key": key, "label": it["label"], "h1_2026": cur, "h1_2025": prev, "h1_2026_billions": bn(cur), "h1_2025_billions": bn(prev),
                      "growth_pct": round((cur / prev - 1) * 100, 1) if prev and prev > 0 else None, "page": it["page"], "ref": f"REP-{d['ticker']}-p{it['page']}"})
    by = {i["key"]: i for i in items}
    margins = {}
    if "revenue" in by:
        for key, name in (("operating_profit", "operating_margin_pct"), ("net_income", "net_margin_pct")):
            if key in by and by["revenue"]["h1_2026"] and by["revenue"]["h1_2025"]:
                margins[name] = {"h1_2026": round(by[key]["h1_2026"] / by["revenue"]["h1_2026"] * 100, 1), "h1_2025": round(by[key]["h1_2025"] / by["revenue"]["h1_2025"] * 100, 1)}
    return {"ticker": d["ticker"], "company": d["company"], "period": d["period"], "period_end": d["period_end"], "standard": d["standard"], "currency": d["currency"],
            "unit": "millions", "report": {"ref": d["ref"], "title": d["title"], "retrieved": manifest()["retrieved"]}, "items": items, "margins": margins, "note": PERIOD_NOTE}


EXTRACT_SYSTEM = """You read the financial statements of a half-year report and copy three headline figures with their evidence.

Return ONLY a JSON object:
{"currency": "CHF or USD", "items": {
  "revenue": {"label": str, "printed_2026": number, "printed_2025": number, "scale": "millions" or "thousands", "page": int, "quote": str},
  "operating_profit": {...}, "net_income": {...}}}

Rules:
- Use the FIRST HALF (six months to 30 June) columns for 2026 and 2025. Never the quarter, never the full year.
  Some tables list the quarter first and the half year after it. Take the half-year columns.
- printed_2026 and printed_2025 are the numbers EXACTLY as printed in the quote, without separators and without converting units
  (for 27 521 write 27521, for 1'121 write 1121, for 511,891 write 511891, for (96) write -96).
- scale is the unit of the table the numbers come from, as stated in its heading (CHF m, $ millions = millions; CHF thousands = thousands).
- "label" is the name used in the report (for example Net sales, Net sales to third parties, Sales, Revenues, Operating income, Operating profit, EBIT, EBITDA, Net income, Profit for the period).
- Read across ONE row of a table: the 2026 number and the 2025 number must be neighbouring columns of the same line, with the same label.
- operating_profit: prefer operating income or EBIT. Use EBITDA only if the report shows neither, and say so in the label.
- net_income: net income or profit for the period of the whole group.
- Prefer the summary table near the start of the report when it shows these figures.
- "page" is the page number given below as PAGE n. "quote" is ONE line copied EXACTLY from that page that contains both numbers. Do not change spaces or characters.
- If a figure is not in the text, omit that item. Never estimate."""

_LABELS = re.compile(r"net sales|sales|revenues?|operating income|operating profit|ebit\b|ebitda|net income|profit for the period|income for the period", re.I)
_QUERIES = ("key figures net sales revenues first half 2026 2025", "operating income EBIT six months 2026 2025", "net income profit for the period six months 2026 2025")


def _candidate_pages(ticker, n=7):
    """Pages most likely to hold the headline figures: those with the most key labels and numbers, plus the best hits for three searches."""
    scored = []
    for pn, text in enumerate(pages(ticker), start=1):
        nums = len(re.findall(r"\d[\d.,' ]{3,}", text))
        head = text.lower()[:600]
        titled = 8 if re.search(r"key figures|income statement|statement of income|financial review|at a glance", head) else 0
        scored.append((len(_LABELS.findall(text)) * 3 + nums / 15 + (2 if "2025" in text and "2026" in text else 0) + (3 if pn <= 12 else 0) + titled, pn))
    cand = [pn for _s, pn in sorted(scored, reverse=True)[:3]]
    for pn in range(1, min(13, len(pages(ticker)) + 1)):
        if re.search(r"key figures|income statement|statement of income|financial review", page_text(ticker, pn).lower()[:600]) and pn not in cand:
            cand.append(pn)
    for q in _QUERIES:
        for pn in [r["page"] for r in _keyword_search(q, ticker, 2)]:
            if pn not in cand:
                cand.append(pn)
    return cand[:n]


def _keyword_search(query, ticker, k):
    chunks = _chunks()
    return [{"page": chunks[i]["page"]} for _s, i in _keyword_scores(query, ticker)[:k]]


def _parse_json(text):
    t = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, flags=re.S)
        return json.loads(m.group(0)) if m else None


async def extract(ticker, attempts=3):
    """Asks a model for the headline figures and keeps only those that pass the page check."""
    d = next(x for x in documents() if x["ticker"] == ticker)
    cand = _candidate_pages(ticker)
    prompt = f"Company: {d['company']}. Report: {d['title']}.\n\n" + "\n\n".join(f"PAGE {pn}:\n{page_text(ticker, pn)[:4500]}" for pn in sorted(cand))
    messages = [{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": prompt}]
    good, problems, data = {}, {}, {}
    for _ in range(attempts):
        r = await llm.chat(MODELS["extractor"], messages, json_mode=True, max_tokens=3000)
        data = _parse_json(r["content"]) or {}
        problems = {}
        for key in KEYS:
            if key in good:
                continue
            it = (data.get("items") or {}).get(key)
            if not isinstance(it, dict):
                problems[key] = "missing"
                continue
            ok, why = check_item(ticker, it)
            if ok:
                div = 1000.0 if str(it.get("scale", "millions")).lower().startswith("thou") else 1.0
                good[key] = {"label": str(it.get("label", key)), "h1_2026": round(float(it["printed_2026"]) / div, 4), "h1_2025": round(float(it["printed_2025"]) / div, 4),
                             "printed_2026": it["printed_2026"], "printed_2025": it["printed_2025"], "scale": "thousands" if div == 1000.0 else "millions",
                             "page": it["page"], "quote": it["quote"], "verified": True}
            else:
                problems[key] = why
        if all(k in good for k in KEYS):
            break
        messages += [{"role": "assistant", "content": r["content"]},
                     {"role": "user", "content": "These items failed the check against the page text: " + json.dumps(problems) + ". Copy the line exactly as it appears on the page and write the numbers exactly as printed."}]
    return {"currency": (data.get("currency") or d["currency"]), "items": good, "problems": problems}

async def extract_all():
    result = {"extracted_at": time.strftime("%d.%m.%Y %H:%M"), "model": MODELS["extractor"], "companies": {}}
    for d in documents():
        if d["available"]:
            result["companies"][d["ticker"]] = await extract(d["ticker"])
            print(d["ticker"], {k: (v["h1_2026"], v["h1_2025"], v["page"], v["label"]) for k, v in result["companies"][d["ticker"]]["items"].items()}, result["companies"][d["ticker"]]["problems"] or "")
    FIN_PATH.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    _cache["fin"] = None
    return result


# ----------------------------------------------------------------------------- overview for the pages and the pre-flight

def overview():
    out = []
    for d in documents():
        row = workbook.by_ticker(d["ticker"])
        f = financials(d["ticker"]) if row else None
        out.append({"ticker": d["ticker"], "company": d["company"], "title": d["title"], "kind": d["kind"], "period": d["period"], "period_end": d["period_end"], "standard": d["standard"],
                    "currency": d["currency"], "url": d["url"], "note": d.get("note"), "available": d["available"], "pages": len(pages(d["ticker"])) if d["available"] else 0,
                    "in_workbook": bool(doc_for(d["ticker"])), "financials": f, "file_url": f"/api/reports/{d['ticker']}/file"})
    return out


def status():
    docs = [d for d in documents() if d["available"]]
    verified = sum(1 for c in fin()["companies"].values() for it in c["items"].values() if it.get("verified"))
    return {"documents": len(documents()), "available": len(docs), "passages": len(_chunks()) if docs else 0, "embedded": bool(_vectors()) if docs else False, "verified_figures": verified,
            "extracted_at": fin().get("extracted_at")}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "fetch":
        for ticker, result in fetch().items():
            print(f"{ticker:5} {result}")
    elif cmd == "build":
        print(build())
    elif cmd == "extract":
        if not llm.live_available():
            raise SystemExit("Live access is not available. Run `az login` and set FOUNDRY_ENDPOINT in .env.")
        asyncio.run(extract_all())
    print(status())








