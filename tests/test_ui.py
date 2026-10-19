"""Browser tests for the pages: how much text a first-time viewer sees, and that details stay behind a click.

They start the app on a free port (offline mode, no Azure) and drive it with headless Chromium.
They are skipped when Playwright or its browser is not installed:  pip install playwright; playwright install chromium
"""
import json
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from app.config import ROOT

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

pytestmark = pytest.mark.ui

PAGES = ["overview", "upload", "workbook", "reports", "monitor", "chat", "plan", "trust", "bakeoff"]
# Words a first-time viewer sees on arrival. Measured values are 20 to 30 percent below these limits.
WORD_BUDGET = {"overview": 300, "upload": 350, "workbook": 480, "reports": 340, "monitor": 340, "chat": 150, "plan": 300, "trust": 200, "bakeoff": 180}


@pytest.fixture(scope="module")
def server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**__import__("os").environ, "FOUNDRY_ENDPOINT": ""}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            urllib.request.urlopen(f"{url}/api/status", timeout=1).read()
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("the app did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no Chromium available: {str(exc).splitlines()[0]}")
        yield b
        b.close()


@pytest.fixture
def open_page(browser, server):
    opened = []

    def go(name, width=1440, height=900):
        ctx = browser.new_context(viewport={"width": width, "height": height})
        ctx.add_init_script("localStorage.setItem('mode', 'offline')")
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(f"{server}/#/{name}")
        page.wait_for_selector("#view > *:not(.skel)", timeout=15000)
        page.wait_for_timeout(1200)
        opened.append(ctx)
        page.errors = errors
        return page

    yield go
    for c in opened:
        c.close()


def words(page, selector="main"):
    """Visible words; the entries of a closed dropdown are not shown on arrival, so they do not count."""
    total = len(page.inner_text(selector).split())
    options = page.evaluate("(s) => [...document.querySelectorAll(s + ' option')].reduce((n, o) => n + o.textContent.split(/\\s+/).filter(Boolean).length, 0)", selector)
    return total - options


@pytest.mark.parametrize("name", PAGES)
def test_a_page_shows_little_text_on_arrival_and_no_errors(open_page, name):
    page = open_page(name)
    n = words(page)
    assert n <= WORD_BUDGET[name], f"{name} shows {n} words on arrival (limit {WORD_BUDGET[name]}); move detail behind a disclosure"
    assert not page.errors, page.errors


@pytest.mark.parametrize("name", PAGES)
def test_the_page_guide_is_closed_until_asked_for_and_remembered_per_page(open_page, name):
    page = open_page(name)
    btn = page.locator("#guide-toggle")
    assert btn.get_attribute("aria-expanded") == "false" and not page.locator("#guide").is_visible()
    btn.click()
    assert btn.get_attribute("aria-expanded") == "true" and page.locator("#guide").is_visible()
    assert "what it shows" in page.inner_text("#guide").lower()
    page.reload()
    page.wait_for_selector("#guide-toggle")
    assert page.locator("#guide").is_visible(), "the choice is remembered for this page"
    other = "chat" if name != "chat" else "trust"
    page.goto(page.url.split("#")[0] + f"#/{other}")
    page.wait_for_timeout(600)
    assert not page.locator("#guide").is_visible(), "other pages stay closed"


@pytest.mark.parametrize("name", PAGES)
@pytest.mark.parametrize("width", [1200, 900, 600])
def test_no_page_scrolls_sideways(open_page, name, width):
    page = open_page(name, width=width)
    over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 2, f"{name} overflows by {over}px at {width}px"


def test_findings_show_a_title_and_a_severity_until_you_open_one(open_page):
    page = open_page("workbook")
    tiles = page.locator(".ftile")
    assert tiles.count() == 4 and page.locator(".sev-row .chip").count() >= 2
    assert not page.locator(".ftile .ft-b").first.is_visible()
    tiles.first.locator("summary").click()
    assert "mis-scaled" in tiles.first.inner_text() and tiles.first.locator(".ft-b").is_visible()
    assert tiles.nth(1).locator(".ft-b").is_visible() is False, "opening one tile leaves the others closed"


def test_the_table_shows_ten_rows_until_you_ask_for_all_or_filter(open_page):
    page = open_page("workbook")
    assert page.locator("#tbody tr").count() == 10
    page.click("#more")
    assert page.locator("#tbody tr").count() == 50 and "Show fewer" in page.inner_text("#more")
    page.click("#more")
    page.fill("#q", "roche")
    assert page.locator("#tbody tr").count() == 2 and not page.locator("#more").is_visible()


def test_overview_hides_prompts_and_the_long_table_and_explains_the_dots_on_hover(open_page):
    page = open_page("overview")
    assert not page.locator(".step .quote").first.is_visible()
    page.locator(".step .disc summary").first.click()
    assert page.locator(".step .quote").first.is_visible()
    assert page.locator(".cmp").is_visible() is False
    page.locator("summary", has_text="More differences").click()
    assert page.locator(".cmp").is_visible()
    assert page.locator(".spec .pin").count() == 10, "five spectrums with two dots each, one of them about the interface"
    assert all("Copilot Studio:" in t or "Foundry:" in t for t in page.eval_on_selector_all(".spec .pin", "e => e.map(x => x.dataset.tip)"))


def test_finished_upload_steps_fold_to_one_line_and_open_again_with_their_content(open_page):
    page = open_page("upload")
    page.wait_for_selector(".ready")
    assert page.locator(".panel.done").count() == 4
    assert all(not b.is_visible() for b in page.locator(".panel.done .panel-b").all())
    assert "16 of 17 columns" in page.inner_text("#panels")
    page.locator(".panel.done .panel-h").nth(2).click()
    page.wait_for_timeout(400)
    assert page.locator(".panel.open .map").is_visible() and page.locator(".map-svg path").count() >= 15
    assert page.locator(".panel.done .panel-h").nth(2).get_attribute("aria-expanded") == "true"


def test_monitor_briefing_is_an_accordion_with_counts_and_the_review_is_a_row_of_checks(open_page):
    page = open_page("monitor")
    page.click("#run")
    page.wait_for_selector("#appr button", timeout=60000)
    page.wait_for_timeout(500)
    sections = page.locator(".brief .disc.acc")
    assert sections.count() == 4
    assert [s.evaluate("e => e.open") for s in sections.all()] == [True, False, False, False], "only the facts start open"
    counts = [int(c) for c in page.eval_on_selector_all(".brief .disc.acc .count", "e => e.map(x => x.textContent)")]
    assert counts[0] == page.locator(".brief .disc.acc").first.locator(".fact").count() and all(c > 0 for c in counts)
    assert page.locator(".ck-strip .ckd.ok").count() == 6 and "6/6 checks passed" in page.inner_text("#results")
    assert not page.locator(".checks").first.is_visible(), "the check details are one click away"
    assert page.locator(".chg").count() >= 3 and page.locator(".chg:visible").count() == 3


def test_chat_has_one_place_for_suggestions_and_indicators_instead_of_paragraphs(open_page):
    page = open_page("chat")
    assert page.locator(".sugg").count() == 9 and page.locator(".sugg.report").count() == 2 and "Try asking" not in page.inner_text("main")
    assert page.locator(".ind").count() == 3 and page.locator(".mini-stats > div").count() == 4
    assert all(not b.is_visible() for b in page.locator(".chat-side .disc-b").all())


# ------------------------------------------------------------------ the chat as a custom interface: clickable peers

def test_peer_explorer_shows_the_peers_of_a_company_with_indicators(open_page):
    page = open_page("chat")
    assert page.locator(".peer.self .pn").inner_text() == "Novartis"
    assert page.locator(".peer:visible .pn").all_inner_texts()[:3] == ["Novartis", "Roche", "Sonova"], "peers are listed by momentum"
    assert page.locator(".peer:visible .pbar i").count() == 6 and page.locator(".peer:visible .sg.pos, .peer:visible .sg.mix").count() == 6
    assert page.locator(".peer.self .pdoc svg").count() == 1, "Novartis has a half-year report, shown as an icon"
    assert "momentum" in page.locator(".peer").nth(1).get_attribute("title") and not page.locator("#tray").is_visible()
    page.select_option("#xco", "UBSG")
    page.wait_for_function("document.querySelector('.peer.self')?.dataset.t === 'UBSG'")
    assert "financials peers" in page.inner_text("#xpeers").lower() and page.locator(".peer:visible").count() >= 5
    assert not page.errors, page.errors


def test_clicking_peers_fills_and_empties_the_reference_tray(open_page):
    page = open_page("chat")
    page.locator(".peer.self").click()
    assert page.locator("#tray").is_visible() and page.locator("#pills .pill").all_inner_texts()[0].startswith("Novartis")
    assert "Novartis" in page.get_attribute("#q", "placeholder") and page.locator("#acts .sugg").all_inner_texts() == ["Peers", "What changed", "H1 results"]
    page.locator(".peer:not(.self)").first.click()
    assert page.locator("#pills .pill").count() == 2 and page.locator(".peer.on").count() == 2
    assert page.locator("#acts .sugg").first.inner_text() == "Compare" and "these companies" in page.get_attribute("#q", "placeholder")
    page.locator("#pills [data-rm]").first.click()
    assert page.locator("#pills .pill").count() == 1 and page.locator(".peer.self.on").count() == 0
    page.locator(".peer:not(.self)").first.click()
    assert not page.locator("#tray").is_visible() and page.locator(".peer.on").count() == 0
    for name in range(1, 6):
        page.locator(".peer:visible").nth(name).click()
    page.locator("summary", has_text="more peers").click()
    page.locator(".peer:visible").last.click()
    assert page.locator("#pills .pill").count() == 5 and "five companies" in page.inner_text("#toast, .toast, body")
    page.click("[data-clear]")
    assert not page.locator("#tray").is_visible() and page.locator(".peer.on").count() == 0


def test_attached_companies_travel_with_the_question_and_show_in_the_message(open_page):
    page = open_page("chat")
    page.locator(".peer.self").click()
    page.locator(".peer:not(.self)").first.click()
    with page.expect_request(lambda r: r.url.endswith("/api/chat/stream")) as sent:
        page.locator("#acts .sugg", has_text="Compare").click()
    body = sent.value.post_data_json
    assert body["message"] == "Compare these companies" and body["references"] == ["NOVN", "RO"] and body["mode"] == "offline"
    page.wait_for_selector(".badges", timeout=30000)
    assert page.locator(".msg.user .msg-refs .pill").all_inner_texts() == ["Novartis", "Roche"]
    answer = page.inner_text(".msg.bot:last-child .ans")
    assert "Novartis AG" in answer and "Roche Holding AG" in answer and "Comparison" in answer
    assert page.locator("#pills .pill").count() == 2, "the selection stays for the next question until it is cleared"
    assert not page.locator(".badges .chip.warn").count() and not page.errors, page.errors


def test_company_codes_in_answers_are_clickable_and_stay_in_sync_with_the_explorer(open_page):
    page = open_page("chat")
    page.fill("#q", "Compare Novartis and Roche")
    page.click("#send")
    page.wait_for_selector(".badges", timeout=30000)
    chips = page.locator(".msg.bot:last-child .cref")
    assert chips.all_inner_texts() == ["NOVN", "RO"] and not page.locator("#tray").is_visible()
    chips.nth(1).click()
    assert page.locator("#pills .pill").all_inner_texts()[0].startswith("Roche") and "on" in chips.nth(1).get_attribute("class").split()
    assert page.locator('.peer[data-t="RO"].on').count() == 1
    page.locator('.peer[data-t="RO"]').click()
    assert page.locator("#pills .pill").count() == 0 and "on" not in chips.nth(1).get_attribute("class").split()


def test_a_model_may_write_company_codes_with_or_without_brackets(open_page):
    page = open_page("chat")
    answer = {"type": "answer", "text": "UBSG leads PGHN on momentum [SEC-006]. Novartis AG (NOVN) and Roche (RO) are peers; GF, IFRS and SEC are not companies in the list.",
              "sources": {}, "checks": {"cited": ["SEC-006"], "unknown_sources": [], "figures": 0, "ungrounded": [], "advice": False}, "blocked": False, "steps": [],
              "context": ["UBSG"], "followups": [], "live": True, "tokens_in": 1, "tokens_out": 1, "cost": 0, "elapsed": 0.1}
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in ({"type": "start", "mode": "live", "model": "x", "references": []}, answer, {"type": "done"}))
    page.route("**/api/chat/stream", lambda route: route.fulfill(status=200, content_type="text/event-stream", body=body))
    page.fill("#q", "anything")
    page.click("#send")
    page.wait_for_selector(".badges", timeout=15000)
    assert page.locator(".msg.bot:last-child .cref").all_inner_texts() == ["UBSG", "PGHN", "NOVN", "RO"], "GF has only two letters and no brackets, so it stays text"
    assert "GF, IFRS and SEC" in page.inner_text(".msg.bot:last-child .ans")


def test_the_explorer_follows_the_conversation_to_another_sector(open_page):
    page = open_page("chat")
    page.fill("#q", "Tell me about UBS")
    page.click("#send")
    page.wait_for_selector(".badges", timeout=30000)
    page.wait_for_function("document.querySelector('.peer.self')?.dataset.t === 'UBSG'")
    assert "financials peers" in page.inner_text("#xpeers").lower()


def test_new_chat_clears_the_attached_companies(open_page):
    page = open_page("chat")
    page.locator(".peer.self").click()
    assert page.locator("#tray").is_visible()
    page.click("#newchat")
    assert not page.locator("#tray").is_visible() and page.locator(".peer.on").count() == 0 and "Ask about companies" in page.get_attribute("#q", "placeholder")


def test_the_chat_with_attached_companies_does_not_scroll_sideways_on_a_narrow_window(open_page):
    page = open_page("chat", width=600)
    page.locator(".peer.self").click()
    page.locator(".peer:not(.self)").first.click()
    page.locator(".peer:not(.self)").nth(1).click()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "tray and explorer must fit a narrow window"
    assert page.locator("#tray").is_visible()


def test_trust_lab_heat_map_matches_the_scores_and_opens_the_case(open_page):
    page = open_page("trust")
    assert page.locator("#heat .hc").count() == 30 and not page.locator("#cases").is_visible()
    page.click("#run")
    page.wait_for_function("document.querySelector('#run').textContent.includes('Run again')", timeout=40000)
    for row, ring in ((0, "#ring-basic"), (1, "#ring-governed")):
        cells = page.locator("#heat .hc").all()[row * 15:(row + 1) * 15]
        passed = sum(1 for c in cells if "pass" in c.get_attribute("class") or "blocked" in c.get_attribute("class"))
        assert page.inner_text(f"{ring} span").split("/")[0] == str(passed)
    page.locator("#heat .hc.fail").first.click()
    assert page.locator(".drawer h3").is_visible() and "Pass criterion" in page.inner_text(".drawer")
    page.click(".drawer #x")
    page.locator("summary", has_text="All 15 questions").click()
    assert page.locator("#cases .case").count() == 15 and page.locator("#cases").is_visible()


def test_bakeoff_recommendation_is_three_numbers_with_the_reason_behind_a_click(open_page):
    page = open_page("bakeoff")
    page.click("#run")
    page.wait_for_function("document.querySelector('#run').textContent.includes('Run again')", timeout=40000)
    page.wait_for_selector(".reco-stats")
    assert page.locator(".reco-stats > div").count() == 3
    assert not page.locator(".reco .disc-b").is_visible()
    page.locator(".reco summary").click()
    assert "quality bar" in page.inner_text(".reco .disc-b")


def test_the_demo_guide_and_the_zoom_button_still_work(open_page):
    page = open_page("overview")
    page.click("#guide-btn")
    assert page.locator("#dg").is_visible() and page.locator(".dstep").count() == 10
    page.keyboard.press("Escape")
    assert not page.locator("#dg").is_visible()
    page.click("#zoom-btn")
    assert page.evaluate("document.body.classList.contains('big')")




def test_reports_page_shows_figures_with_page_chips_and_searches_the_text(open_page):
    page = open_page("reports")
    assert page.locator(".rep").count() == 5 and page.locator(".rep-stat").count() == 15
    chips = page.locator(".rep a.src.report")
    assert chips.count() == 15 and "#page=" in chips.first.get_attribute("href") and chips.first.get_attribute("target") == "_blank"
    assert page.locator("#b-growth .bar-row").count() == 5 and page.locator("#b-margin .bar-row").count() == 5
    assert "Search with keywords" in page.inner_text("#rep-mode"), "offline mode searches by keywords and never calls Azure"
    assert not page.locator(".rep .disc-b").first.is_visible(), "report details are one click away"
    page.locator(".rep summary", has_text="About this report").first.click()
    assert "Period ended" in page.inner_text(".rep .disc-b")
    page.select_option("#rt", "ALC")
    page.fill("#rq", "operating income")
    page.click("#rgo")
    page.wait_for_selector(".passage")
    assert page.locator(".passage").count() >= 3 and page.locator(".passage mark").count() > 0
    assert page.inner_text("#rres").count("Alcon") >= 3 and "keywords" in page.inner_text("#rres")
    page.locator(".sugg[data-q]").first.click()
    page.wait_for_function("document.querySelector('#rq').value === 'outlook'")


def test_chat_shows_report_sources_as_links_to_the_pdf_page(open_page):
    page = open_page("chat")
    page.fill("#q", "What were Novartis net sales and operating income in H1 2026?")
    page.click("#send")
    page.wait_for_selector(".badges", timeout=30000)
    link = page.locator(".msg.bot a.src.report").first
    assert "NOVN p.3" in link.inner_text() and link.get_attribute("href").endswith("/api/reports/NOVN/file#page=3")
    assert "27,521" in page.inner_text(".msg.bot:last-child") and page.locator(".badges .chip.good").count() >= 2
    assert not page.locator(".badges .chip.warn").count(), "no ungrounded figure and no unknown source"


def test_monitor_briefing_shows_report_facts_with_clickable_pages(open_page):
    page = open_page("monitor")
    page.select_option("#focus", "NOVN")
    page.click("#run")
    page.wait_for_selector("#appr button", timeout=60000)
    assert page.locator(".brief .fact a.src.report").count() == 2
    assert "6/6 checks passed" in page.inner_text("#results")


def ask_plan(page, text):
    page.fill("#pl-q", text)
    page.press("#pl-q", "Enter")
    page.wait_for_function("!document.querySelector('#pl-send').disabled && document.querySelectorAll('#pl-msgs .badges').length > 0", timeout=20000)
    page.wait_for_timeout(500)


def test_plan_page_starts_with_the_cowork_shortlist_and_checks_the_hypothesis(open_page):
    page = open_page("plan")
    page.evaluate("sessionStorage.removeItem('salesPlan')")
    page.reload()
    page.wait_for_selector(".acc[data-t]")
    assert page.eval_on_selector_all(".acc[data-t]", "els => els.map(e => e.dataset.t)") == ["UBSG", "VACN", "CLN"]
    assert "Run-rate efficiency programme" in page.inner_text(".acc.on")
    assert "Evidence found" in page.inner_text(".hyp") and page.locator(".ev.supports .src.news").count() >= 2
    assert sum(int(x) for x in page.eval_on_selector_all(".acc .days b", "els => els.map(e => e.textContent)")) == 20
    assert not page.errors


def test_the_plan_assistant_drives_the_dashboard(open_page):
    page = open_page("plan")
    page.evaluate("sessionStorage.removeItem('salesPlan')")
    page.reload()
    page.wait_for_selector(".acc[data-t]")
    ask_plan(page, "We only have 12 seller days this quarter. Where should they go?")
    page.wait_for_function("document.querySelector('#cap-v').textContent === '12'")
    page.wait_for_timeout(600)
    assert sum(int(x) for x in page.eval_on_selector_all(".acc .days b", "els => els.map(e => e.textContent)")) == 12
    ask_plan(page, "How does Clariant compare with its competitors?")
    page.wait_for_selector("#pl-comp")
    assert page.get_attribute(".acc.on", "data-t") == "CLN" and "Clariant" in page.inner_text("#pd-name")
    assert page.get_attribute("#pd-tabs button.on", "data-v") == "competitors"
    ask_plan(page, "Build the sales plan for all three accounts")
    assert page.locator(".plan-tbl tbody tr").count() == 3 and page.is_enabled("#pl-dl")
    with page.expect_download() as dl:
        page.click("#pl-dl")
    text = open(dl.value.path(), encoding="utf-8").read()
    assert "FinOps for cloud and AI" in text and "[SIG-046]" in text and "12 days" in text
    assert not page.errors


def test_plays_can_be_added_by_hand_and_open_a_talk_track(open_page):
    page = open_page("plan")
    page.evaluate("sessionStorage.removeItem('salesPlan')")
    page.reload()
    page.click("#pd-tabs button[data-v=plays]")
    page.click(".play[data-p=finops] .add-play")
    assert page.inner_text(".play[data-p=finops] .add-play") == "✓ In plan" and page.locator(".plan-tbl tbody tr").count() == 1
    page.click(".play[data-p=finops] .talk-d summary")
    page.wait_for_selector(".play[data-p=finops] .talk-l")
    talk = page.inner_text(".play[data-p=finops] .talk-l")
    assert "Swiss Lawmakers Support Levy" in talk and "Model Bake-off" in talk
    page.click(".plan-tbl [data-del]")
    assert page.inner_text(".play[data-p=finops] .add-play") == "+ Add to plan"
    assert not page.errors
