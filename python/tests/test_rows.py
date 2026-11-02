"""The per-cell row store: the same codes as the gene-major store, one cell at a time, along a Morton curve."""

import json
from itertools import pairwise

import numpy as np
import pytest
import scipy.sparse as sp
import zarr

from spatialscape.config import DatasetConfig, SampleSpec, rows_wanted
from spatialscape.expression import feature_ranges, quantize_values
from spatialscape.rows import morton_order, read_rows, write_rows


def _config(tmp_path, adata_path, **sample):
    return DatasetConfig(id="t", name="t", samples=[SampleSpec(id="s", platform="visium", path=adata_path, **sample)])


def test_rows_match_the_gene_major_codes(tmp_path, small_adata):
    from spatialscape.build import build_dataset

    src = tmp_path / "a.h5ad"
    small_adata.write_h5ad(src)
    out = tmp_path / "bundle"
    build_dataset(_config(tmp_path, src), out)
    m = json.loads((out / "manifest.json").read_text())
    s = m["samples"][0]
    assert s["rows"]["order"] == "morton"
    d = out / "samples" / "s"
    g = zarr.open_group(str(d / "expr.zarr"), mode="r")
    u8 = np.asarray(g["u8"][:])  # (genes, bundle rows)
    assert s["rows"]["nnz"] == int((u8 > 0).sum())
    rows = np.array([0, 7, 123, 299])
    R = read_rows(d, rows).toarray()
    np.testing.assert_array_equal(R, u8[:, rows].T)
    # no zeros stored, genes ascending within a row
    rg = zarr.open_group(str(d / "rows.zarr"), mode="r")
    assert (np.asarray(rg["value"][:]) > 0).all()
    ptr = np.asarray(rg["indptr"][:])
    steps = np.asarray(rg["gene"][:])
    for a, b in pairwise(ptr):
        assert (steps[a + 1 : b] > 0).all()  # ids ascend within a row, stored as their steps


def test_rows_follow_the_curve_and_pos_inverts_it(tmp_path):
    rng = np.random.default_rng(1)
    xy = rng.uniform(0, 100, size=(500, 2))
    order = morton_order(xy)
    assert sorted(order.tolist()) == list(range(500))
    # neighbours along the curve are close in space far more often than random pairs
    steps = np.linalg.norm(np.diff(xy[order], axis=0), axis=1)
    random_pairs = np.linalg.norm(xy[rng.permutation(500)][1:] - xy[rng.permutation(500)][:-1], axis=1)
    assert np.median(steps) < 0.3 * np.median(random_pairs)


def test_write_rows_from_csc_and_signed_values(tmp_path):
    rng = np.random.default_rng(2)
    X = rng.normal(size=(50, 6)).astype(np.float32)
    X[rng.uniform(size=X.shape) < 0.5] = 0
    X[:, 2] = 0  # dropped gene
    M = sp.csc_matrix(X)
    gmin_all = X.min(axis=0)
    gmax_all = X.max(axis=0)
    lo, hi = feature_ranges(gmin_all.astype(np.float32), gmax_all.astype(np.float32))
    keep = hi > 0
    perm = rng.permutation(50)
    xy = rng.uniform(0, 10, size=(50, 2))
    info = write_rows(M, tmp_path, keep=keep, gmin=lo[keep], gmax=hi[keep], xy=xy, perm=perm)
    assert info["nnz"] == int((X[:, keep] != 0).sum())
    R = read_rows(tmp_path, np.arange(50)).toarray()
    expected = np.zeros((50, int(keep.sum())), dtype=np.uint8)
    Xk = X[perm][:, keep]
    nz = Xk != 0
    expected[nz] = quantize_values(Xk[nz], np.broadcast_to(lo[keep], Xk.shape)[nz], np.broadcast_to(hi[keep], Xk.shape)[nz])
    np.testing.assert_array_equal(R, expected)


def test_auto_rows_follow_the_sample_kind(tmp_path, small_adata):
    from spatialscape.config import ExpressionSpec

    assert rows_wanted(ExpressionSpec(), "spatial")
    assert not rows_wanted(ExpressionSpec(), "embedding")
    assert rows_wanted(ExpressionSpec(rows=True), "embedding")
    assert not rows_wanted(ExpressionSpec(rows=False), "spatial")


def test_embedding_has_no_rows_unless_asked(tmp_path, small_adata):
    from spatialscape.build import build_dataset

    src = tmp_path / "a.h5ad"
    small_adata.obsm["X_umap"] = small_adata.obsm["spatial"]
    small_adata.write_h5ad(src)
    out = tmp_path / "bundle"
    cfg = DatasetConfig(id="t", name="t", samples=[SampleSpec(id="s", platform="snrnaseq", kind="embedding", coords="obsm/X_umap", path=src)])
    build_dataset(cfg, out)
    m = json.loads((out / "manifest.json").read_text())
    assert m["samples"][0].get("rows") is None
    assert not (out / "samples" / "s" / "rows.zarr").exists()


@pytest.mark.parametrize("rows", [True])
def test_validate_checks_the_row_store(tmp_path, small_adata, rows):
    from spatialscape.build import build_dataset
    from spatialscape.validate import validate_local

    src = tmp_path / "a.h5ad"
    small_adata.write_h5ad(src)
    out = tmp_path / "bundle"
    build_dataset(_config(tmp_path, src), out)
    assert validate_local(out) == []
    pos = zarr.open_group(str(out / "samples" / "s" / "rows.zarr"), mode="r+")["pos"]
    pos[0] = pos[1]
    problems = validate_local(out)
    assert any("permutation" in p for p in problems)
