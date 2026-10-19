"""HTTP layer: every endpoint returns data consistent with the workbook."""
import json

import pytest
from fastapi.testclient import TestClient

from app import agents, evals
from app.main import APPROVALS, app

client = TestClient(app)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    async def instant(_seconds=0):
        return None

    monkeypatch.setattr(agents, "pace", instant)


def sse(url):
    events = []
    with client.stream("GET", url) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: ") and line != "data: {}":
                events.append(json.loads(line[6:]))
    return events


def test_index_and_static_assets_are_served():
    assert "Foundry Account Intelligence" in client.get("/").text
    for path in ("/app.js", "/app.css", "/vendor/chart.umd.min.js"):
        assert client.get(path).status_code == 200, path


def test_workbook_endpoint_returns_all_rows_and_findings(raw):
    data = client.get("/api/workbook").json()
    assert len(data["rows"]) == 50 and data["kpis"]["complete"] == 44
    assert [r["ticker"] for r in data["rows"]] == [r["Ticker"] for r in raw]
    assert len(data["findings"]) == 4 and len(data["prompts"]) == 10 and len(data["sectors"]) == 9


def test_status_endpoint_reports_models_and_prices():
    s = client.get("/api/status").json()
    assert set(s["models"]) >= {"steward", "scout", "analyst", "reviewer", "judge"}
    assert s["prices"]["gpt-5.5"]["out"] > s["prices"]["gpt-5.6-luna"]["out"] > s["prices"]["gpt-6-luna"]["out"]
    assert s["recordings"] == {"trust_lab": True, "bakeoff": True}


def test_signals_endpoint_lists_material_changes():
    data = client.get("/api/signals").json()
    assert len(data) > 20 and any(c["material"] for c in data) and "events" not in data[0]
    assert all(c["top"]["url"].startswith("https://") and c["event_count"] >= 1 for c in data)


def test_feed_endpoint_reports_freshness_coverage_and_the_price_check():
    d = client.get("/api/feed").json()
    assert d["status"]["quotes"] == 50 and d["status"]["retrieved_at"] and d["coverage"]["covered"] == 50
    assert d["baseline"]["checked"] == 44 and {x["ticker"] for x in d["baseline"]["differences"]} <= {"RO", "ROP"}
    assert d["events"] > 50


def test_trustlab_cases_endpoint():
    data = client.get("/api/trustlab/cases").json()
    assert len(data["cases"]) == 15 and [c["key"] for c in data["configs"]] == ["basic", "governed"]
    assert all("forbid" not in c for c in data["cases"]), "rule patterns must not leak to the browser"


def test_monitor_stream_runs_a_full_offline_cycle():
    events = sse("/api/monitor/stream?mode=offline&focus=CLN")
    assert events[0]["type"] == "cycle_start" and events[-1]["type"] == "done"
    briefing = next(e for e in events if e["type"] == "briefing")["briefing"]
    assert briefing["ticker"] == "CLN" and briefing["company"] == "Clariant AG"


def test_monitor_stream_reports_errors_instead_of_crashing(monkeypatch):
    async def broken(*_a, **_k):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(agents, "run_cycle", broken)
    events = sse("/api/monitor/stream")
    assert events[-1] == {"type": "error", "message": "boom"}


def test_trust_lab_and_bakeoff_replay_streams(monkeypatch):
    async def no_delay(name, delay=0.3):
        async for e in original(name, 0):
            yield e

    original = evals.replay_events
    monkeypatch.setattr(evals, "replay_events", no_delay)
    monkeypatch.setattr("app.bakeoff.replay_events", no_delay)
    lab = sse("/api/trustlab/stream?mode=offline")
    assert lab[0]["type"] == "lab_start" and lab[0]["recorded_at"] and lab[-1]["type"] == "lab_done"
    assert sum(e["type"] == "lab_result" for e in lab) == 30
    bake = sse("/api/bakeoff/stream?mode=offline")
    assert bake[0]["type"] == "bake_start" and bake[-1]["type"] == "bake_done"
    assert sum(e["type"] == "bake_result" for e in bake) == 15


def test_approvals_are_logged_with_a_timestamp():
    APPROVALS.clear()
    r = client.post("/api/approvals", json={"briefing_id": "abc123", "decision": "approved", "company": "VAT Group", "owner_team": "Industrial & Manufacturing account team"})
    assert r.status_code == 200 and r.json()["at"]
    assert client.get("/api/approvals").json()[0]["briefing_id"] == "abc123"
    assert client.post("/api/approvals", json={"decision": "approved"}).status_code == 422


# ------------------------------------------------------------------ page structure the script depends on

def test_page_has_every_element_the_script_looks_up_exactly_once():
    import re

    html = client.get("/").text
    js = client.get("/app.js").text
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids)), "duplicate ids in index.html"
    for needed in ("nav", "topnav", "guide", "view", "dg", "rail-foot", "top-actions", "page-title", "page-sub", "logo", "progress"):
        assert needed in ids, needed
    assert "#drawer'" not in js, "'#drawer' belongs to the Trust Lab case viewer; the demo guide is '#dg'"
    css = client.get("/app.css").text
    assert css.count(".demo-guide {") == 1 and "body.dg-open" in css


def test_every_page_has_a_guide_and_a_short_nav_label():
    import re

    js = client.get("/app.js").text
    pages = re.findall(r"^  (\w+): \{ title:", js, flags=re.M)
    guide_block = js[js.index("const GUIDE = {"):js.index("const GLOSSARY")]
    for p in pages:
        assert re.search(rf"^  {p}: \{{\r?\n    what:", guide_block, flags=re.M), f"page {p} has no guide"
    assert len(pages) == 9
    for term in re.findall(r"\bgl\('(\w+)'", js):
        assert re.search(rf"^  {term}: '", js[js.index("const GLOSSARY"):], flags=re.M), f"unknown glossary term {term}"



def test_demo_guide_steps_point_to_real_pages_and_warn_about_slow_live_runs():
    import re

    js = client.get("/app.js").text
    block = js[js.index("const DEMO_STEPS = ["):js.index("function renderDrawer")]
    pages = set(re.findall(r"^  (\w+): \{ title:", js, flags=re.M))
    steps = re.findall(r"\{ page: '(\w+)', min: (\d+)(?:, wait: '([^']*)')?", block)
    assert len(steps) == 10 and {p for p, _m, _w in steps} <= pages
    slow = {p: w for p, _m, w in steps if w}
    for page in ("trust", "bakeoff", "monitor"):
        assert page in slow and re.search(r"second|minute", slow[page]), f"{page} needs a timing hint"
    assert "Offline replay" in slow["bakeoff"], "the Bake-off is the longest live run (about a minute); the guide must offer the replay"


