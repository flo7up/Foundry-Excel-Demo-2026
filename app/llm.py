import asyncio
import time

from .config import ENDPOINT, cost_usd

_state = {"client": None, "provider": None, "status": None, "checked": 0.0}
# Models that refuse function tools together with a reasoning effort; learned from the first rejection.
_tools_need_no_effort = set()


def _provider():
    if _state["provider"] is None:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        _state["provider"] = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
    return _state["provider"]


def _client():
    if _state["client"] is None:
        from openai import OpenAI

        _state["client"] = OpenAI(base_url=ENDPOINT, api_key=_provider(), timeout=90, max_retries=2)
    return _state["client"]


def status(force=False):
    """Reports whether live calls can be made; cached for a minute to keep the UI snappy."""
    if not force and _state["status"] and time.time() - _state["checked"] < 60:
        return _state["status"]
    info = {"configured": bool(ENDPOINT), "endpoint": ENDPOINT.split("//")[-1].split("/")[0] if ENDPOINT else None,
            "auth_ok": False, "error": None}
    if ENDPOINT:
        try:
            _provider()()
            info["auth_ok"] = True
        except Exception as exc:  # noqa: BLE001
            info["error"] = str(exc).splitlines()[0][:200]
    _state["status"], _state["checked"] = info, time.time()
    return info


def live_available():
    s = status()
    return bool(s["configured"] and s["auth_ok"])


async def chat(model, messages, *, tools=None, json_mode=False, effort="low", max_tokens=4000):
    """One chat-completions call against the Foundry deployment. Returns content, tool calls, usage and timing."""
    kwargs = {"model": model, "messages": messages, "max_completion_tokens": max_tokens, "reasoning_effort": effort}
    if tools:
        kwargs["tools"] = tools
        if model in _tools_need_no_effort:
            kwargs["reasoning_effort"] = "none"
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    started = time.perf_counter()
    try:
        resp = await asyncio.to_thread(_client().chat.completions.create, **kwargs)
    except Exception as exc:  # noqa: BLE001
        if not (tools and kwargs["reasoning_effort"] != "none" and "Function tools with reasoning_effort" in str(exc)):
            raise
        _tools_need_no_effort.add(model)
        kwargs["reasoning_effort"] = "none"
        resp = await asyncio.to_thread(_client().chat.completions.create, **kwargs)
    latency = time.perf_counter() - started
    msg = resp.choices[0].message
    usage = resp.usage
    tin, tout = usage.prompt_tokens, usage.completion_tokens
    return {
        "content": msg.content or "",
        "tool_calls": [
            {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments} for tc in (msg.tool_calls or [])
        ],
        "message": msg,
        "tokens_in": tin,
        "tokens_out": tout,
        "latency": round(latency, 2),
        "cost": cost_usd(model, tin, tout),
        "model": model,
    }


def embed(texts, model=None, dimensions=None, batch=64):
    """Embeddings for a list of texts (blocking; call from a thread in async code). Returns a list of float lists."""
    from .config import EMBED_DIMENSIONS, EMBED_MODEL

    model, dimensions = model or EMBED_MODEL, dimensions or EMBED_DIMENSIONS
    out = []
    for i in range(0, len(texts), batch):
        resp = _client().embeddings.create(model=model, input=texts[i:i + batch], dimensions=dimensions)
        out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
    return out
