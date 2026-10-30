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
ENTRY_BLOCK = 4 * 1024 * 1024  # stored values quantized per step: bounds the per-entry temporaries, not the shard
MASK_CHUNK = 1 << 27  # entries scanned per step when a CSR matrix's column index is searched for a gene block (1 GB of int64 temporaries at most)


@dataclass
class ExprResult:
    gmax: np.ndarray  # float32 (n_genes_kept,)
    keep: np.ndarray  # bool (n_vars,) genes retained (non-zero)
    shard_genes: int
    sharded: bool
    gmin: np.ndarray | None = None  # float32 (n_genes_kept,): 0 for non-negative features, -gmax for signed ones


def get_matrix(adata: ad.AnnData, layer: str) -> sp.csr_matrix | sp.csc_matrix:
    """The (n_obs, n_vars) matrix as float32, CSR or CSC as stored. The writer gathers gene blocks from either form,
    so nothing is converted here: a CSR matrix of several billion values would need a second copy of itself."""
    M = adata.X if layer == "X" else adata.layers[layer]
    if sp.issparse(M):
        M = M.tocsc() if M.format not in ("csr", "csc") else M
    else:
        M = sp.csc_matrix(np.asarray(M))
    return M.astype(np.float32, copy=False)


def detect_lognorm(M: sp.csr_matrix, sample: int = 1_000_000) -> bool:
    data = M.data
    if data.size == 0:
        return True
    if data.size > sample:
        rng = np.random.default_rng(0)
        data = data[rng.choice(data.size, sample, replace=False)]
    # log-normalized data is essentially never all-integer; raw counts always are (also at low depth, where the
    # old "max <= 20" rule mistook Visium HD bins and small-panel runs for normalized data)
    return not np.allclose(data, np.rint(data))


def log1p_cp10k(M):
    """log1p(CP10k) of a CSR/CSC counts matrix: each stored value times its row's factor, in a new matrix that shares
    the index arrays with the input. `diags(scale) @ M` was a full sparse product whose result came back with
    unsorted indices, so every later reduction sorted the whole matrix again."""
    if not sp.issparse(M) or M.format not in ("csr", "csc"):
        M = sp.csc_matrix(M)
    tot = np.asarray(M.sum(axis=1)).ravel()
    scale = np.where(tot > 0, 1e4 / np.maximum(tot, 1e-12), 0.0).astype(np.float32)
    rows = M.indices if M.format == "csc" else np.repeat(np.arange(M.shape[0]), np.diff(M.indptr))
    data = M.data.astype(np.float32)  # a copy: the caller's matrix is never modified
    data *= scale[rows]
    np.log1p(data, out=data)
    out = M.__class__((data, M.indices, M.indptr), shape=M.shape)
    if M.has_canonical_format:
        out.has_canonical_format = True
    return out


def choose_shard_genes(n_obs: int, requested: int) -> int:
    return int(max(1, min(requested, TARGET_SHARD_BYTES // max(n_obs, 1))))


ZSTD_LEVEL = 7
EMPTY = np.iinfo(np.uint64).max  # a shard index entry for a chunk that was never written


class ShardWriter:
    """Writes the gene-major uint8 array's chunks itself, in the exact zarr v3 layout zarr-python declared in
    zarr.json: per shard `c/<i>/0` = the zstd frames of its rows back to back, then the index (offset, nbytes as
    little-endian uint64 per inner chunk, EMPTY for chunks past the end) followed by its crc32c; unsharded, one
    `c/<g>/0` per gene. Going around zarr-python's per-chunk pipeline removes the few hundred thousand asyncio
    tasks that made up ~90% of a build, and lets the zstd calls run in threads (they release the GIL)."""

    def __init__(self, array_dir: Path, n_obs: int, shard_genes: int, *, sharded: bool, level: int = ZSTD_LEVEL, workers: int | None = None):
        import os
        from concurrent.futures import ThreadPoolExecutor

        from numcodecs import Zstd

        self.dir = Path(array_dir) / "c"
        self.n_obs = n_obs
        self.S = shard_genes
        self.sharded = sharded
        self.codec = Zstd(level=level)
        self.pool = ThreadPoolExecutor(max_workers=workers or min(8, os.cpu_count() or 1))

    def _encode_rows(self, q: np.ndarray) -> list[bytes]:
        rows = [np.ascontiguousarray(q[i]) for i in range(q.shape[0])]
        return list(self.pool.map(lambda r: bytes(self.codec.encode(r)), rows))

    def write(self, g0: int, q: np.ndarray) -> None:
        """Rows g0..g0+len(q) of the array; with sharding, g0 must be a multiple of the shard size."""
        import google_crc32c

        frames = self._encode_rows(q)
        if not self.sharded:
            for k, frame in enumerate(frames):
                d = self.dir / str(g0 + k)
                d.mkdir(parents=True, exist_ok=True)
                (d / "0").write_bytes(frame)
            return
        if g0 % self.S:
            raise ValueError("shard writes must start on a shard boundary")
        index = np.full((self.S, 2), EMPTY, dtype="<u8")
        offset = 0
        for k, frame in enumerate(frames):
            index[k] = (offset, len(frame))
            offset += len(frame)
        idx_bytes = index.tobytes()
        d = self.dir / str(g0 // self.S)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "0", "wb") as fh:
            fh.writelines(frames)
            fh.write(idx_bytes)
            fh.write(np.uint32(google_crc32c.value(idx_bytes)).tobytes())

    def close(self) -> None:
        self.pool.shutdown(wait=True)


def column_ranges(Mc: sp.csc_matrix) -> tuple[np.ndarray, np.ndarray]:
    """Per-column (min, max) of a CSC matrix including its implicit zeros, straight from indptr/data. scipy's
    `.max(axis=0)` first sorts and deduplicates the indices of a matrix read from disk, a 4 s pass on a 15k x 37k
    object; this reads the data once and needs no particular index order."""
    n_obs, n_vars = Mc.shape
    nnz_col = np.diff(Mc.indptr)
    gmax = np.zeros(n_vars, dtype=np.float32)
    gmin = np.zeros(n_vars, dtype=np.float32)
    has = nnz_col > 0
    if has.any():
        starts = Mc.indptr[:-1][has]
        data = Mc.data
        gmax[has] = np.maximum.reduceat(data, starts)
        gmin[has] = np.minimum.reduceat(data, starts)
    sparse_cols = nnz_col < n_obs  # an implicit zero takes part in the range
    gmax = np.where(sparse_cols, np.maximum(gmax, 0), gmax).astype(np.float32)
    gmin = np.where(sparse_cols, np.minimum(gmin, 0), gmin).astype(np.float32)
    return gmin, gmax


def _positions_in_columns(indices: np.ndarray, lo: int, hi: int) -> np.ndarray:
    """Positions of the stored values whose column is in [lo, hi], found a chunk at a time: a boolean mask over a
    7-billion-entry index would be three 7 GB temporaries, which is what put a 1.5 M-nuclei panel out of memory."""
    parts = []
    for start in range(0, len(indices), MASK_CHUNK):
        piece = indices[start : start + MASK_CHUNK]
        hit = np.flatnonzero((piece >= lo) & (piece <= hi))
        if hit.size:
            parts.append(hit + start)
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int64)


def _all_finite(data: np.ndarray) -> bool:
    return all(np.isfinite(data[s : s + MASK_CHUNK]).all() for s in range(0, len(data), MASK_CHUNK))


def column_ranges_csr(M: sp.csr_matrix) -> tuple[np.ndarray, np.ndarray]:
    """`column_ranges` for a CSR matrix: one pass over the stored values, a chunk at a time. (`bincount` and
    `ufunc.at` cast an int32 index to int64 internally: on a 7-billion-entry panel that was a 59 GB temporary each.)"""
    n_obs, n_vars = M.shape
    nnz_col = np.zeros(n_vars, dtype=np.int64)
    gmax = np.full(n_vars, -np.inf, dtype=np.float32)
    gmin = np.full(n_vars, np.inf, dtype=np.float32)
    for s in range(0, M.nnz, MASK_CHUNK):
        idx = M.indices[s : s + MASK_CHUNK]
        val = M.data[s : s + MASK_CHUNK]
        nnz_col += np.bincount(idx, minlength=n_vars)
        np.maximum.at(gmax, idx, val)
        np.minimum.at(gmin, idx, val)
    has = nnz_col > 0
    gmax[~has] = 0
    gmin[~has] = 0
    sparse_cols = nnz_col < n_obs  # an implicit zero takes part in the range
    gmax = np.where(sparse_cols, np.maximum(gmax, 0), gmax).astype(np.float32)
    gmin = np.where(sparse_cols, np.minimum(gmin, 0), gmin).astype(np.float32)
    return gmin, gmax


def column_moments(Mc: sp.csc_matrix) -> tuple[np.ndarray, np.ndarray]:
    """Per-column (mean, variance) of a CSC matrix over all rows, implicit zeros included, in one pass over the data
    and in any index order (scipy's `.mean()` sorts and deduplicates the matrix first)."""
    n_obs, n_vars = Mc.shape
    nnz_col = np.diff(Mc.indptr)
    s1 = np.zeros(n_vars)
    s2 = np.zeros(n_vars)
    has = nnz_col > 0
    if has.any():
        starts = Mc.indptr[:-1][has]
        d = Mc.data.astype(np.float64, copy=False)
        s1[has] = np.add.reduceat(d, starts)
        s2[has] = np.add.reduceat(d * d, starts)
    n = max(n_obs, 1)
    mean = s1 / n
    return mean, np.maximum(s2 / n - mean * mean, 0.0)


def feature_ranges(gmin: np.ndarray, gmax: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The [lo, hi] each feature is quantized over: [0, max] for non-negative features; for features with negative
    values (motif deviations, module scores) a symmetric [-m, m] with m = max |x|, so zero sits at the centre."""
    signed = gmin < 0
    m = np.maximum(np.abs(gmin), np.abs(gmax))
    lo = np.where(signed, -m, 0.0).astype(np.float32)
    hi = np.where(signed, m, gmax).astype(np.float32)
    return lo, hi


def quantize_values(x: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """uint8 codes of x over [lo, hi] (lo/hi broadcast against x): code = rint((x - lo) * 255 / (hi - lo)), and a
    positive value of a non-negative feature never rounds to 0, so an expressed cell never renders as zero."""
    lo = np.asarray(lo, dtype=np.float32)
    span = (np.asarray(hi, dtype=np.float32) - lo).astype(np.float32)
    scale = np.where(span > 0, 255.0 / np.maximum(span, 1e-12), 0.0).astype(np.float32)
    q = np.subtract(x, lo, dtype=np.float32)  # one working buffer, updated in place
    np.multiply(q, scale, out=q)
    np.rint(q, out=q)
    np.clip(q, 0, 255, out=q)
    bump = (lo >= 0) & (x > 0) & (q < 1)
    if bump.any():
        q[bump] = 1
    return q.astype(np.uint8)


def quantize_block(block: np.ndarray, gmax: np.ndarray, gmin: np.ndarray | None = None) -> np.ndarray:
    """block (g, n) float32 -> uint8 over [gmin, gmax] per row (gmin defaults to 0). value = gmin + u8 / 255 * (gmax - gmin)."""
    lo = np.zeros_like(gmax, dtype=np.float32) if gmin is None else np.asarray(gmin, dtype=np.float32)
    return quantize_values(block, lo[:, None], np.asarray(gmax, dtype=np.float32)[:, None])


def write_expression(
    M: sp.csr_matrix,
    out_dir: Path,
    *,
    shard_genes: int = 512,
    sharded: bool = True,
    keep_f16: bool = False,
    order: np.ndarray | None = None,
    log=lambda *_: None,
) -> ExprResult:
    """M is (n_obs, n_vars) normalized, CSR or CSC. Writes out_dir/expr.zarr/{u8,gmax[,f16]}. With `order` (a
    permutation), row i of the written array is observation order[i]: the LOD shuffle is applied while scattering
    the stored values, so the matrix itself is never permuted (a copy with unsorted indices that every later
    reduction would sort again). A CSC matrix gives each gene block as a slice of its arrays; a CSR matrix (what a
    large h5ad usually holds) is kept as it is and each block's values are found by masking the column index, so
    the matrix is never copied: a 1.5 M-cell, 32k-gene panel with 7 billion values builds in its own 60 GB."""
    n_obs, n_vars = M.shape
    csr = sp.issparse(M) and M.format == "csr"
    Mc = M if csr else M.tocsc()
    if Mc.nnz and not Mc.has_canonical_format:
        Mc = Mc.copy()  # duplicate entries must sum, as in a dense view; canonicalise a copy, never the caller's matrix
        Mc.sum_duplicates()
    inv = None
    if order is not None:
        order = np.asarray(order)
        if order.shape != (n_obs,) or not np.array_equal(np.sort(order), np.arange(n_obs)):
            raise ValueError("order must be a permutation of the observations")
        inv = np.empty(n_obs, dtype=np.int64)
        inv[order] = np.arange(n_obs)
    gmax_all = np.zeros(n_vars, dtype=np.float32)
    gmin_all = np.zeros(n_vars, dtype=np.float32)
    if Mc.nnz:
        if not _all_finite(Mc.data):
            finite = np.isfinite(Mc.data)  # only now, to name the columns in the error
            cols = Mc.indices[~finite] if csr else np.repeat(np.arange(n_vars), np.diff(Mc.indptr))[~finite]
            names = ", ".join(str(c) for c in np.unique(cols)[:5])
            raise ValueError(f"expression has NaN or infinite values (feature columns {names}{'...' if len(np.unique(cols)) > 5 else ''}); fix or drop those features before building")
        gmin_all, gmax_all = column_ranges_csr(Mc) if csr else column_ranges(Mc)
    lo_all, hi_all = feature_ranges(gmin_all, gmax_all)
    keep = hi_all > 0  # all-zero features are dropped
    gmax = hi_all[keep]
    gmin = lo_all[keep]
    G = int(keep.sum())

    S = choose_shard_genes(n_obs, shard_genes) if sharded else max(1, min(shard_genes, G))
    store = zarr.storage.LocalStore(str(out_dir / "expr.zarr"))
    root = zarr.open_group(store, mode="w", zarr_format=3)
    kwargs: dict = {
        "shape": (G, n_obs),
        "chunks": (1, n_obs),
        "compressors": [ZstdCodec(level=ZSTD_LEVEL)],
        "fill_value": 0,
        "dimension_names": ("gene", "obs"),
    }
    if sharded:
        kwargs["shards"] = (S, n_obs)
    root.create_array("u8", dtype="uint8", **kwargs)  # zarr writes the metadata; the chunks below are ours
    f16 = root.create_array("f16", dtype="float16", **kwargs) if keep_f16 else None
    writer = ShardWriter(out_dir / "expr.zarr" / "u8", n_obs, S if sharded else 1, sharded=sharded)

    # Only the stored values are quantized; implicit zeros are the shard's fill (0 unless the feature is signed).
    # That is one pass over the nnz values instead of six over a dense n_genes x n_obs float32 block, and the
    # kept columns are gathered per block straight out of the input, so the matrix is never copied or sliced.
    kept = np.flatnonzero(keep)  # input column of each kept gene
    if csr:
        kept_index = np.full(n_vars, -1, dtype=np.int64)  # input column -> kept gene index
        kept_index[kept] = np.arange(G)
    else:
        nnz_col = np.diff(Mc.indptr)
        kcum = np.zeros(G + 1, dtype=np.int64)  # stored values before each kept gene
        np.cumsum(nnz_col[kept], out=kcum[1:])
    zero_code = quantize_values(np.zeros(G, dtype=np.float32), gmin, gmax)

    def scatter(q, h, g0, pos, g):
        """Quantize the stored values at `pos` (kept-gene index `g` each) into the block arrays."""
        rows = np.searchsorted(Mc.indptr, pos, side="right") - 1 if csr else Mc.indices[pos]
        if inv is not None:
            rows = inv[rows]
        flat = (g - g0) * n_obs + rows
        vals = Mc.data[pos]
        q.reshape(-1)[flat] = quantize_values(vals, gmin[g], gmax[g])
        if h is not None:
            h.reshape(-1)[flat] = vals.astype(np.float16)

    for g0 in range(0, G, S):
        g1 = min(G, g0 + S)
        q = np.empty((g1 - g0, n_obs), dtype=np.uint8)
        q[:] = zero_code[g0:g1, None]
        h = np.zeros((g1 - g0, n_obs), dtype=np.float16) if keep_f16 else None
        if csr:
            # every stored value whose column is one of the block's kept genes (dropped genes have none)
            lo_c, hi_c = int(kept[g0]), int(kept[g1 - 1])
            pos = _positions_in_columns(Mc.indices, lo_c, hi_c)
            g = kept_index[Mc.indices[pos]]
            if (g < 0).any():  # explicitly stored zeros of a dropped gene sit inside the block's column span
                pos, g = pos[g >= 0], g[g >= 0]
            if pos.size:
                scatter(q, h, g0, pos, g)
        else:
            b0 = g0
            while b0 < g1:
                # whole genes holding about ENTRY_BLOCK stored values (at least one gene)
                target = min(int(kcum[b0]) + ENTRY_BLOCK, int(kcum[-1]))
                b1 = max(b0 + 1, min(g1, int(np.searchsorted(kcum, target, side="right")) - 1))
                n_vals = int(kcum[b1] - kcum[b0])
                if n_vals:
                    lengths = nnz_col[kept[b0:b1]]
                    starts = Mc.indptr[kept[b0:b1]].astype(np.int64)
                    # position in Mc.data of every stored value of the block, column segments back to back
                    pos = np.arange(n_vals, dtype=np.int64) + np.repeat(starts - (np.cumsum(lengths) - lengths), lengths)
                    scatter(q, h, g0, pos, np.repeat(np.arange(b0, b1, dtype=np.int64), lengths))
                b0 = b1
        writer.write(g0, q)
        if f16 is not None:
            f16[g0:g1, :] = h
        log(f"  expr genes {g1}/{G}")
    writer.close()

    root.create_array("gmax", shape=(G,), chunks=(max(G, 1),), dtype="float32", compressors=[ZstdCodec(level=3)])
    root["gmax"][:] = gmax
    root.create_array("gmin", shape=(G,), chunks=(max(G, 1),), dtype="float32", compressors=[ZstdCodec(level=3)])
    root["gmin"][:] = gmin
    return ExprResult(gmax=gmax, keep=keep, shard_genes=S, sharded=sharded, gmin=gmin)
