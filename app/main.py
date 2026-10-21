import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import unquote

from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agents, autorun, bakeoff, chat, evals, feed, llm, logos, reports, salesplan, signals, store, workbook
from .config import BAKEOFF_MODELS, MODEL_TIERS, MODELS, PRICES, QUALITY_BAR, RECORDINGS, STATIC, XLSX_PATH

@asynccontextmanager
async def lifespan(_app):
    # The first Azure sign-in check takes several seconds, so do it in the background at start-up.
    asyncio.create_task(asyncio.to_thread(llm.status))
    yield


app = FastAPI(title="Foundry Account Intelligence Demo", lifespan=lifespan)
APPROVALS = []


def sse(generator):
    async def stream():
        workbook.pin(workbook.current())  # this stream keeps the workbook it started with
        try:
            async for event in generator:
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)[:300]})}\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/status")
def get_status(refresh: bool = False):
    s = llm.status(force=refresh)
    return {
        **s, "live_available": bool(s["configured"] and s["auth_ok"]), "models": MODELS, "bakeoff_models": BAKEOFF_MODELS,
        "tiers": MODEL_TIERS, "prices": {k: {"in": v[0], "out": v[1]} for k, v in PRICES.items()},
        "recordings": {n: (RECORDINGS / f"{n}.json").exists() for n in ("trust_lab", "bakeoff")}, "quality_bar": QUALITY_BAR,
        "source": workbook.current().info(),
    }


@app.get("/api/workbook")
def get_workbook():
    return {**workbook.summary(), "prompts": workbook.demo_prompts()}


@app.get("/api/workbook/ingest")
def get_ingest_report():
    ds = workbook.current()
    return {"source": ds.info(), "report": ds.report}


@app.post("/api/workbook/upload")
async def upload_workbook(request: Request, x_filename: str = Header("workbook.xlsx")):
    """Takes the raw .xlsx bytes as the request body. The file is parsed in memory and never written to disk."""
    too_big = {"errors": [f"The file is larger than {workbook.MAX_UPLOAD_BYTES // 1024 // 1024} MB."], "report": None}
    if int(request.headers.get("content-length") or 0) > workbook.MAX_UPLOAD_BYTES:
        return JSONResponse(status_code=413, content=too_big)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > workbook.MAX_UPLOAD_BYTES:
            return JSONResponse(status_code=413, content=too_big)
        chunks.append(chunk)
    try:
        ds = workbook.parse_workbook(b"".join(chunks), unquote(x_filename))
    except workbook.UploadError as exc:
        return JSONResponse(status_code=400, content={"errors": exc.errors, "report": exc.report})
    workbook.activate(ds)
    return {"source": ds.info(), "report": ds.report}


@app.post("/api/workbook/reset")
def reset_workbook():
    workbook.activate(workbook.sample())
    ds = workbook.current()
    return {"source": ds.info(), "report": ds.report}


@app.get("/api/workbook/template")
def download_template():
    return FileResponse(XLSX_PATH, filename=workbook.SAMPLE_NAME,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/signals")
def get_signals():
    return [{k: v for k, v in c.items() if k != "events"} | {"event_count": len(c["events"])} for c in signals.compare()]


@app.get("/api/feed")
def get_feed():
    """Where the monitoring data comes from, how fresh it is and how the workbook prices compare with real closes."""
    check = signals.baseline_check()
    return {"status": feed.status(), "coverage": signals.coverage(), "events": len(signals.feed()),
            "baseline": {"checked": len(check), "matching": sum(1 for c in check if c["matches"]), "differences": [c for c in check if not c["matches"]]}}


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    context: list[str] = []
    mode: str = "offline"
    references: list[str] = Field(default_factory=list, max_length=12)


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    return sse(chat.chat_events(req.message, req.history, req.context, req.mode, req.references))


@app.get("/api/chat/peers")
def chat_peers(ticker: str):
    """A company and its sector peers for the clickable peer explorer in the chat."""
    panel = chat.peer_panel(ticker.strip()[:12])
    if not panel:
        return JSONResponse({"error": f"Unknown ticker {ticker}."}, status_code=404)
    return panel


@app.get("/api/chat/suggestions")
def chat_suggestions():
    ds = workbook.current()
    return {"suggestions": chat.suggestions(), "source": ds.info(), "briefings": store.tickers(),
            "events": len(signals.feed()), "sectors": len({r["sector"] for r in ds.rows}), "tools": len(chat.TOOL_SPECS), "companies": chat.company_list(),
            "reports": sum(1 for d in reports.documents() if d["available"] and reports.doc_for(d["ticker"]))}


def _tickers(param):
    return [t.strip()[:12] for t in (param or "").split(",") if t.strip()][:salesplan.MAX_ACCOUNTS]


@app.get("/api/plan")
def get_plan(tickers: str = "", days: int = salesplan.DEFAULT_DAYS):
    """The Cowork shortlist with evidence, hypothesis checks, Microsoft plays, priorities and seller days."""
    return {**salesplan.overview(_tickers(tickers), days), "suggestions": salesplan.suggestions(_tickers(tickers))}


@app.get("/api/plan/competitors")
def get_plan_competitors(ticker: str):
    res = salesplan.competitors(ticker.strip()[:12])
    return JSONResponse(res, status_code=404) if "error" in res else res


@app.get("/api/plan/talk")
def get_plan_talk(ticker: str, play: str | None = None):
    res = salesplan.talk_track(ticker.strip()[:12], play)
    return JSONResponse(res, status_code=404) if "error" in res else res


class PlanChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    mode: str = "offline"
    focus: str | None = None
    tickers: list[str] = Field(default_factory=list, max_length=salesplan.MAX_ACCOUNTS)
    days: int = salesplan.DEFAULT_DAYS


@app.post("/api/plan/chat/stream")
def plan_chat_stream(req: PlanChatRequest):
    return sse(salesplan.plan_events(req.message, req.history, req.mode, req.focus, req.tickers, req.days))


@app.get("/api/reports")
def get_reports():
    """The public reports, their verified headline figures and how the search works."""
    return {"documents": reports.overview(), "status": reports.status(), "prices_date": workbook.current().snapshot_str, "source": workbook.current().info()}


@app.get("/api/reports/search")
def search_reports(q: str, ticker: str | None = None, mode: str = "offline"):
    """Passages from the reports that match a question. Live mode adds embeddings; offline mode uses keywords only."""
    q = q.strip()[:300]
    if not q:
        return JSONResponse({"error": "Type a question."}, status_code=422)
    if ticker and not any(d["ticker"] == ticker for d in reports.documents()):
        return JSONResponse({"error": f"No report for {ticker}."}, status_code=404)
    reports.use_semantic(mode == "live" and llm.live_available())
    passages, how = reports.search(q, ticker, 5)
    return {"question": q, "search": how, "passages": [{**p, "url": f"/api/reports/{p['ticker']}/file#page={p['page']}"} for p in passages]}


@app.get("/api/reports/{ticker}/file")
def report_file(ticker: str):
    doc = next((d for d in reports.documents() if d["ticker"] == ticker and d["available"]), None)
    if not doc:
        return JSONResponse({"error": "No such report."}, status_code=404)
    filename = doc["file"]
    return FileResponse(reports.DIR / filename, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"', "Cache-Control": "no-cache"})


@app.get("/api/logos")
def get_logos():
    """Tickers of the loaded workbook that have a downloaded logo. The others show their initials."""
    return {"tickers": logos.available(), "status": logos.status()}


@app.get("/api/logos/{ticker}")
def logo_file(ticker: str):
    entry = logos.entry_for(ticker)
    path = logos.file_for(entry) if entry else None
    if not path:
        return JSONResponse({"error": "No logo for this company."}, status_code=404)
    # An SVG opened on its own must not run scripts on the app's origin.
    return FileResponse(path, media_type=logos.TYPES[path.suffix], headers={"Cache-Control": "max-age=86400", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'", "X-Content-Type-Options": "nosniff"})


@app.get("/api/trustlab/cases")
def trustlab_cases():
    return {"cases": [{k: c[k] for k in ("id", "category", "prompt", "criterion")} for c in evals.load_cases()], "configs": evals.CONFIGS}


@app.get("/api/monitor/stream")
def monitor_stream(mode: str = "offline", focus: str | None = None):
    return sse(agents.run_cycle(mode, focus))


@app.get("/api/autorun")
def get_autorun():
    """The account run: schedule, the run in progress, run history, the agents and where results go."""
    return autorun.status()


class AutorunRequest(BaseModel):
    mode: str = "offline"


@app.post("/api/autorun/run")
def start_autorun(req: AutorunRequest):
    run, started = autorun.start(req.mode, "manual", "You")
    return {"run": run.summary(), "started": started}


@app.get("/api/autorun/stream")
def autorun_stream(run: str):
    return sse(autorun.follow(run.strip()[:20]))


class ScheduleRequest(BaseModel):
    enabled: bool
    cadence: str = "demo"
    mode: str = "offline"


@app.post("/api/autorun/schedule")
def set_autorun_schedule(req: ScheduleRequest):
    return autorun.set_schedule(req.enabled, req.cadence, req.mode)


@app.get("/api/autorun/cases")
def get_autorun_cases():
    return autorun.case_file()


@app.get("/api/trustlab/stream")
def trustlab_stream(mode: str = "offline"):
    return sse(evals.trust_lab_events(mode))


@app.get("/api/bakeoff/stream")
def bakeoff_stream(mode: str = "offline"):
    return sse(bakeoff.bakeoff_events(mode))


class Approval(BaseModel):
    briefing_id: str
    decision: str
    company: str = ""
    owner_team: str = ""


@app.post("/api/approvals")
def post_approval(a: Approval):
    record = {**a.model_dump(), "at": datetime.now().strftime("%d.%m.%Y %H:%M")}
    APPROVALS.append(record)
    return record


@app.get("/api/approvals")
def list_approvals():
    return APPROVALS


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


class FreshStaticFiles(StaticFiles):
    """Static files that the browser re-checks on every load, so an edited page is never shown stale."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", FreshStaticFiles(directory=STATIC), name="static")

