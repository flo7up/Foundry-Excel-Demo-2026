"""Records one live Trust Lab and Bake-off run so the demo can replay realistic results offline.

Usage (requires `az login` and FOUNDRY_ENDPOINT in .env):
    python -m app.record              # both
    python -m app.record trust_lab    # only the Trust Lab
    python -m app.record bakeoff      # only the Model Bake-off
"""
import asyncio
import json
from datetime import datetime

from . import bakeoff, evals, llm
from .config import RECORDINGS


async def capture(name, generator):
    events = [e async for e in generator]
    RECORDINGS.mkdir(exist_ok=True)
    payload = {"recorded_at": datetime.now().strftime("%d.%m.%Y %H:%M"), "events": events}
    (RECORDINGS / f"{name}.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"saved {name}: {len(events)} events")


async def main(only=None):
    if not llm.live_available():
        raise SystemExit("Live access is not available. Run `az login` and set FOUNDRY_ENDPOINT in .env.")
    if only in (None, "trust_lab"):
        await capture("trust_lab", evals.live_events())
    if only in (None, "bakeoff"):
        await capture("bakeoff", bakeoff.live_events())


if __name__ == "__main__":
    import sys

    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
