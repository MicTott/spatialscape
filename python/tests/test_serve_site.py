"""The one-origin dev server, the generated registry, `site.yaml` and `site build`."""
from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

import pytest

from spatialscape.build import build_dataset
from spatialscape.config import load_config
from spatialscape.registry import bundle_entry, placeholder_entry
from spatialscape.serve import make_server
from spatialscape.site import build_site, build_site_from_config, load_site_config, write_site_template
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


def test_bundle_and_placeholder_entries(bundle):
    gen = bundle_entry(bundle, "demo")
    assert gen["platforms"] == ["visium", "snrnaseq"] and gen["genes"] == 5 and gen["status"] == "live"
    ph = placeholder_entry("later", "Later", None, ["visium"])
    assert ph == {"id": "later", "name": "Later", "description": "", "platforms": ["visium"], "samples": 0, "cells": 0, "url": "", "status": "coming soon"}


def test_site_build_from_a_folder_copies_links_or_references(bundle, fake_app, tmp_path):
    site = tmp_path / "site"
    build_site(site, [bundle], app_dir=fake_app, log=lambda *_: None)
    assert (site / "index.html").exists() and (site / "assets" / "a.js").exists()
    assert (site / "synthetic" / "manifest.json").exists()
    reg = json.loads((site / "datasets.json").read_text())
    assert reg["title"] == "spatialscape" and reg["datasets"][0]["url"] == "synthetic"
    site2 = tmp_path / "site2"  # remote data: nothing copied
    build_site(site2, [bundle], app_dir=fake_app, data_url="https://data.example.org/", log=lambda *_: None)
    assert not (site2 / "synthetic").exists()
    assert json.loads((site2 / "datasets.json").read_text())["datasets"][0]["url"] == "https://data.example.org/synthetic"
    site3 = tmp_path / "site3"  # linked
    build_site(site3, [bundle], app_dir=fake_app, link=True, log=lambda *_: None)
    assert (site3 / "synthetic").is_symlink()


def test_site_yaml_is_the_one_source_of_the_gallery(bundle, fake_app, tmp_path):
    import yaml

    proj = tmp_path / "proj"
    cfg = make_synthetic(proj / "src", n_cells=40, n_genes=5)
    other = proj / "src" / "other.yaml"  # a second dataset yaml, built by `site build` itself
    doc = yaml.safe_load(cfg.read_text())
    doc["id"], doc["name"] = "other", "Other"
    other.write_text(yaml.safe_dump(doc))
    site_yaml = proj / "site.yaml"
    site_yaml.write_text(
        "title: Lab data\nintro: Two datasets.\n"
        "nav: { title: Our lab, links: [{ label: Lab site, url: https://lab.example.org }] }\n"
        "datasets:\n"
        "  - config: src/other.yaml\n    paper: { title: Someone 2026, url: https://doi.org/x }\n    tags: [demo]\n"
        f"  - bundle: {bundle}\n    description: Hand-written card text.\n"
        "  - id: later\n    name: Later\n    platforms: [visium]\n"
    )
    out = build_site_from_config(site_yaml, app_dir=fake_app, log=lambda *_: None)
    assert out == proj / "site" and (out / "index.html").exists()
    assert (proj / "src" / "bundles" / "other" / "manifest.json").exists()  # built into bundles/<id> next to its yaml
    assert (out / "other" / "manifest.json").exists() and (out / "synthetic" / "manifest.json").exists()
    reg = json.loads((out / "datasets.json").read_text())
    assert reg["title"] == "Lab data" and reg["intro"] == "Two datasets." and reg["site"]["links"][0]["label"] == "Lab site"
    ids = [d["id"] for d in reg["datasets"]]
    assert ids == ["other", "synthetic", "later"]
    assert reg["datasets"][0]["paper"]["title"] == "Someone 2026" and reg["datasets"][0]["tags"] == ["demo"] and reg["datasets"][0]["url"] == "other"
    assert reg["datasets"][1]["description"] == "Hand-written card text." and reg["datasets"][1]["samples"] == 3
    assert reg["datasets"][2] == {"id": "later", "name": "Later", "description": "", "platforms": ["visium"], "samples": 0, "cells": 0, "url": "", "status": "coming soon"}
    # a hand edit to datasets.json does not survive: site.yaml is the source
    reg["datasets"][0]["tags"] = ["edited"]
    (out / "datasets.json").write_text(json.dumps(reg))
    build_site_from_config(site_yaml, app_dir=fake_app, log=lambda *_: None)
    assert json.loads((out / "datasets.json").read_text())["datasets"][0]["tags"] == ["demo"]
    # remote data: viewer + registry only
    site_yaml.write_text("title: T\ndata_url: https://data.example.org\ndatasets:\n" + f"  - bundle: {bundle}\n")
    out2 = build_site_from_config(site_yaml, tmp_path / "remote", app_dir=fake_app, log=lambda *_: None)
    assert not (out2 / "synthetic").exists()
    assert json.loads((out2 / "datasets.json").read_text())["datasets"][0]["url"] == "https://data.example.org/synthetic"


def test_site_yaml_validation_messages(tmp_path):
    p = tmp_path / "site.yaml"
    p.write_text("title: T\ndatasets:\n  - config: a.yaml\n    bundle: b\n")
    with pytest.raises(Exception, match="exactly one of"):
        load_site_config(p)
    p.write_text("title: T\ndatasets:\n  - id: later\n")
    with pytest.raises(Exception, match="set `name:`"):
        load_site_config(p)


def test_site_init_template_loads(bundle, tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=30, n_genes=5)
    out = write_site_template([cfg, bundle], tmp_path / "site.yaml", title="Lab data")
    site = load_site_config(out)
    assert site.title == "Lab data" and [d.config is not None for d in site.datasets] == [True, False]
    assert site.datasets[0].config == cfg.resolve() and site.datasets[1].bundle == bundle.resolve()


def test_site_build_needs_a_viewer(bundle, tmp_path, monkeypatch):
    import spatialscape.site as st

    monkeypatch.setattr(st, "packaged_app_dir", lambda: None)
    with pytest.raises(FileNotFoundError, match="packaged viewer"):
        build_site(tmp_path / "s", [bundle], log=lambda *_: None)


def test_serve_skips_a_busy_default_port(bundle, fake_app, monkeypatch, capsys):
    import threading

    import spatialscape.serve as srv

    busy = make_server(bundle.parent, port=0, app_dir=fake_app)
    port = busy.server_address[1]
    threading.Thread(target=busy.serve_forever, daemon=True).start()
    started = {}

    class _Fake:
        RequestHandlerClass = type("H", (), {"func": type("F", (), {"app_dir": fake_app})})

        def serve_forever(self):
            raise KeyboardInterrupt

    def fake_make_server(directory, port=8787, host="127.0.0.1", app_dir=None):
        started["port"] = port
        return _Fake()

    monkeypatch.setattr(srv, "make_server", fake_make_server)
    try:
        srv.serve(bundle.parent, port=port, open_browser=False, port_chosen=False)
        assert started["port"] == port + 1
        assert f"port {port} is in use; using {port + 1}" in capsys.readouterr().out
        with pytest.raises(OSError, match="already in use"):
            srv.serve(bundle.parent, port=port, open_browser=False, port_chosen=True)
    finally:
        busy.shutdown()
