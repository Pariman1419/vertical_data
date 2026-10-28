import hashlib
import json
import pathlib
import re

from fastapi.testclient import TestClient

from backend.v2.app import app

ROOT = pathlib.Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor" / "tanstack"


def test_manifest_hashes_match_files():
    manifest = json.loads((VENDOR / "MANIFEST.json").read_text())
    files = {p.relative_to(VENDOR).as_posix() for p in VENDOR.rglob("*") if p.is_file()}
    assert files - {"MANIFEST.json"} == set(manifest)
    for name, meta in manifest.items():
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == meta["sha256"]
        assert meta["package"] and meta["version"]


def test_every_vendored_file_is_served_and_only_those():
    client = TestClient(app, base_url="https://testserver")
    manifest = json.loads((VENDOR / "MANIFEST.json").read_text())
    for name in manifest:
        r = client.get("/vendor/tanstack/" + name)
        assert r.status_code == 200
        if name.endswith((".js", ".mjs")):
            assert "javascript" in r.headers["content-type"]
    assert client.get("/vendor/tanstack/not-listed.js").status_code == 404
    assert client.get("/vendor/tanstack/../MANIFEST.json").status_code == 404


def test_no_external_urls_in_html():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert not re.search(r'<script[^>]+src=["\']https?://', html, re.I)
