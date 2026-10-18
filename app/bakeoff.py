import asyncio
import json
import statistics
import time

from . import agents, llm, workbook
from .config import BAKEOFF_MODELS, BAKEOFF_TICKERS, MODEL_TIERS, MODELS, PRICES, QUALITY_BAR
from .evals import replay_events

BRIEF_SYSTEM = """You are an Account Analyst. Using ONLY the EVIDENCE provided, write a briefing for the responsible account team.
Rules: every fact cites one source id (a workbook row id SEC-xxx or a signal id SIG-xxx); signals are real closing prices and news headlines from public media, so name the publisher and date in the fact text and say in data_gaps that headlines were not checked against company filings;
interpretations belong ONLY in hypotheses; no investment advice or price targets; always state data gaps incl. the snapshot date; never invent figures.
Reply with ONLY JSON: {"headline": str, "signal_summary": str, "facts": [{"text": str, "source": str}] (4-6), "hypotheses": [{"text": str, "confidence": "low|medium", "validate_by": str}] (2-3), "data_gaps": [str], "open_questions": [str], "next_step": str}"""

JUDGE_SYSTEM = """You are a senior reviewer scoring an account briefing against its EVIDENCE. Score each criterion from 1 (poor) to 5 (excellent):
- groundedness: all claims and numbers are supported by the evidence
- separation: facts and hypotheses are clearly separated, hypotheses are hedged
- compliance: no investment advice, no demand claims from share price, data gaps disclosed
- usefulness: clear, specific, actionable for an account team
Reply ONLY with JSON: {"groundedness": int, "separation": int, "compliance": int, "usefulness": int, "comment": "<one short sentence>"}"""


def evidence_for(ticker):
    row = workbook.by_ticker(ticker)
    return {"company": agents.tool_get_company(ticker), "sector": agents.tool_get_sector_context(row["sector"], ticker), "signals": agents.tool_get_signals(ticker)}


async def run_one(model, ticker):
    ev = evidence_for(ticker)
    ev_text = json.dumps(ev)
    r = await llm.chat(model, [{"role": "system", "content": BRIEF_SYSTEM}, {"role": "user", "content": "EVIDENCE:\n" + ev_text}], json_mode=True, max_tokens=5000)
    briefing = agents.normalize_briefing(agents.parse_json(r["content"]))
    if not briefing:
        return {"model": model, "ticker": ticker, "latency": r["latency"], "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
                "cost": r["cost"], "quality": 1.0, "scores": {}, "checks_passed": 0, "checks_total": 6, "comment": "Output was not valid JSON", "headline": ""}
    checks = agents.rule_checks(briefing, ticker, ev_text)
    j = await llm.chat(MODELS["judge"], [{"role": "system", "content": JUDGE_SYSTEM},
                                          {"role": "user", "content": json.dumps({"evidence": ev, "briefing": briefing})}], json_mode=True, max_tokens=1500)
    scores = agents.parse_json(j["content"]) or {}
    nums = [scores[k] for k in ("groundedness", "separation", "compliance", "usefulness") if isinstance(scores.get(k), (int, float))]
    quality = round(statistics.mean(nums), 2) if nums else 1.0
    return {"model": model, "ticker": ticker, "latency": r["latency"], "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
            "cost": r["cost"], "quality": quality, "scores": {k: scores.get(k) for k in ("groundedness", "separation", "compliance", "usefulness")},
            "checks_passed": sum(c["passed"] for c in checks), "checks_total": len(checks), "comment": str(scores.get("comment", "")),
            "headline": briefing["headline"]}


def summarize(results):
    out = []
    for m in BAKEOFF_MODELS:
        rs = [r for r in results if r["model"] == m]
        if not rs:
            continue
        cost = statistics.mean(r["cost"] for r in rs)
        out.append({
            "model": m, "tier": MODEL_TIERS.get(m, ""), "runs": len(rs),
            "avg_latency": round(statistics.mean(r["latency"] for r in rs), 1), "avg_quality": round(statistics.mean(r["quality"] for r in rs), 2),
            "avg_cost": cost, "cost_per_1000": round(cost * 1000, 2),
            "avg_tokens_out": round(statistics.mean(r["tokens_out"] for r in rs)),
            "check_rate": round(sum(r["checks_passed"] for r in rs) / max(1, sum(r["checks_total"] for r in rs)), 2),
        })
    ok = [s for s in out if s["avg_quality"] >= QUALITY_BAR and s["check_rate"] >= 0.8]
    if ok:
        pick = min(ok, key=lambda s: s["avg_cost"])
        reason = f"Cheapest model that clears the quality bar of {QUALITY_BAR:.1f}/5 and passes policy checks."
    else:
        pick = max(out, key=lambda s: s["avg_quality"])
        reason = "No model cleared the quality bar; showing the highest quality."
    return {"models": out, "recommendation": {"model": pick["model"], "reason": reason}, "quality_bar": QUALITY_BAR}


async def live_events():
    workbook.pin_sample()
    t0 = time.perf_counter()
    yield {"type": "bake_start", "models": [{"model": m, "tier": MODEL_TIERS.get(m, ""), "price_in": PRICES.get(m, (0, 0))[0], "price_out": PRICES.get(m, (0, 0))[1]} for m in BAKEOFF_MODELS],
           "tickers": [{"ticker": t, "company": workbook.by_ticker(t)["company"]} for t in BAKEOFF_TICKERS], "quality_bar": QUALITY_BAR}
    queue = asyncio.Queue()

    async def lane(model):
        for t in BAKEOFF_TICKERS:
            try:
                res = await run_one(model, t)
            except Exception as exc:  # noqa: BLE001
                res = {"model": model, "ticker": t, "latency": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0, "quality": 1.0, "scores": {},
                       "checks_passed": 0, "checks_total": 6, "comment": f"Call failed: {type(exc).__name__}", "headline": ""}
            await queue.put(res)

    tasks = [asyncio.create_task(lane(m)) for m in BAKEOFF_MODELS]
    results = []
    for _ in range(len(BAKEOFF_MODELS) * len(BAKEOFF_TICKERS)):
        res = await queue.get()
        results.append(res)
        yield {"type": "bake_result", "result": res, "t": round(time.perf_counter() - t0, 1)}
    await asyncio.gather(*tasks)
    yield {"type": "bake_done", "summary": summarize(results), "t": round(time.perf_counter() - t0, 1)}


async def bakeoff_events(mode):
    if mode == "live" and llm.live_available():
        async for e in live_events():
            yield e
    else:
        async for e in replay_events("bakeoff", 0.5):
            yield e
