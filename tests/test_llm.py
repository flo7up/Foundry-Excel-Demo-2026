"""The model client must cope with models that refuse function tools together with a reasoning effort."""
import asyncio
from types import SimpleNamespace

import pytest

from app import llm

REJECTION = ("Error code: 400 - Function tools with reasoning_effort are not supported for gpt-6-luna in /v1/chat/completions. "
             "To use function tools, use /v1/responses or set reasoning_effort to 'none'.")


class FakeCompletions:
    def __init__(self, reject_models=()):
        self.calls = []
        self.reject_models = set(reject_models)

    def create(self, **kw):
        self.calls.append(kw)
        if kw.get("tools") and kw["reasoning_effort"] != "none" and kw["model"] in self.reject_models:
            raise RuntimeError(REJECTION)
        msg = SimpleNamespace(content="OK", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2))


@pytest.fixture
def fake(monkeypatch):
    comp = FakeCompletions(reject_models={"gpt-6-luna"})
    monkeypatch.setattr(llm, "_client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=comp)))
    monkeypatch.setattr(llm, "_tools_need_no_effort", set())
    return comp


TOOLS = [{"type": "function", "function": {"name": "t", "parameters": {"type": "object", "properties": {}}}}]


def call(model, **kw):
    return asyncio.run(llm.chat(model, [{"role": "user", "content": "hi"}], **kw))


def test_a_rejected_tool_call_is_retried_without_reasoning_and_remembered(fake):
    r = call("gpt-6-luna", tools=TOOLS)
    assert r["content"] == "OK" and [c["reasoning_effort"] for c in fake.calls] == ["low", "none"]
    call("gpt-6-luna", tools=TOOLS)
    assert [c["reasoning_effort"] for c in fake.calls][2:] == ["none"], "the second call must not repeat the failed attempt"


def test_other_models_and_calls_without_tools_keep_their_reasoning_effort(fake):
    call("gpt-5.5", tools=TOOLS)
    call("gpt-6-luna")
    call("gpt-6-luna", json_mode=True, effort="medium")
    assert [c["reasoning_effort"] for c in fake.calls] == ["low", "low", "medium"]


def test_other_errors_are_not_swallowed(monkeypatch):
    class Broken:
        def create(self, **_kw):
            raise RuntimeError("Error code: 429 - rate limited")

    monkeypatch.setattr(llm, "_client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=Broken())))
    monkeypatch.setattr(llm, "_tools_need_no_effort", set())
    with pytest.raises(RuntimeError, match="429"):
        call("gpt-6-luna", tools=TOOLS)


def test_the_default_setup_uses_gpt_6_luna_for_the_agents_and_keeps_a_stronger_reviewer():
    from app.config import BAKEOFF_MODELS, MODELS, PRICES

    assert {MODELS[r] for r in ("steward", "scout", "analyst", "assistant")} == {"gpt-6-luna"}
    assert MODELS["reviewer"] == MODELS["judge"] == "gpt-5.5"
    assert len(set(BAKEOFF_MODELS)) == 3 and all(m in PRICES for m in BAKEOFF_MODELS)
    assert not any("5.4" in m for m in (*MODELS.values(), *BAKEOFF_MODELS, *PRICES))
