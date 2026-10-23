"""Molecules (transcripts): read from a long-format table, filtered, mapped into the sample frame like the cells,
cut into spatial tiles sorted by gene, and decoded back exactly."""
import json

import numpy as np
import pyarrow.parquet as pq
import pytest
import zarr

from spatialscape import molecules as M
from spatialscape.build import build_dataset
from spatialscape.config import load_config
from spatialscape.synthetic import make_synthetic
from spatialscape.validate import validate_local


def test_tile_round_trip_is_exact_and_gene_sorted():
    rng = np.random.default_rng(0)
    n = 5000
    gene = rng.integers(0, 40, n).astype(np.uint16)
    qx = rng.integers(0, 32768, n).astype(np.uint16)
    qy = rng.integers(0, 32768, n).astype(np.uint16)
    flags = rng.integers(0, 4, n).astype(np.uint8)
    frame = M.encode_tile(gene, qx, qy, flags)
    g, xy, f = M.decode_tile(frame, (100.0, 200.0), M.GRID)
    assert len(g) == n and (np.diff(g.astype(int)) >= 0).all()  # gene runs ascending
    want = {(int(a), int(b), int(c), int(d)) for a, b, c, d in zip(gene, qx, qy, flags, strict=True)}
    got = {(int(a), round((x - 100.0) / M.GRID), round((y - 200.0) / M.GRID), int(d)) for a, (x, y), d in zip(g, xy, f, strict=True)}
    assert got == want
    assert len(frame) < n * 5  # under the raw 7 bytes per molecule even for positions with no locality
    m = M.morton(np.array([0, 1, 0, 1], np.uint16), np.array([0, 0, 1, 1], np.uint16))
    assert m.tolist() == [0, 1, 2, 3]


def _bundle(tmp_path, n_cells=400, **kw):
    cfg = make_synthetic(tmp_path / "src", n_cells=n_cells, n_genes=12)
    logs: list[str] = []
    m = build_dataset(load_config(cfg), tmp_path / "b", log=logs.append, **kw)
    return cfg, m, logs


def test_molecules_land_where_their_cells_are_in_both_frames(tmp_path):
    _, m, logs = _bundle(tmp_path)
    for sid in ("sampleA", "sampleB"):  # B is flipped and rotated: the molecules must follow
        s = next(x for x in m.samples if x.id == sid)
        assert s.molecules is not None and s.molecules.count > 1000 and s.molecules.genes == 12
        names, gene, xy, flags = M.read_molecules(tmp_path / "b" / "samples" / sid)
        assert names == [f"G{i:03d}" for i in range(12)] and len(gene) == s.molecules.count
        cells = np.asarray(zarr.open_array(str(tmp_path / "b" / "samples" / sid / "obs.zarr" / "xy"), mode="r")[:])
        # every molecule sits within a few cell radii of some cell (scatter sd is 2 px = 20 um)
        from scipy.spatial import cKDTree

        d, _ = cKDTree(cells).query(xy)
        assert np.percentile(d, 99) < 80
        assert 0.4 < (flags & 1).mean() < 0.8  # about 60% assigned
        assert ((flags & 2) > 0).sum() > 0
        idx = json.loads((tmp_path / "b" / "samples" / sid / "molecules.json").read_text())
        assert sum(idx["counts"]) == idx["count"] == s.molecules.count
    assert any("controls" in line and "below Q20" in line for line in logs)
    assert not any("not in the expression matrix" in line for line in logs)
    assert validate_local(tmp_path / "b") == []


def test_quality_filter_and_controls_are_counted(tmp_path):
    make_synthetic(tmp_path / "src", n_cells=300, n_genes=8)
    t = pq.read_table(tmp_path / "src" / "sampleA.transcripts.parquet")
    qv = t.column("qv").to_numpy()
    feat = np.asarray(t.column("feature_name").to_pylist())
    expected = int(((qv >= 20) & ~np.char.startswith(feat.astype(str), "NegControl")).sum())
    st = M.write_molecules(tmp_path / "out", tmp_path / "src" / "sampleA.transcripts.parquet", to_frame=lambda a: a)
    assert st.count == expected and st.read == t.num_rows and st.controls == 40 and st.low_quality == int((qv < 20).sum())
    st2 = M.write_molecules(tmp_path / "out2", tmp_path / "src" / "sampleA.transcripts.parquet", to_frame=lambda a: a, min_qv=0)
    assert st2.count == t.num_rows - 40


def test_one_file_per_tile_and_validate_catches_damage(tmp_path):
    _bundle(tmp_path, sharded=False)
    d = tmp_path / "b" / "samples" / "sampleA"
    assert (d / "molecules").is_dir() and not (d / "molecules.bin").exists()
    assert validate_local(tmp_path / "b") == []
    idx = json.loads((d / "molecules.json").read_text())
    ix, iy = idx["tiles"][0][:2]
    f = d / "molecules" / f"{ix}_{iy}.bin"
    f.write_bytes(f.read_bytes()[:-2])
    assert any("molecule" in p for p in validate_local(tmp_path / "b"))


def test_missing_required_column_is_a_clear_error(tmp_path):
    make_synthetic(tmp_path / "src", n_cells=50, n_genes=4)
    with pytest.raises(KeyError, match="column 'gene' \\(feature\\) not found"):
        M.write_molecules(tmp_path / "out", tmp_path / "src" / "sampleA.transcripts.parquet", to_frame=lambda a: a, columns={"feature": "gene"})
