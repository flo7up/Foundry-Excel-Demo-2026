"""Company logos: the website icon of each workbook company, shown next to its name.

Logos are trademarks of their owners, so like the report PDFs they are not in the repository. They are downloaded once on this machine
and stored in data/logos. A company without a logo (no download yet, offline, or an uploaded workbook with other companies) shows its initials.

  python -m app.logos fetch       # download the logos listed in manifest.json
  python -m app.logos status
"""
import json
import struct
import sys

from . import workbook
from .config import ROOT

DIR = ROOT / "data" / "logos"
MANIFEST_PATH = DIR / "manifest.json"
MIN_PX = 32  # smaller icons look blurred at badge size, so the next source is tried
TYPES = {".png": "image/png", ".ico": "image/x-icon", ".jpg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}

_cache = {"manifest": None}


def reset_cache():
    _cache["manifest"] = None


def manifest():
    if _cache["manifest"] is None:
        _cache["manifest"] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.exists() else {"sources": [], "companies": []}
    return _cache["manifest"]


def companies():
    return manifest()["companies"]


def _stem(entry):
    return entry["domain"].replace("/", "_")


def file_for(entry):
    """The downloaded logo of a manifest entry, or None."""
    for ext in TYPES:
        path = DIR / f"{_stem(entry)}{ext}"
        if path.exists():
            return path
    return None


def entry_for(ticker):
    """The logo entry of a company in the loaded workbook. The company name must match, so a foreign ticker in an uploaded file does not get our logo."""
    row = workbook.by_ticker(str(ticker))
    if not row:
        return None
    tickers = {row["ticker"], *row.get("share_classes", [])}
    return next((c for c in companies() if tickers & set(c["tickers"]) and c["match"].lower() in row["company"].lower()), None)


def available():
    """Tickers of the loaded workbook that have a downloaded logo, so the page only asks for images that exist."""
    out = []
    for r in workbook.rows():
        e = entry_for(r["ticker"])
        if e and file_for(e):
            out.append(r["ticker"])
    return out


# ----------------------------------------------------------------------------- download

def _kind(data):
    """The file extension for image bytes, or None when the bytes are not an image."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"\x00\x00\x01\x00":
        return ".ico"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    head = data[:400].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return ".svg"
    return None


def _width(data, kind):
    """Pixel width for PNG and ICO (the largest image in the icon), else None when it can't be read cheaply."""
    if kind == ".png" and len(data) >= 24:
        return struct.unpack(">I", data[16:20])[0]
    if kind == ".ico" and len(data) >= 6:
        n = struct.unpack("<H", data[4:6])[0]
        sizes = [data[6 + 16 * i] or 256 for i in range(n) if len(data) >= 6 + 16 * (i + 1)]
        return max(sizes, default=0)
    return None


def _download(url):
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Foundry Excel demo; logo download)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(512 * 1024)


def fetch(force=False):
    """Downloads the missing logos. Each source is tried in turn; a reply is kept only when it is an image of a usable size."""
    DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for entry in companies():
        key = "/".join(entry["tickers"])
        have = file_for(entry)
        if have and not force:
            out[key] = "present"
            continue
        urls = [entry["url"]] if entry.get("url") else [s.format(domain=entry["domain"]) for s in manifest()["sources"]]
        result = "no logo found; the initials are shown instead"
        for url in urls:
            try:
                data = _download(url)
            except Exception:  # noqa: BLE001 - one unreachable site must not stop the others
                continue
            kind = _kind(data)
            width = _width(data, kind) if kind else None
            if not kind or len(data) < 100 or (width is not None and width < MIN_PX):
                continue
            if have:
                have.unlink()
            (DIR / f"{_stem(entry)}{kind}").write_bytes(data)
            result = "downloaded"
            break
        out[key] = result
    return out


def status():
    return {"companies": len(companies()), "downloaded": sum(1 for c in companies() if file_for(c))}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "fetch":
        for key, result in fetch(force="--force" in sys.argv).items():
            print(f"{key:9} {result}")
    print(status())
