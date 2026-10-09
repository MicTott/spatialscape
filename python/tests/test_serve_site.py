"""The one-origin dev server, the generated registry and `site build`."""
from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

import pytest

from spatialscape.build import build_dataset
from spatialscape.config import load_config
from spatialscape.registry import bundle_entry, merge_entry
from spatialscape.serve import make_server
from spatialscape.site import build_site
from spatialscape.synthetic import make_synthetic


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("data")
    cfg = make_synthetic(root / "src", n_cells=60, n_genes=5)
    out = root / "bundles" / "demo"
    build_dataset(load_config(cfg), out, log=lambda *_: None)
    return out


@pytest.fixture
def fake_app(tmp_path) -> Path:
    d = tmp_path / "app"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text('<!doctype html><div id="root"></div><script src="./assets/a.js"></script>')
    (d / "assets" / "a.js").write_text("console.log(1)")
    return d


def _get(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, dict(r.headers), r.read()


def _serve(directory: Path, app_dir: Path | None):
    httpd = make_server(directory, port=0, app_dir=app_dir)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def test_server_serves_viewer_registry_and_ranges(bundle, fake_app):
    httpd, base = _serve(bundle.parent, fake_app)
    try:
        st, h, body = _get(f"{base}/")
        assert st == 200 and b'id="root"' in body
        st, h, body = _get(f"{base}/assets/a.js")
        assert st == 200
        st, h, body = _get(f"{base}/datasets.json")
        reg = json.loads(body)
        assert h["Content-Type"] == "application/json" and h["Access-Control-Allow-Origin"] == "*"
        assert [d["id"] for d in reg["datasets"]] == ["synthetic"]
        assert reg["datasets"][0]["url"] == "demo" and reg["datasets"][0]["samples"] == 3
        st, h, body = _get(f"{base}/demo/manifest.json")
        assert st == 200 and json.loads(body)["id"] == "synthetic"
        st, h, body = _get(f"{base}/demo/samples/sampleA/expr.zarr/u8/c/0/0", {"Range": "bytes=0-15"})
        assert st == 206 and len(body) == 16 and h["Content-Range"].startswith("bytes 0-15/")
        assert "Content-Range" in h["Access-Control-Expose-Headers"]
    finally:
        httpd.shutdown()


def test_server_without_viewer_still_serves_data(bundle, tmp_path, monkeypatch):
    import spatialscape.serve as srv

    monkeypatch.setattr(srv, "packaged_app_dir", lambda: None)
    httpd, base = _serve(bundle.parent, None)
    try:
        st, _, _ = _get(f"{base}/demo/genes.json")
        assert st == 200
        st, _, body = _get(f"{base}/")  # plain folder listing, no viewer
        assert st == 200 and b'id="root"' not in body and b"demo/" in body
    finally:
        httpd.shutdown()


def test_registry_merge_keeps_hand_edits(bundle):
    gen = bundle_entry(bundle, "demo")
    assert gen["platforms"] == ["visium", "snrnaseq"] and gen["genes"] == 5
    merged = merge_entry(gen, {"id": "synthetic", "name": "old name", "paper": {"title": "X et al."}, "tags": ["t"], "status": "coming soon"})
    assert merged["name"] == gen["name"] and merged["paper"]["title"] == "X et al." and merged["tags"] == ["t"]
    assert merged["status"] == "coming soon"  # people's status wins over the generated "live"


def test_site_build_copies_links_or_references(bundle, fake_app, tmp_path):
    site = tmp_path / "site"
    build_site(site, [bundle], app_dir=fake_app, title="Lab data", log=lambda *_: None)
    assert (site / "index.html").exists() and (site / "assets" / "a.js").exists()
    assert (site / "synthetic" / "manifest.json").exists()
    reg = json.loads((site / "datasets.json").read_text())
    assert reg["title"] == "Lab data" and reg["datasets"][0]["url"] == "synthetic"
    # hand edits survive a rebuild
    reg["datasets"][0]["paper"] = {"title": "Someone 2026"}
    reg["datasets"].append({"id": "later", "name": "Later", "description": "", "platforms": [], "samples": 0, "cells": 0, "url": "", "status": "coming soon"})
    (site / "datasets.json").write_text(json.dumps(reg))
    build_site(site, [bundle.parent], app_dir=fake_app, log=lambda *_: None)
    reg2 = json.loads((site / "datasets.json").read_text())
    assert reg2["datasets"][0]["paper"]["title"] == "Someone 2026" and reg2["datasets"][1]["id"] == "later"
    # remote data: nothing copied
    site2 = tmp_path / "site2"
    build_site(site2, [bundle], app_dir=fake_app, data_url="https://data.example.org/", log=lambda *_: None)
    assert not (site2 / "synthetic").exists()
    assert json.loads((site2 / "datasets.json").read_text())["datasets"][0]["url"] == "https://data.example.org/synthetic"
    # linked
    site3 = tmp_path / "site3"
    build_site(site3, [bundle], app_dir=fake_app, link=True, log=lambda *_: None)
    assert (site3 / "synthetic").is_symlink()


def test_site_build_needs_a_viewer(bundle, tmp_path, monkeypatch):
    import spatialscape.site as st

    monkeypatch.setattr(st, "packaged_app_dir", lambda: None)
    with pytest.raises(FileNotFoundError, match="packaged viewer"):
        build_site(tmp_path / "s", [bundle], log=lambda *_: None)
