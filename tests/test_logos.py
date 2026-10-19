"""Company logos: downloaded once per machine, only real images of a usable size are kept, and every company without one gets its initials."""
import struct

import pytest
from fastapi.testclient import TestClient

from app import logos, workbook
from app.main import app


def png(width):
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, width) + b"\x08\x06\x00\x00\x00" + b"\x00" * 120


@pytest.fixture
def logo_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "DIR", tmp_path)
    return tmp_path


def test_every_workbook_company_has_a_logo_entry_that_matches_its_name():
    for r in workbook.sample().rows:
        e = next((c for c in logos.companies() if r["ticker"] in c["tickers"]), None)
        assert e and e["match"].lower() in r["company"].lower() and "." in e["domain"], r["ticker"]


def test_fetch_keeps_images_skips_tiny_icons_and_web_pages_and_survives_a_dead_link(logo_dir, monkeypatch):
    src = logo_dir / "src"
    src.mkdir()
    (src / "big.png").write_bytes(png(128))
    (src / "tiny.png").write_bytes(png(16))
    (src / "page.html").write_bytes(b"<html>" + b"x" * 200)
    entries = [
        {"tickers": ["AAA"], "match": "A", "domain": "a.example", "url": (src / "big.png").as_uri()},
        {"tickers": ["BBB"], "match": "B", "domain": "b.example"},
        {"tickers": ["CCC"], "match": "C", "domain": "c.example", "url": (src / "missing.png").as_uri()},
    ]
    # B tries the sources in turn: a web page, a blurred 16 pixel icon, then a usable one.
    for name in ("page.html", "tiny.png", "big.png"):
        (src / f"b.example-{name}").write_bytes((src / name).read_bytes())
    sources = [src.as_uri() + "/{domain}-" + name for name in ("page.html", "tiny.png", "big.png")]
    monkeypatch.setattr(logos, "manifest", lambda: {"sources": sources, "companies": entries})

    out = logos.fetch()

    assert out == {"AAA": "downloaded", "BBB": "downloaded", "CCC": "no logo found; the initials are shown instead"}
    assert (logo_dir / "a.example.png").read_bytes() == png(128) and (logo_dir / "b.example.png").read_bytes() == png(128)
    assert logos.fetch()["AAA"] == "present"


def test_a_logo_is_served_only_for_a_matching_company_and_cannot_run_scripts(logo_dir):
    (logo_dir / "ubs.com.png").write_bytes(png(64))
    client = TestClient(app)
    r = client.get("/api/logos/UBSG")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and "default-src 'none'" in r.headers["content-security-policy"]
    assert client.get("/api/logos/NOVN").status_code == 404, "no file downloaded for Novartis"
    assert client.get("/api/logos/ZZZZ").status_code == 404
    assert client.get("/api/logos").json()["tickers"] == ["UBSG"]


def test_a_foreign_company_with_our_ticker_does_not_get_our_logo(logo_dir, monkeypatch):
    (logo_dir / "ubs.com.png").write_bytes(png(64))
    monkeypatch.setattr(workbook, "by_ticker", lambda t: {"ticker": "UBSG", "company": "Unrelated Bakery Ltd"})
    assert logos.entry_for("UBSG") is None


def test_share_classes_share_one_logo(logo_dir):
    (logo_dir / "roche.com.png").write_bytes(png(64))
    assert logos.entry_for("RO") is logos.entry_for("ROP") and logos.file_for(logos.entry_for("ROP"))
