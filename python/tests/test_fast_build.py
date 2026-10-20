"""The build's fast paths: hand-written shards, column ranges without index sorting, strip-wise downsampling,
pyramid level choice and the partial AnnData loader."""
from __future__ import annotations

import numpy as np
import pytest
import scipy.sparse as sp
import zarr

from spatialscape import expression as E
from spatialscape import images as I
from spatialscape.readers import read_anndata


def test_shard_writer_matches_zarr_for_full_partial_and_unsharded(tmp_path):
    rng = np.random.default_rng(0)
    M = sp.csc_matrix(rng.poisson(0.4, size=(70, 1300)).astype(np.float32))  # 1300 genes: 2 full shards + a partial one at S=512
    for sharded in (True, False):
        out = tmp_path / ("sharded" if sharded else "flat")
        res = E.write_expression(M, out, shard_genes=512, sharded=sharded, log=lambda *_: None)
        u8 = zarr.open_array(str(out / "expr.zarr" / "u8"), mode="r")
        got = u8[:]
        # reference: dequantize and compare with the matrix the way the viewer would read it
        lo = np.asarray(zarr.open_array(str(out / "expr.zarr" / "gmin"), mode="r")[:])
        hi = res.gmax
        want = M.toarray().T[res.keep]
        expect = E.quantize_block(want.astype(np.float32), hi, lo)
        assert got.shape == want.shape and np.array_equal(got, expect)
        if sharded:
            shard = out / "expr.zarr" / "u8" / "c" / "2" / "0"  # the partial last shard still has a full index
            assert shard.exists() and shard.stat().st_size > 16 * 512 + 4


def test_column_ranges_include_implicit_zeros_and_need_no_sorted_indices():
    M = sp.csc_matrix(np.array([[0, 2.0, -1.0], [0, 3.0, -2.0], [0, 0, 4.0]], dtype=np.float32))
    M.has_sorted_indices = False
    M.indices = M.indices.copy()
    gmin, gmax = E.column_ranges(M)
    assert gmax.tolist() == [0, 3, 4] and gmin.tolist() == [0, 0, -2]
    dense_min, dense_max = np.asarray(M.min(axis=0).todense()).ravel(), np.asarray(M.max(axis=0).todense()).ravel()
    assert np.array_equal(gmin, dense_min) and np.array_equal(gmax, dense_max)


def test_downsample2_is_a_rounded_mean_in_strips():
    rng = np.random.default_rng(1)
    img = rng.integers(0, 256, size=(3, 2051, 1203), dtype=np.uint8)
    got = I.downsample2(img, strip=100)
    ref = img[:, :2050, :1202].astype(np.float32).reshape(3, 1025, 2, 601, 2).mean(axis=(2, 4))
    assert got.shape == (3, 1025, 601) and np.abs(got.astype(float) - ref).max() <= 0.5 + 1e-6
    f = rng.random((1, 10, 10), dtype=np.float32)
    assert I.downsample2(f).shape == (1, 5, 5)


def test_pick_level_takes_the_smallest_level_that_is_still_large_enough():
    shapes = [(3, 40000, 30000), (3, 20000, 15000), (3, 10000, 7500), (3, 5000, 3750), (3, 2500, 1875)]
    assert I._pick_level(shapes, "cyx", 8192) == 2
    assert I._pick_level(shapes, "cyx", 100_000) == 0
    assert I._pick_level(shapes, "cyx", 1000) == 4
    assert I._pick_level([(40000, 30000, 3)], "YXS", 8192) == 0


def test_partial_loader_skips_layers_and_graphs(tmp_path):
    import anndata as ad

    rng = np.random.default_rng(2)
    a = ad.AnnData(X=sp.csr_matrix(rng.poisson(0.5, size=(50, 20)).astype(np.float32)))
    a.layers["counts"] = a.X.copy()
    a.obsm["spatial"] = rng.random((50, 2))
    a.obsm["X_umap"] = rng.random((50, 2))
    a.obsm["segmentations"] = rng.random((50, 6, 2))
    a.obsp["connectivities"] = sp.random(50, 50, density=0.1, format="csr")
    a.uns["spot_nn_spacing_level0_px"] = 12.5
    p = tmp_path / "a.h5ad"
    a.write_h5ad(p)
    b = read_anndata(p, layer="X", obsm_keys=["spatial"])
    assert set(b.obsm.keys()) == {"spatial", "segmentations"} and not b.layers and not b.obsp
    assert b.uns["spot_nn_spacing_level0_px"] == 12.5 and b.shape == (50, 20)
    c = read_anndata(p, layer="counts", obsm_keys=["X_umap"])
    assert np.array_equal(c.X.toarray(), a.layers["counts"].toarray()) and "X_umap" in c.obsm
    with pytest.raises(KeyError, match="layer 'nope'"):
        read_anndata(p, layer="nope")
    assert read_anndata(p).layers.keys()  # the full read is still the default


def _u8_and_ref(out, M, res, order=None):
    got = zarr.open_array(str(out / "expr.zarr" / "u8"), mode="r")[:]
    lo = np.asarray(zarr.open_array(str(out / "expr.zarr" / "gmin"), mode="r")[:])
    dense = M.toarray()
    want = (dense[order] if order is not None else dense).T[res.keep]
    return got, E.quantize_block(want.astype(np.float32), res.gmax, lo)


def test_write_expression_order_scatters_the_shuffle(tmp_path):
    rng = np.random.default_rng(5)
    M = sp.csc_matrix(rng.poisson(0.5, size=(50, 40)).astype(np.float32))
    perm = rng.permutation(50)
    res = E.write_expression(M, tmp_path, shard_genes=16, sharded=True, order=perm, log=lambda *_: None)
    got, want = _u8_and_ref(tmp_path, M, res, perm)
    assert np.array_equal(got, want)
    assert M.has_canonical_format  # the matrix was neither permuted nor re-sorted
    with pytest.raises(ValueError, match="permutation"):
        E.write_expression(M, tmp_path / "bad", order=perm[:-1], log=lambda *_: None)


def test_writer_sums_duplicates_and_accepts_unsorted_indices_like_a_dense_view(tmp_path):
    # column 0 stores rows 2 then 1 (unsorted); column 1 stores row 3 twice (duplicates add up, as toarray() does)
    data = np.array([1, 2, 1.5, 2.5, 4], dtype=np.float32)
    M = sp.csc_matrix((data, np.array([2, 1, 3, 3, 0]), np.array([0, 2, 4, 5])), shape=(5, 3))
    assert not M.has_canonical_format
    res = E.write_expression(M, tmp_path, shard_genes=8, sharded=False, log=lambda *_: None)
    got, want = _u8_and_ref(tmp_path, M, res)
    assert np.array_equal(got, want) and res.gmax.tolist() == [2, 4, 4]
    assert not M.has_canonical_format and M.indices.tolist() == [2, 1, 3, 3, 0]  # the caller's matrix is untouched


def test_writer_blocks_by_stored_values_not_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "ENTRY_BLOCK", 7)  # several blocks per shard, one column wider than a block
    rng = np.random.default_rng(6)
    dense = rng.poisson(0.8, size=(12, 30)).astype(np.float32)
    dense[:, [0, 5, 17, 29]] = 0  # dropped genes inside and at both ends: kept columns are gathered, never contiguous
    M = sp.csc_matrix(dense)
    res = E.write_expression(M, tmp_path, shard_genes=16, sharded=True, keep_f16=True, log=lambda *_: None)
    assert res.keep.sum() == 26
    got, want = _u8_and_ref(tmp_path, M, res)
    assert np.array_equal(got, want)
    f16 = zarr.open_array(str(tmp_path / "expr.zarr" / "f16"), mode="r")[:]
    assert np.array_equal(f16.astype(np.float32), M.toarray().T[res.keep])


def test_log1p_cp10k_scales_rows_in_place_of_a_sparse_product():
    rng = np.random.default_rng(2)
    dense = rng.poisson(1.0, size=(30, 20)).astype(np.float32)
    dense[3] = 0  # an empty cell stays zero
    tot = dense.sum(axis=1, keepdims=True)
    want = np.log1p(np.divide(dense * np.float32(1e4), tot, out=np.zeros_like(dense), where=tot > 0))
    for fmt in ("csr", "csc"):
        M = getattr(sp, f"{fmt}_matrix")(dense)
        before = M.data.copy()
        out = E.log1p_cp10k(M)
        assert out.format == fmt and out.has_canonical_format
        assert np.allclose(out.toarray(), want, rtol=1e-5, atol=1e-6)
        assert np.array_equal(M.data, before) and out.data is not M.data


def test_column_moments_match_dense_in_any_index_order():
    rng = np.random.default_rng(4)
    dense = rng.poisson(0.7, size=(25, 12)).astype(np.float32)
    dense[:, 0] = 0
    M = sp.csc_matrix(dense)
    for c in range(M.shape[1]):  # reverse every column segment: valid, but not canonical
        s, e = M.indptr[c], M.indptr[c + 1]
        M.indices[s:e] = M.indices[s:e][::-1].copy()
        M.data[s:e] = M.data[s:e][::-1].copy()
    M.has_sorted_indices = False
    mean, var = E.column_moments(M)
    assert np.allclose(mean, dense.mean(axis=0)) and np.allclose(var, dense.var(axis=0))
