"""Expression matrix: normalization detection, uint8 quantization, gene-major zarr v3 writer."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import anndata as ad
import numpy as np
import scipy.sparse as sp
import zarr
from zarr.codecs import ZstdCodec

TARGET_SHARD_BYTES = 128 * 1024 * 1024
FLOAT_BLOCK_BYTES = 64 * 1024 * 1024


@dataclass
class ExprResult:
    gmax: np.ndarray  # float32 (n_genes_kept,)
    keep: np.ndarray  # bool (n_vars,) genes retained (non-zero)
    shard_genes: int
    sharded: bool


def get_matrix(adata: ad.AnnData, layer: str) -> sp.csr_matrix:
    M = adata.X if layer == "X" else adata.layers[layer]
    if sp.issparse(M):
        M = M.tocsr()
    else:
        M = sp.csr_matrix(np.asarray(M))
    return M.astype(np.float32, copy=False)


def detect_lognorm(M: sp.csr_matrix, sample: int = 1_000_000) -> bool:
    data = M.data
    if data.size == 0:
        return True
    if data.size > sample:
        rng = np.random.default_rng(0)
        data = data[rng.choice(data.size, sample, replace=False)]
    is_int = np.allclose(data, np.rint(data))
    return not (is_int and data.max() > 20)


def log1p_cp10k(M: sp.csr_matrix) -> sp.csr_matrix:
    tot = np.asarray(M.sum(axis=1)).ravel()
    scale = np.where(tot > 0, 1e4 / np.maximum(tot, 1e-12), 0.0).astype(np.float32)
    M = sp.diags(scale) @ M
    M = M.tocsr()
    np.log1p(M.data, out=M.data)
    return M


def choose_shard_genes(n_obs: int, requested: int) -> int:
    return int(max(1, min(requested, TARGET_SHARD_BYTES // max(n_obs, 1))))


def quantize_block(block: np.ndarray, gmax: np.ndarray) -> np.ndarray:
    """block (g, n) float32, gmax (g,) -> uint8 with nonzero preserved as >= 1."""
    scale = np.where(gmax > 0, 255.0 / np.maximum(gmax, 1e-12), 0.0).astype(np.float32)
    q = np.rint(block * scale[:, None])
    q = np.clip(q, 0, 255)
    q[(block > 0) & (q < 1)] = 1
    return q.astype(np.uint8)


def write_expression(
    M: sp.csr_matrix,
    out_dir: Path,
    *,
    shard_genes: int = 512,
    sharded: bool = True,
    keep_f16: bool = False,
    log=lambda *_: None,
) -> ExprResult:
    """M is (n_obs, n_vars) normalized. Writes out_dir/expr.zarr/{u8,gmax[,f16]}."""
    n_obs, n_vars = M.shape
    Mc = M.tocsc()
    gmax_all = np.zeros(n_vars, dtype=np.float32)
    if Mc.nnz:
        gmax_all = np.asarray(Mc.max(axis=0).todense()).ravel().astype(np.float32)
    keep = gmax_all > 0
    Mc = Mc[:, keep]
    gmax = gmax_all[keep]
    G = int(keep.sum())

    S = choose_shard_genes(n_obs, shard_genes) if sharded else max(1, min(shard_genes, G))
    store = zarr.storage.LocalStore(str(out_dir / "expr.zarr"))
    root = zarr.open_group(store, mode="w", zarr_format=3)
    kwargs: dict = {
        "shape": (G, n_obs),
        "chunks": (1, n_obs),
        "compressors": [ZstdCodec(level=7)],
        "fill_value": 0,
        "dimension_names": ("gene", "obs"),
    }
    if sharded:
        kwargs["shards"] = (S, n_obs)
    u8 = root.create_array("u8", dtype="uint8", **kwargs)
    f16 = root.create_array("f16", dtype="float16", **kwargs) if keep_f16 else None

    fblock = max(1, min(S, FLOAT_BLOCK_BYTES // max(n_obs * 4, 1)))
    for g0 in range(0, G, S):
        g1 = min(G, g0 + S)
        q = np.empty((g1 - g0, n_obs), dtype=np.uint8)
        h = np.empty((g1 - g0, n_obs), dtype=np.float16) if keep_f16 else None
        for b0 in range(g0, g1, fblock):
            b1 = min(g1, b0 + fblock)
            dense = np.asarray(Mc[:, b0:b1].todense()).T.astype(np.float32)  # (g, n)
            q[b0 - g0 : b1 - g0] = quantize_block(dense, gmax[b0:b1])
            if h is not None:
                h[b0 - g0 : b1 - g0] = dense.astype(np.float16)
        u8[g0:g1, :] = q
        if f16 is not None:
            f16[g0:g1, :] = h
        log(f"  expr genes {g1}/{G}")

    root.create_array("gmax", shape=(G,), chunks=(max(G, 1),), dtype="float32", compressors=[ZstdCodec(level=3)])
    root["gmax"][:] = gmax
    return ExprResult(gmax=gmax, keep=keep, shard_genes=S, sharded=sharded)
