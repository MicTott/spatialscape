"""Cell boundary shapes: read from a parquet file or obsm, mapped into the sample frame, cut into spatial tiles that
the viewer loads one view at a time, and decoded back exactly."""
import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from spatialscape import shapes as S
from spatialscape.build import build_dataset
from spatialscape.config import load_config
from spatialscape.synthetic import make_synthetic
from spatialscape.validate import validate_local


def _build(cfg_path, out, patch, *, sharded=True):
    doc = yaml.safe_load(cfg_path.read_text())
    doc["samples"] = [s for s in doc["samples"] if s["id"] == "sampleA"]
    patch(doc["samples"][0])
    cfg_path.write_text(yaml.safe_dump(doc))
    logs: list[str] = []
    m = build_dataset(load_config(cfg_path), out, sharded=sharded, log=logs.append)
    return m.samples[0], S.read_shapes(out / "samples/sampleA"), logs


def _same(a: dict, b: dict) -> bool:
    return a.keys() == b.keys() and all(np.allclose(a[k], b[k], atol=1e-9) for k in a)


def test_obsm_polygons_match_parquet_polygons(tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=150, n_genes=5)
    s1, r1, logs1 = _build(cfg, tmp_path / "a", lambda s: None)  # parquet, as generated
    s2, r2, logs = _build(cfg, tmp_path / "b", lambda s: s.update(polygons={"obsm": "segmentations"}))
    assert s1.shapes.cells == s1.nObs == s2.shapes.cells and s1.polygons is None
    assert _same(r1, r2)
    assert any("from obsm/segmentations" in line for line in logs)
    assert any("cell shapes for 150/150 cells" in line for line in logs1)


def test_obsm_polygons_are_auto_detected(tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=120, n_genes=5)
    s, _, logs = _build(cfg, tmp_path / "a", lambda s: s.pop("polygons"))
    assert s.shapes is not None and s.shapes.cells == s.nObs
    assert any("auto polygons: obsm/segmentations" in line for line in logs)


def test_affine_maps_a_transposed_boundary_file_back(tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=150, n_genes=5)
    t = pq.read_table(tmp_path / "src/sampleA.polygons.parquet")
    pq.write_table(
        pa.table({"cell_id": t["cell_id"], "vertex_x": t["vertex_y"], "vertex_y": t["vertex_x"]}),
        tmp_path / "src/transposed.parquet",
    )
    _, r_ref, _ = _build(cfg, tmp_path / "ref", lambda s: None)
    _, r_fixed, logs_fixed = _build(
        cfg,
        tmp_path / "fixed",
        lambda s: s.update(polygons={"path": "transposed.parquet", "affine": [0, 1, 0, 1, 0, 0]}),
    )
    assert _same(r_fixed, r_ref)
    assert not any("warning: polygon centroids" in line for line in logs_fixed)
    _, _, logs_bad = _build(cfg, tmp_path / "bad", lambda s: s.update(polygons={"path": "transposed.parquet"}))
    assert any("warning: polygon centroids" in line for line in logs_bad)


def test_polygon_spec_requires_one_source(tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=50, n_genes=5)
    doc = yaml.safe_load(cfg.read_text())
    doc["samples"][0]["polygons"] = {"path": "sampleA.polygons.parquet", "obsm": "segmentations"}
    cfg.write_text(yaml.safe_dump(doc))
    with pytest.raises(ValueError, match="exactly one"):
        load_config(cfg)


def _rings(n=400, seed=0, spread=3000.0, closed=True, k=8):
    """n jittered k-gons scattered over `spread` um; returns obs ids, cell xy, long-format ids and vertices."""
    rng = np.random.default_rng(seed)
    xy = rng.random((n, 2)) * spread
    ids = [f"c{i}" for i in range(n)]
    ang = np.linspace(0, 2 * np.pi, k, endpoint=False)
    pids, pts = [], []
    for i in range(n):
        r = 4 + rng.random(k) * 3
        ring = xy[i] + np.c_[np.cos(ang) * r, np.sin(ang) * r]
        ring = np.round(ring / 0.2125) * 0.2125  # on a Xenium-like pixel grid
        if closed:
            ring = np.vstack([ring, ring[:1]])
        pids += [ids[i]] * len(ring)
        pts.append(ring)
    return ids, xy, np.array(pids), np.vstack(pts)


def test_tiles_round_trip_every_ring_to_its_own_cell(tmp_path):
    ids, xy, pids, pxy = _rings()
    perm = np.random.default_rng(1).permutation(len(ids))  # bundle rows are shuffled relative to the file
    obs = [ids[i] for i in perm]
    st = S.write_shapes(tmp_path, obs, xy[perm], pids, pxy, max_vertices=24)
    assert st.cells == 400 and st.vertices == 400 * 8 and st.unmatched == 0 and st.centroid_offset < 1.0
    index = json.loads((tmp_path / "shapes.json").read_text())
    assert index["layout"] == "packed" and sum(t[4] for t in index["tiles"]) == 400
    back = S.read_shapes(tmp_path)
    for row, ring in back.items():
        cell = obs[row]
        src = pxy[pids == cell][:-1]  # the closing vertex is not stored
        assert np.abs(ring - src).max() <= S.GRID / 2 + 1e-9
    # every ring sits in the tile of its centroid, and reach covers its vertices
    blob = (tmp_path / "shapes.bin").read_bytes()
    for ix, iy, off, nb, _nr, _nv in index["tiles"]:
        o = (index["origin"][0] + ix * index["tile"], index["origin"][1] + iy * index["tile"])
        rows, counts, v = S.decode_tile(blob[off : off + nb], o, index["grid"])
        assert (np.diff(rows) > 0).all()  # ascending: the viewer gathers colours in row order
        starts = np.cumsum(counts) - counts
        cen = np.add.reduceat(v, starts, axis=0) / counts[:, None]
        assert (np.floor((cen - o) / index["tile"]) == 0).all()
        assert np.hypot(*(v - np.repeat(cen, counts, axis=0)).T).max() <= index["reach"] + 1e-6


def test_long_rings_are_thinned_and_bad_rings_counted(tmp_path):
    ids, xy, pids, pxy = _rings(n=30, k=40)
    pids = np.concatenate([pids, ["ghost"] * 5, ["c0b"] * 2])  # an unknown cell, and a two-vertex ring
    pxy = np.vstack([pxy, np.zeros((5, 2)), np.ones((2, 2))])
    st = S.write_shapes(tmp_path, ids + ["c0b"], np.vstack([xy, [[1, 1]]]), pids, pxy, max_vertices=24)
    assert st.cells == 30 and st.vertices == 30 * 24 and st.unmatched == 1 and st.degenerate == 1


def test_dense_tissue_gets_smaller_tiles(tmp_path):
    ids, xy, pids, pxy = _rings(n=3000, spread=600.0, closed=False)  # about 8k cells per mm2
    st = S.write_shapes(tmp_path, ids, xy, pids, pxy)
    assert st.tile < 1024
    index = json.loads((tmp_path / "shapes.json").read_text())
    assert max(t[4] for t in index["tiles"]) <= S.TILE_TARGET


def test_one_file_per_tile_for_hosts_without_ranges_and_validate(tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=150, n_genes=5)
    _, r1, _ = _build(cfg, tmp_path / "packed", lambda s: None)
    _, r2, _ = _build(cfg, tmp_path / "files", lambda s: None, sharded=False)
    assert _same(r1, r2)
    assert (tmp_path / "files/samples/sampleA/shapes").is_dir() and not (tmp_path / "files/samples/sampleA/shapes.bin").exists()
    for d in ("packed", "files"):
        assert validate_local(tmp_path / d) == []
    blob = tmp_path / "packed/samples/sampleA/shapes.bin"
    blob.write_bytes(blob.read_bytes()[:-3])
    assert any("shape" in p for p in validate_local(tmp_path / "packed"))


def test_every_spatial_sample_carries_the_shapes_recipe(tmp_path):
    from spatialscape.fingerprint import sample_fingerprint
    from spatialscape.shapes import SHAPES_RECIPE

    cfg = load_config(make_synthetic(tmp_path / "src", n_cells=50, n_genes=4))
    by_id = {s.id: s for s in cfg.samples}
    no_poly = by_id["sampleA"].model_copy(update={"polygons": None})  # obsm polygons are only found at build time
    assert sample_fingerprint(no_poly, cfg, sharded=True)["spec"]["shapes_recipe"] == SHAPES_RECIPE
    emb = next(s for s in cfg.samples if s.kind == "embedding")
    assert "shapes_recipe" not in sample_fingerprint(emb, cfg, sharded=True)["spec"]


def test_validate_reports_a_malformed_shape_index(tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=100, n_genes=5)
    _build(cfg, tmp_path / "b", lambda s: None)
    idx = tmp_path / "b/samples/sampleA/shapes.json"
    doc = json.loads(idx.read_text())
    doc["tiles"][0] = doc["tiles"][0][:5]
    idx.write_text(json.dumps(doc))
    problems = validate_local(tmp_path / "b")
    assert any("not a shape tile index" in p for p in problems)


def test_another_segmentation_is_tiled_beside_the_cells_and_compared(tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=200, n_genes=5)
    logs: list[str] = []
    m = build_dataset(load_config(cfg), tmp_path / "b", log=logs.append)
    a = next(s for s in m.samples if s.id == "sampleA")
    [seg] = a.segmentations
    assert seg.id == "nucleus" and seg.name == "Nuclei" and seg.cells == 200 and seg.path == "segmentations/nucleus/shapes"
    assert a.shapes.medianArea and seg.medianArea and seg.medianArea < 0.4 * a.shapes.medianArea  # 55% radius -> 30% area
    rings = S.read_shapes(tmp_path / "b" / "samples" / "sampleA" / "segmentations" / "nucleus")
    assert sorted(rings) == list(range(200))  # numbered rings, not cell rows
    assert next(s for s in m.samples if s.id == "sampleB").segmentations == []
    assert validate_local(tmp_path / "b") == []
    idx = tmp_path / "b/samples/sampleA/segmentations/nucleus/shapes.bin"
    idx.write_bytes(idx.read_bytes()[:-2])
    assert any("nucleus" in p for p in validate_local(tmp_path / "b"))


def test_xenium_nucleus_boundaries_are_found_next_to_the_cell_boundaries(tmp_path):
    from spatialscape.config import PolygonSpec, SampleSpec
    from spatialscape.discover import auto_segmentations

    outs = tmp_path / "outs"
    outs.mkdir()
    (outs / "cell_boundaries.parquet").write_bytes(b"x")
    spec = SampleSpec(id="x", platform="xenium", path=outs / "adata.h5ad", polygons=PolygonSpec(path=outs / "cell_boundaries.parquet"))
    assert auto_segmentations(spec) == []
    (outs / "nucleus_boundaries.parquet").write_bytes(b"x")
    [sg] = auto_segmentations(spec)
    assert sg.id == "nucleus" and sg.path == outs / "nucleus_boundaries.parquet"
    assert auto_segmentations(spec.model_copy(update={"segmentations": []})) == []
