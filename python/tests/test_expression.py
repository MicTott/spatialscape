import numpy as np
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
