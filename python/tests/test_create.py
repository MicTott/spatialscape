"""The Create page's backend: browsing the server's paths, inspecting data into a menu, rendering choices to the
yaml, building in a job, and the HTTP dispatch with its error codes."""

import json
import time
from pathlib import Path

import pytest

from spatialscape.create import CreateService, handle, login_node_guard

FIX = Path(__file__).parent / "fixtures"


def test_browse_lists_kinds(tmp_path):
    svc = CreateService(tmp_path)
    d = svc.browse(str(FIX))
    kinds = {e["name"]: e["kind"] for e in d["entries"]}
    assert kinds["tiny_seurat_visium.rds"] == "object" and kinds["tiny_sdata_v3.zarr"] == "store" and kinds["make_tiny_seurat_visium.R"] == "file"
    assert d["parent"] == str(FIX.parent) and {r["name"] for r in d["roots"]} >= {"project", "home"}
    assert not any(e["name"].startswith(".") for e in d["entries"])
    with pytest.raises(FileNotFoundError):
        svc.browse(str(tmp_path / "nope"))


def test_inspect_render_and_choices(tmp_path, small_adata):
    src = tmp_path / "data" / "sample.h5ad"
    src.parent.mkdir()
    small_adata.write_h5ad(src)
    svc = CreateService(tmp_path / "proj")
    r = svc.inspect([str(src)], platform=None, table=None, dataset_id=None, name=None)
    assert r["token"] and r["id"] == "sample" and r["entries"][0]["n_obs"] == small_adata.n_obs
    cols = {c["column"]: c for c in r["entries"][0]["columns"]}
    assert cols and any(c["on"] for c in cols.values())
    assert "samples:" in r["yaml"] and r["yaml_path"].endswith("sample.yaml")
    # choices: a new id and name, every column on, one renamed, a display name
    first = next(iter(cols))
    choices = {"id": "my_set", "name": "My set", "names": {"thing": "The thing"}, "entries": {"0": {"columns": [{"column": c, "id": "thing" if c == first else cols[c]["id"], "on": True} for c in cols]}}}
    out = svc.render(r["token"], choices)
    assert out["id"] == "my_set" and "name: My set" in out["yaml"] and "name: The thing" in out["yaml"]
    assert f"thing: {first}" in out["yaml"]
    # a bad id is refused before anything is written
    with pytest.raises(ValueError):
        svc.render(r["token"], {"id": "../x", "entries": {}})
    with pytest.raises(KeyError):
        svc.render("stale", {})


def test_build_job_writes_yaml_and_bundle(tmp_path, small_adata, monkeypatch):
    monkeypatch.setenv("SPATIALSCAPE_ALLOW_LOGIN_NODE", "1")
    src = tmp_path / "data" / "sample.h5ad"
    src.parent.mkdir()
    small_adata.write_h5ad(src)
    proj = tmp_path / "proj"
    svc = CreateService(proj)
    r = svc.inspect([str(src)], platform="visium", table=None, dataset_id=None, name=None)
    j = svc.build(r["token"], {"id": "built", "name": "Built", "entries": {}})
    assert (proj / "built.yaml").exists()
    for _ in range(600):
        st = svc.job(j["job"], 0)
        if st["status"] != "running":
            break
        time.sleep(0.1)
    assert st["status"] == "done", st
    assert (proj / "bundles" / "built" / "manifest.json").exists()
    assert any("built" in line for line in st["lines"])
    # incremental: the log is fetched from an offset
    tail = svc.job(j["job"], st["next"] - 1)
    assert len(tail["lines"]) == 1 and tail["next"] == st["next"]
    m = json.loads((proj / "bundles" / "built" / "manifest.json").read_text())
    assert m["id"] == "built"


def test_dispatch_codes(tmp_path, monkeypatch):
    svc = CreateService(tmp_path)
    assert handle(svc, "GET", "ping", {}, None)[0] == 200
    assert handle(svc, "GET", "jobs/none", {}, None)[0] == 404
    assert handle(svc, "GET", "browse", {"path": str(tmp_path / "missing")}, None)[0] == 404
    assert handle(svc, "POST", "inspect", {}, {"paths": []})[0] == 400
    assert handle(svc, "POST", "render", {}, {"token": "x"})[0] == 404
    assert handle(svc, "GET", "nope", {}, None)[0] == 404
    # the login-node guard refuses a build with 403 and says why
    monkeypatch.delenv("SPATIALSCAPE_ALLOW_LOGIN_NODE", raising=False)
    monkeypatch.setattr("spatialscape.create.shutil.which", lambda name: "/usr/bin/sbatch" if name == "sbatch" else None)
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    assert "login node" in (login_node_guard() or "")
    assert svc.ping()["guard"]
    monkeypatch.setenv("SLURM_JOB_ID", "123")
    assert login_node_guard() is None


def test_serve_mounts_the_create_api(tmp_path):
    import threading
    import urllib.request

    from spatialscape.serve import make_server

    (tmp_path / "bundles").mkdir()
    httpd = make_server(tmp_path / "bundles", port=0, create=CreateService(tmp_path))
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        reg = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/datasets.json").read())
        assert reg["create"] == "/_api/create"
        doc = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/_api/create/ping").read())
        assert doc["create"] is True and doc["project"] == str(tmp_path.resolve())
        req = urllib.request.Request(f"http://127.0.0.1:{port}/_api/create/inspect", data=b'{"paths": []}', headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req)
        assert ei.value.code == 400
        # another web page's origin is refused
        req = urllib.request.Request(f"http://127.0.0.1:{port}/_api/create/ping", headers={"Origin": "https://evil.example"})
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req)
        assert ei.value.code == 403
    finally:
        httpd.shutdown()
