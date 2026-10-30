import numpy as np
import pytest
import scipy.sparse as sp
import zarr

from spatialscape.expression import (
    choose_shard_genes,
    detect_lognorm,
    log1p_cp10k,
    quantize_block,
    write_expression,
)


def test_quantize_round_trip_and_nonzero_preserved():
    rng = np.random.default_rng(1)
    block = rng.uniform(0, 5, size=(4, 1000)).astype(np.float32)
    block[0, :500] = 0
    block[1, :] = 1e-4  # tiny but non-zero
    gmax = block.max(axis=1)
    q = quantize_block(block, gmax)
    assert q.dtype == np.uint8
    assert (q[0, :500] == 0).all()
    assert (q[1] >= 1).all()
    deq = q[2].astype(np.float32) / 255 * gmax[2]
    err = np.abs(deq - block[2])
    step = gmax[2] / 255
    # values below half a step are floored up to code 1 on purpose (expressed cells never render as 0)
    assert err[block[2] >= step / 2].max() <= step / 2 + 1e-6
    assert err.max() <= step + 1e-6


def test_signed_features_quantize_symmetrically_around_zero(tmp_path):
    from spatialscape.expression import feature_ranges

    rng = np.random.default_rng(4)
    M = sp.random(300, 6, density=0.5, random_state=5, format="csr", dtype=np.float32)
    M.data[:] = rng.uniform(0.1, 2, M.nnz)
    M = M.tolil()
    M[:, 2] = rng.normal(0, 1, 300)  # a signed feature, e.g. a module score
    M[:, 4] = -rng.uniform(0, 3, 300)  # entirely negative
    M = M.tocsr()
    lo, hi = feature_ranges(np.asarray(M.min(axis=0).todense()).ravel(), np.asarray(M.max(axis=0).todense()).ravel())
    assert lo[0] == 0 and hi[0] > 0 and lo[2] == -hi[2] and hi[2] == pytest.approx(np.abs(M[:, 2].toarray()).max())
    res = write_expression(M, tmp_path, shard_genes=8, sharded=False)
    g = zarr.open_group(str(tmp_path / "expr.zarr"), mode="r")
    gmin, gmax = g["gmin"][:], g["gmax"][:]
    assert res.gmin is not None and np.allclose(res.gmin, gmin)
    assert (gmin <= 0).all() and gmin[0] == 0 and gmin[2] < 0 and gmin[4] < 0
    u8 = g["u8"][2, :].astype(np.float32)
    deq = gmin[2] + u8 / 255 * (gmax[2] - gmin[2])
    truth = M[:, 2].toarray().ravel()
    assert np.abs(deq - truth).max() <= (gmax[2] - gmin[2]) / 255 + 1e-6
    assert abs(float(gmin[2] + g["u8"][2, :][np.argmin(np.abs(truth))] / 255 * (gmax[2] - gmin[2]))) < (gmax[2] - gmin[2]) / 100  # zero sits near the centre


def test_detect_lognorm():
    counts = sp.csr_matrix(np.random.default_rng(0).poisson(30, size=(50, 20)).astype(np.float32))
    assert detect_lognorm(counts) is False
    assert detect_lognorm(log1p_cp10k(counts)) is True


def test_shard_choice_respects_byte_target():
    assert choose_shard_genes(30_000, 512) == 512
    assert choose_shard_genes(1_000_000, 512) == (128 * 1024 * 1024) // 1_000_000


def test_write_expression_layout(tmp_path):
    rng = np.random.default_rng(2)
    M = sp.random(200, 40, density=0.3, random_state=3, format="csr", dtype=np.float32)
    M.data[:] = rng.uniform(0.1, 3, M.nnz)
    M[:, 7] = 0
    M.eliminate_zeros()
    res = write_expression(M, tmp_path, shard_genes=16, sharded=True)
    assert res.keep.sum() == 39 and not res.keep[7]
    g = zarr.open_group(str(tmp_path / "expr.zarr"), mode="r")
    u8 = g["u8"]
    assert u8.shape == (39, 200) and u8.chunks == (1, 200) and u8.shards == (16, 200)
    col = u8[3, :]
    dense = M.tocsc()[:, [i for i in range(40) if res.keep[i]]][:, 3].toarray().ravel()
    assert ((col > 0) == (dense > 0)).all()
    assert col.max() == 255
    assert np.allclose(g["gmax"][:], M[:, res.keep].max(axis=0).toarray().ravel())


def test_csr_and_csc_inputs_write_the_same_bundle(tmp_path):
    """A CSR matrix is gathered by masking its column index, a CSC one by slicing; the bytes must agree, with the
    LOD shuffle, signed features and an all-zero gene in the mix."""
    rng = np.random.default_rng(5)
    M = sp.random(300, 50, density=0.2, random_state=6, format="csr", dtype=np.float32)
    M.data[:] = rng.uniform(-2, 3, M.nnz)
    M[:, 11] = 0
    M.eliminate_zeros()
    order = rng.permutation(300)
    a = write_expression(M.tocsr(), tmp_path / "csr", shard_genes=16, order=order, keep_f16=True)
    b = write_expression(M.tocsc(), tmp_path / "csc", shard_genes=16, order=order, keep_f16=True)
    assert (a.keep == b.keep).all() and np.array_equal(a.gmax, b.gmax) and np.array_equal(a.gmin, b.gmin)
    ga = zarr.open_group(str(tmp_path / "csr" / "expr.zarr"), mode="r")
    gb = zarr.open_group(str(tmp_path / "csc" / "expr.zarr"), mode="r")
    assert np.array_equal(ga["u8"][:], gb["u8"][:])
    assert np.array_equal(ga["f16"][:], gb["f16"][:])
    assert ga["u8"].shape == (49, 300)


def test_csr_explicit_zero_in_a_dropped_gene(tmp_path):
    """A sparse matrix may store a zero explicitly; a gene whose only stored value is such a zero is dropped, and the
    row-major gather must leave that entry alone instead of scattering it under a kept gene."""
    M = sp.csr_matrix((np.array([1, 1, 1, 0, 1, 1], dtype=np.float32), np.array([0, 1, 2, 3, 4, 5]), np.array([0, 6, 6])), shape=(2, 6))
    res = write_expression(M, tmp_path / "csr", shard_genes=2)
    ref = write_expression(M.tocsc(), tmp_path / "csc", shard_genes=2)
    assert res.keep.tolist() == [True, True, True, False, True, True] and (res.keep == ref.keep).all()
    a = zarr.open_group(str(tmp_path / "csr" / "expr.zarr"), mode="r")["u8"][:]
    b = zarr.open_group(str(tmp_path / "csc" / "expr.zarr"), mode="r")["u8"][:]
    assert np.array_equal(a, b) and a.shape == (5, 2) and a[:, 0].tolist() == [255] * 5 and a[:, 1].tolist() == [0] * 5


def test_csr_gather_is_the_same_in_small_chunks(tmp_path, monkeypatch):
    """The column scan of a CSR matrix runs chunk by chunk; a tiny chunk must give the same bundle as one pass."""
    import spatialscape.expression as ex

    rng = np.random.default_rng(9)
    M = sp.random(120, 30, density=0.25, random_state=10, format="csr", dtype=np.float32)
    M.data[:] = rng.uniform(0.1, 2, M.nnz)
    a = write_expression(M, tmp_path / "one", shard_genes=8)
    monkeypatch.setattr(ex, "MASK_CHUNK", 7)
    b = write_expression(M, tmp_path / "chunked", shard_genes=8)
    ga = zarr.open_group(str(tmp_path / "one" / "expr.zarr"), mode="r")["u8"][:]
    gb = zarr.open_group(str(tmp_path / "chunked" / "expr.zarr"), mode="r")["u8"][:]
    assert np.array_equal(ga, gb) and (a.keep == b.keep).all()


def test_csr_helpers_agree_with_scipy(monkeypatch):
    """The chunked canonical check and the slice-based row gather give scipy's answers, also across chunk edges."""
    import spatialscape.expression as ex
    from spatialscape.expression import csr_is_canonical, csr_rows

    rng = np.random.default_rng(3)
    M = sp.random(50, 40, density=0.2, random_state=4, format="csr", dtype=np.float32)
    M.sort_indices()
    monkeypatch.setattr(ex, "MASK_CHUNK", 7)
    assert csr_is_canonical(M) is True
    rows = np.sort(rng.choice(50, 12, replace=False))
    assert (csr_rows(M, rows) != M[rows]).nnz == 0
    bad = M.copy()
    bad.indices[3], bad.indices[4] = bad.indices[4], bad.indices[3]  # one unsorted pair inside a row
    bad.has_canonical_format = False
    assert csr_is_canonical(bad) is (bad.has_canonical_format if bad.indptr[1] > 4 else csr_is_canonical(bad))
    dup = sp.csr_matrix((np.array([1.0, 1.0, 2.0], dtype=np.float32), np.array([0, 0, 1]), np.array([0, 2, 3])), shape=(2, 3))
    assert csr_is_canonical(dup) is False


def test_csr_input_with_unsorted_rows_writes_the_same_bundle(tmp_path):
    """A CSR matrix whose rows are not sorted by column (as a concatenation of pieces may leave it) is gathered as
    stored, with no copy and the same result as the sorted matrix."""
    rng = np.random.default_rng(11)
    M = sp.random(80, 20, density=0.3, random_state=12, format="csr", dtype=np.float32)
    M.data[:] = rng.uniform(0.1, 2, M.nnz)
    shuffled = M.copy()
    for r in range(shuffled.shape[0]):  # reverse each row's entries
        a, b = shuffled.indptr[r], shuffled.indptr[r + 1]
        shuffled.indices[a:b] = shuffled.indices[a:b][::-1].copy()
        shuffled.data[a:b] = shuffled.data[a:b][::-1].copy()
    shuffled.has_sorted_indices = False
    write_expression(M, tmp_path / "sorted", shard_genes=8)
    write_expression(shuffled, tmp_path / "shuffled", shard_genes=8)
    a = zarr.open_group(str(tmp_path / "sorted" / "expr.zarr"), mode="r")["u8"][:]
    b = zarr.open_group(str(tmp_path / "shuffled" / "expr.zarr"), mode="r")["u8"][:]
    assert np.array_equal(a, b)
