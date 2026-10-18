"""The pre-flight check must be trustworthy: it has to pass on a healthy setup and fail loudly on a broken one."""
import os
import subprocess
import sys

import pytest

from app import preflight
from app.config import ROOT


def run_preflight(*args, env_extra=None):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "FOUNDRY_ENDPOINT": "", **(env_extra or {})}
    return subprocess.run([sys.executable, "-m", "app.preflight", "--url", "http://127.0.0.1:9", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


def test_without_an_endpoint_the_check_passes_with_a_warning_and_names_the_fix():
    r = run_preflight()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FOUNDRY_ENDPOINT is not set" in r.stdout and "READY WITH CAUTION" in r.stdout
    assert "nothing answers at http://127.0.0.1:9" in r.stdout, "a missing app is reported, not crashed on"


def test_the_offline_rehearsal_runs_every_demo_step_and_finds_no_problem(monkeypatch, capsys):
    import asyncio

    from app import agents, chat, workbook

    async def instant(_s=0):
        return None

    monkeypatch.setattr(agents, "pace", instant)
    monkeypatch.setattr(chat.asyncio, "sleep", instant)
    preflight.results.clear()
    asyncio.run(preflight.rehearse(live=False, full=False))
    out = capsys.readouterr().out
    for step in ("Upload", "Reports", "Monitor", "Chat", "Trust Lab", "Bake-off"):
        assert f"Rehearsal: {step}" in out, step
    assert "fail" not in preflight.results and "PROBLEMS" not in out
    assert workbook.current().is_sample

def test_a_failed_sign_in_is_a_failure_with_the_command_to_fix_it(monkeypatch, capsys):
    import azure.identity

    class Broken:
        def get_token(self, *_a, **_k):
            raise RuntimeError("Please run 'az login' to set up an account.")

    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", Broken)
    monkeypatch.setattr(preflight, "ENDPOINT", "https://example.cognitiveservices.azure.com/openai/v1/")
    preflight.results.clear()
    assert preflight.check_signin() is False
    out = capsys.readouterr().out
    assert "FAIL" in out and "az login" in out and preflight.results == ["ok", "fail"]


def test_a_missing_recording_is_a_failure(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "ROOT", ROOT / "nowhere")
    preflight.results.clear()
    preflight.check_files()
    assert "FAIL" in capsys.readouterr().out and "fail" in preflight.results


def test_the_start_script_exposes_the_check_switches():
    text = (ROOT / "start.ps1").read_text(encoding="utf-8")
    for needle in ("[switch]$Check", "[switch]$Rehearse", "[switch]$Full", "app.preflight"):
        assert needle in text




def test_a_figure_that_no_longer_matches_its_pdf_page_is_a_failure(monkeypatch, capsys):
    from app import reports

    if not reports.status()["available"]:
        pytest.skip("no report PDFs on this machine")
    reports.reset_cache()
    monkeypatch.setitem(reports.fin()["companies"]["NOVN"]["items"]["revenue"], "page", 9)
    preflight.results.clear()
    preflight.check_reports()
    out = capsys.readouterr().out
    assert "FAIL" in out and "NOVN revenue" in out and "python -m app.reports extract" in out
    reports.reset_cache()
