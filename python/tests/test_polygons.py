import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from spatialscape.build import build_dataset
from spatialscape.config import load_config
from spatialscape.polygons import pack_polygons
from spatialscape.synthetic import make_synthetic


def _build(cfg_path, out, patch):
    doc = yaml.safe_load(cfg_path.read_text())
    doc["samples"] = [s for s in doc["samples"] if s["id"] == "sampleA"]
    patch(doc["samples"][0])
    cfg_path.write_text(yaml.safe_dump(doc))
    logs: list[str] = []
    m = build_dataset(load_config(cfg_path), out, log=logs.append)
    return m.samples[0], (out / "samples/sampleA/polygons.i16").read_bytes(), logs


def test_obsm_polygons_match_parquet_polygons(tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=150, n_genes=5)
    s1, b1, _ = _build(cfg, tmp_path / "a", lambda s: None)  # parquet, as generated
    s2, b2, logs = _build(cfg, tmp_path / "b", lambda s: s.update(polygons={"obsm": "segmentations"}))
    assert s1.polygons.cells == s1.nObs == s2.polygons.cells
    assert b1 == b2
    assert any("from obsm/segmentations" in line for line in logs)


def test_obsm_polygons_are_auto_detected(tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=120, n_genes=5)
    s, _, logs = _build(cfg, tmp_path / "a", lambda s: s.pop("polygons"))
    assert s.polygons is not None and s.polygons.cells == s.nObs
    assert any("auto polygons: obsm/segmentations" in line for line in logs)


def test_affine_maps_a_transposed_boundary_file_back(tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=150, n_genes=5)
    t = pq.read_table(tmp_path / "src/sampleA.polygons.parquet")
    pq.write_table(
        pa.table({"cell_id": t["cell_id"], "vertex_x": t["vertex_y"], "vertex_y": t["vertex_x"]}),
        tmp_path / "src/transposed.parquet",
    )
    _, b_ref, _ = _build(cfg, tmp_path / "ref", lambda s: None)
    _, b_fixed, logs_fixed = _build(
        cfg,
        tmp_path / "fixed",
        lambda s: s.update(polygons={"path": "transposed.parquet", "affine": [0, 1, 0, 1, 0, 0]}),
    )
    assert b_fixed == b_ref
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


def test_pack_reports_centroid_offset():
    xy = np.array([[0.0, 0.0], [10.0, 10.0]])
    ids = ["a", "b"]
    sq = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], dtype=float)
    pids = np.array(["a"] * 4 + ["b"] * 4)
    pxy = np.vstack([sq, sq + [10, 10]])
    _, _, n, dev = pack_polygons(ids, xy, pids, pxy)
    assert n == 2 and dev == pytest.approx(0.0)
    _, _, n, dev = pack_polygons(ids, xy, pids, pxy + [5, 0])
    assert dev == pytest.approx(5.0)
