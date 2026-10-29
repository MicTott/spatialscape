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
