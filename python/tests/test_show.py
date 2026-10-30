"""`spatialscape.show()`: an in-memory object builds once into the cache, the session server answers, and a
selection posted the way the viewer does comes back as rows of the object."""
from __future__ import annotations

import base64
import json
import urllib.request

import anndata as ad
import numpy as np
import pytest
import zarr

import spatialscape
from spatialscape.synthetic import make_synthetic


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    yield tmp_path / "cache" / "spatialscape" / "show"
    spatialscape.stop()


def _post(api: str, key: str, samples: dict) -> None:
    req = urllib.request.Request(f"{api}/selection", data=json.dumps({"dataset": key, "version": 1, "samples": samples}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 204


def _get(url: str):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read()


def test_show_anndata_builds_once_and_maps_selection(tmp_path, cache):
    make_synthetic(tmp_path / "src", n_cells=150, n_genes=8)
    adata = ad.read_h5ad(tmp_path / "src" / "sampleA.h5ad")
    logs: list[str] = []
    s = spatialscape.show(adata, color="cluster", log=logs.append)
    assert s.url.startswith("http://127.0.0.1:") and "?d=" in s.url and "built in" in logs[-1]
    assert s.bundle == cache / s.key and (s.bundle / "manifest.json").exists()
    manifest = json.loads(_get(f"{s.url.split('?')[0]}{s.key}/manifest.json")[1])
    # `cluster` is mapped by init's heuristics onto the shared `domain` field, and that is what is colored by
    assert manifest["id"] == s.key and manifest["samples"][0]["kind"] == "spatial" and manifest["defaultColor"] == {"kind": "field", "field": "domain"}
    assert _get(f"{s.api}/ping")[1] == b'{"session": true}'
    assert "<iframe" in s._repr_html_()
    # nothing selected yet
    assert len(s.selection()) == 0 and not s.selection(as_mask=True).any()
    # the viewer posts bundle-order indices; they come back as the object's obs names
    order = np.asarray(zarr.open_group(str(s.bundle / "samples" / "all" / "obs.zarr"), mode="r")["order"][:])
    _post(s.api, s.key, {"all": [0, 1, 5]})
    sel = s.selection()
    assert sorted(sel) == sorted(adata.obs_names[order[[0, 1, 5]]])
    mask = s.selection(as_mask=True)
    assert mask.sum() == 3 and list(adata.obs_names[mask]) == list(sel)
    # the same object again: no rebuild, same server
    logs.clear()
    s2 = spatialscape.show(adata, color="cluster", log=logs.append)
    assert s2.bundle == s.bundle and s2.url == s.url and "cached" in logs[-1]
    # an edited object is new data
    adata2 = adata.copy()
    adata2.obs["cluster"] = adata2.obs["cluster"].astype(str).replace({"Astro": "Glia"})
    s3 = spatialscape.show(adata2, color="cluster", log=logs.append)
    assert s3.key != s.key


def test_show_splits_by_a_sample_column_and_picks_an_embedding(tmp_path, cache):
    make_synthetic(tmp_path / "src", n_cells=120, n_genes=6)
    a = ad.read_h5ad(tmp_path / "src" / "sampleA.h5ad")
    b = ad.read_h5ad(tmp_path / "src" / "sampleB.h5ad")
    adata = ad.concat([a, b], label="donor", keys=["d1", "d2"], index_unique="-")
    del adata.obsm["spatial"]  # only the UMAP is left: an embedding dataset
    s = spatialscape.show(adata, sample="donor", log=lambda *_: None)
    manifest = json.loads((s.bundle / "manifest.json").read_text())
    assert [x["id"] for x in manifest["samples"]] == ["d1", "d2"] and manifest["samples"][0]["kind"] == "embedding"
    order = np.asarray(zarr.open_group(str(s.bundle / "samples" / "d2" / "obs.zarr"), mode="r")["order"][:])
    _post(s.api, s.key, {"d2": [0, 2]})
    sel = s.selection()
    d2_rows = np.flatnonzero(adata.obs["donor"].to_numpy() == "d2")
    assert sorted(sel) == sorted(adata.obs_names[d2_rows[order[[0, 2]]]])


def test_show_a_file_builds_from_a_menu(tmp_path, cache):
    make_synthetic(tmp_path / "src", n_cells=80, n_genes=5)
    path = tmp_path / "src" / "sampleA.h5ad"
    logs: list[str] = []
    s = spatialscape.show(path, log=logs.append)
    assert (s.bundle / "manifest.json").exists() and s.adata is None and "built" in logs[-1]
    _post(s.api, s.key, {json.loads((s.bundle / "manifest.json").read_text())["samples"][0]["id"]: [3]})
    (name,) = s.selection()
    assert name in set(ad.read_h5ad(path).obs_names)
    logs.clear()
    spatialscape.show(path, log=logs.append)
    assert "cached" in logs[-1]


def test_build_lock_waits_for_the_other_builder_and_clears_stale_locks(tmp_path):
    import threading
    import time

    from spatialscape.session import _build_lock

    out = tmp_path / "bundle"
    order: list[str] = []
    logs: list[str] = []

    def first():
        with _build_lock(out, logs.append):
            order.append("first-in")
            time.sleep(0.8)
            order.append("first-out")

    t = threading.Thread(target=first)
    t.start()
    time.sleep(0.2)
    with _build_lock(out, logs.append) as waited:
        order.append("second-in")
    t.join()
    assert order == ["first-in", "first-out", "second-in"] and waited and any("waiting" in m for m in logs)
    # a lock left by a process that no longer exists does not block
    lock = out.with_name("bundle.lock")
    lock.write_text("999999999")
    with _build_lock(out, logs.append) as waited:
        assert not waited
    assert not lock.exists()


def test_regions_come_back_as_a_series(tmp_path, cache):
    """The viewer posts region codes per sample (uint16 in bundle order, base64); regions() maps them to obs names."""
    make_synthetic(tmp_path / "src", n_cells=90, n_genes=5)
    adata = ad.read_h5ad(tmp_path / "src" / "sampleA.h5ad")
    s = spatialscape.show(adata, log=lambda *_: None)
    order = np.asarray(zarr.open_group(str(s.bundle / "samples" / "all" / "obs.zarr"), mode="r")["order"][:])
    codes = np.full(adata.n_obs, 2, dtype="<u2")  # 2 groups -> code 2 is "unassigned"
    codes[[0, 1]] = 0
    codes[[5]] = 1
    body = {"dataset": s.key, "version": 1, "groups": [{"name": "CeA", "color": "#111111"}, {"name": "BLA", "color": "#222222"}], "codes": {"all": base64.b64encode(codes.tobytes()).decode()}}
    req = urllib.request.Request(f"{s.api}/regions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 204
    reg = s.regions()
    assert reg.name == "region" and reg.notna().sum() == 3
    assert set(reg[adata.obs_names[order[[0, 1]]]]) == {"CeA"} and reg[adata.obs_names[order[5]]] == "BLA"
    # nothing drawn: an all-None series, not an error
    assert spatialscape.show(ad.read_h5ad(tmp_path / "src" / "sampleB.h5ad"), log=lambda *_: None).regions().notna().sum() == 0


def test_regions_drawing_saves_loads_and_preloads(tmp_path, cache):
    """The session holds the drawing: save_regions writes it, load_regions / show(regions=) hand it back."""
    make_synthetic(tmp_path / "src", n_cells=50, n_genes=4)
    adata = ad.read_h5ad(tmp_path / "src" / "sampleA.h5ad")
    s = spatialscape.show(adata, log=lambda *_: None)
    drawing = [{"name": "CeA", "color": "#111111", "polygons": [{"sample": "all", "view": "spatial", "local": [[0, 0], [10, 0], [10, 10]]}]}]
    body = {"dataset": s.key, "version": 3, "groups": drawing, "codes": {}}
    req = urllib.request.Request(f"{s.api}/regions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 204
    out = s.save_regions(tmp_path / "drawing.json")
    saved = json.loads(out.read_text())
    assert saved["groups"][0]["polygons"][0]["local"] == [[0, 0], [10, 0], [10, 10]]
    # a fresh session for the same object: nothing drawn until the file is loaded
    spatialscape.stop()
    s2 = spatialscape.show(adata, log=lambda *_: None)
    assert s2.raw_regions()["groups"] == []
    assert s2.load_regions(out) == 1 and s2.raw_regions()["groups"][0]["name"] == "CeA"
    spatialscape.stop()
    logs: list[str] = []
    s3 = spatialscape.show(adata, regions=out, log=logs.append)
    assert s3.raw_regions()["groups"][0]["name"] == "CeA" and any("1 area" in m for m in logs)
    with pytest.raises(ValueError, match="not a regions file"):
        (tmp_path / "bad.json").write_text("[]")
        s3.load_regions(tmp_path / "bad.json")


def test_show_takes_sample_metadata_and_comparisons_from_the_session(tmp_path, cache):
    import pandas as pd

    make_synthetic(tmp_path / "src", n_cells=120, n_genes=6, comparisons=True)
    parts = [ad.read_h5ad(tmp_path / "src" / f"sample{x}.h5ad") for x in "ABCD"]
    for a, mouse in zip(parts, ["m1", "m2", "m3", "m4"], strict=True):
        a.obs["mouse"] = mouse
    adata = ad.concat(parts, label="section", keys=["A", "B", "C", "D"], index_unique="-")
    adata.obs["condition"] = adata.obs["condition"].astype(str)
    adata.uns["spot_nn_spacing_level0_px"] = parts[0].uns["spot_nn_spacing_level0_px"]  # concat drops uns; the scale rule needs it
    logs: list[str] = []
    s = spatialscape.show(adata, sample="section", meta={"condition": "condition", "mouse": "mouse"}, log=logs.append)
    m = json.loads((s.bundle / "manifest.json").read_text())
    assert [k["id"] for k in m["meta"]] == ["condition", "mouse"] and {x["id"]: x["meta"] for x in m["samples"]}["C"] == {"condition": "stress", "mouse": "m3"}
    # a test run in the session, handed back as data frames
    res = pd.read_csv(tmp_path / "src" / "de" / "stress_vs_control.csv")
    pb = pd.read_csv(tmp_path / "src" / "de" / "pseudobulk.csv")
    s.add_comparison("Stress vs control", res, pb, groups=["control", "stress"], units="log2 mean+1", description="t-test on per-mouse pseudobulk", log=logs.append)
    m = json.loads((s.bundle / "manifest.json").read_text())
    [c] = m["comparisons"]
    assert c["id"] == "stress_vs_control" and c["split"] == "condition" and c["link"] == "mouse" and c["nReplicates"] == 4 and c["hasPseudobulk"]
    doc = json.loads((s.bundle / "comparisons" / "stress_vs_control" / "comparison.json").read_text())
    assert {r["id"]: r["samples"] for r in doc["replicates"]["all"]} == {"m1": ["A"], "m2": ["B"], "m3": ["C"], "m4": ["D"]}  # replicates found their sections through the meta
    assert any("re-display the session" in line for line in logs)
    # the same comparison again replaces itself; one given at show() time is added after the build
    s.add_comparison("Stress vs control", res, pb, groups=["control", "stress"], log=logs.append)
    assert len(json.loads((s.bundle / "manifest.json").read_text())["comparisons"]) == 1
    s2 = spatialscape.show(adata, sample="section", meta={"condition": "condition", "mouse": "mouse"}, comparisons=[{"name": "Again", "results": res, "groups": ["control", "stress"]}], log=logs.append)
    assert s2.key == s.key and {c["id"] for c in json.loads((s2.bundle / "manifest.json").read_text())["comparisons"]} == {"stress_vs_control", "again"}
    _post(s.api, s.key, {"C": [0, 1]})
    assert len(s.selection()) == 2  # selections still map after comparisons were added


def test_fingerprint_sees_the_columns_of_sparse_values():
    import anndata as ad
    import numpy as np
    import scipy.sparse as sp

    from spatialscape.session import _hash_adata

    data, indptr = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32), np.array([0, 2, 4])
    a = ad.AnnData(sp.csr_matrix((data, np.array([0, 1, 0, 1]), indptr), shape=(2, 2)))
    b = ad.AnnData(sp.csr_matrix((data.copy(), np.array([1, 0, 1, 0]), indptr.copy()), shape=(2, 2)))
    assert _hash_adata(a, {}, obs_columns=[], obsm_key=None, layer="X") != _hash_adata(b, {}, obs_columns=[], obsm_key=None, layer="X")


def test_a_live_owner_keeps_its_lock_however_old(tmp_path):
    import os
    import sys
    import time

    import pytest

    from spatialscape.session import _build_lock

    if sys.platform == "win32":
        pytest.skip("liveness is not asked on Windows")
    out = tmp_path / "bundle"
    out.mkdir()
    lock = out.with_name(out.name + ".lock")
    lock.write_text(str(os.getpid()))  # a live owner: this process
    old = time.time() - 10_000
    os.utime(lock, (old, old))
    with pytest.raises(TimeoutError), _build_lock(out, lambda *_: None, timeout=0.3):
        pass
    assert lock.exists() and lock.read_text() == str(os.getpid())
