import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

XLSX_PATH = ROOT / "data" / "Verkaufszahlen_Demo_SMI_Expanded.xlsx"
FEED_PATH = ROOT / "data" / "feed" / "market_feed.json"
EVAL_CASES_PATH = ROOT / "data" / "eval_cases.json"
RECORDINGS = Path(__file__).resolve().parent / "recordings"
STATIC = Path(__file__).resolve().parent / "static"

# Foundry resource OpenAI-compatible endpoint. Authentication uses Microsoft Entra ID
# (az login / DefaultAzureCredential); no API key is stored anywhere.
ENDPOINT = os.getenv("FOUNDRY_ENDPOINT", "").strip()

MODELS = {
    "steward": os.getenv("MODEL_STEWARD", "gpt-6-luna"),
    "scout": os.getenv("MODEL_SCOUT", "gpt-6-luna"),
    "analyst": os.getenv("MODEL_ANALYST", "gpt-6-luna"),
    "reviewer": os.getenv("MODEL_REVIEWER", "gpt-5.5"),
    "judge": os.getenv("MODEL_JUDGE", "gpt-5.5"),
    "assistant": os.getenv("MODEL_ASSISTANT", "gpt-6-luna"),
    "extractor": os.getenv("MODEL_EXTRACTOR", "gpt-6-luna"),
}

# Embedding deployment used to search the public reports. 768 dimensions keep the index small.
EMBED_MODEL = os.getenv("MODEL_EMBEDDINGS", "text-embedding-3-large")
EMBED_DIMENSIONS = int(os.getenv("EMBED_DIMENSIONS", "768"))

BAKEOFF_MODELS = [m.strip() for m in os.getenv("BAKEOFF_MODELS", "gpt-5.5,gpt-6-luna,gpt-5.6-luna").split(",")]
BAKEOFF_TICKERS = ["VACN", "PGHN", "NOVN", "CLN", "ALC"]
QUALITY_BAR = float(os.getenv("QUALITY_BAR", "4.7"))

# USD per 1M tokens (input, output). Azure retail list price, Global Standard, retrieved 2026-10-15.
PRICES = {
    "gpt-5.5": (5.00, 30.00),
    "gpt-6-luna": (0.10, 0.50),
    "gpt-5.6-luna": (0.20, 1.20),
}
MODEL_TIERS = {"gpt-5.5": "Frontier", "gpt-6-luna": "Newest, low cost", "gpt-5.6-luna": "Previous gen, low cost"}


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return (tokens_in * pin + tokens_out * pout) / 1_000_000

