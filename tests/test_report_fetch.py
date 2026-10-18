"""Downloading the report PDFs on a fresh clone: only the exact files the figures were checked on are kept."""
import hashlib

from app import reports


def test_fetch_keeps_matching_files_rejects_changed_ones_and_survives_a_dead_link(tmp_path, monkeypatch):
    good, changed = b"%PDF-1.7 the checked report", b"%PDF-1.7 a newer version"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "good.pdf").write_bytes(good)
    (tmp_path / "src" / "changed.pdf").write_bytes(changed)
    (tmp_path / "have.pdf").write_bytes(b"already here")
    sha = hashlib.sha256(good).hexdigest()
    docs = [
        {"ticker": "AAA", "file": "a.pdf", "url": (tmp_path / "src" / "good.pdf").as_uri(), "sha256": sha, "bytes": len(good)},
        {"ticker": "BBB", "file": "b.pdf", "url": (tmp_path / "src" / "changed.pdf").as_uri(), "sha256": sha, "bytes": len(good)},
        {"ticker": "CCC", "file": "c.pdf", "url": (tmp_path / "src" / "missing.pdf").as_uri(), "sha256": sha},
        {"ticker": "DDD", "file": "have.pdf", "url": "file:///never-read", "sha256": sha},
    ]
    monkeypatch.setattr(reports, "DIR", tmp_path)
    monkeypatch.setattr(reports, "documents", lambda: docs)

    out = reports.fetch()

    assert out["AAA"] == "downloaded" and (tmp_path / "a.pdf").read_bytes() == good
    assert out["BBB"].startswith("the company now serves a different file") and not (tmp_path / "b.pdf").exists()
    assert out["CCC"].startswith("download failed") and docs[2]["url"] in out["CCC"] and not (tmp_path / "c.pdf").exists()
    assert out["DDD"] == "present" and (tmp_path / "have.pdf").read_bytes() == b"already here"


def test_every_report_in_the_manifest_can_be_verified_after_download():
    for d in reports.documents():
        assert d["url"].startswith("https://") and len(d["sha256"]) == 64 and d["bytes"] > 0, d["ticker"]
