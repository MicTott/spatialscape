"""The row store: the same quantized matrix again, one cell at a time, for tests on a handful of cells.

`expr.zarr/u8` is gene-major, which is what colouring the map needs (one gene for every cell). A differential
expression test on a lasso needs the opposite, every gene for a few cells, and from the gene-major store that is
the whole sample. So each sample may also carry `rows.zarr`, a sparse CSR copy of the kept genes' values:

    indptr  uint32 (nObs + 1)   stored values before each row of the store
    gene    uint16 | uint32     kept-gene index (the row of expr.zarr/u8) of every stored value, as the step from
                                the previous value of the same row (the row's first value absolute): sorted ids
                                make small steps, which zstd packs about twice as tight as the ids themselves
    value   uint8               the same code as expr.zarr/u8: x = gmin + value / 255 * (gmax - gmin)
    pos     uint32 (nObs)       where bundle row i (the shuffled order of obs.zarr) sits in the store

Rows are ordered along a Morton curve over the section's coordinates, so a spatially compact selection is a few
contiguous runs of rows, and the viewer fetches those runs' chunks with a few range requests. Zero values are not
stored. The store is written in whole shards through zarr-python: with chunks of a million values the per-chunk
overhead that made the gene-major writer roll its own is negligible here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import scipy.sparse as sp
import zarr
from zarr.codecs import ZstdCodec

from .expression import ZSTD_LEVEL, csr_rows, quantize_values
from .molecules import morton

ROWS_DIR = "rows.zarr"
CHUNK = 1 << 20  # stored values per inner chunk: about 1 MB of codes, 2 MB of gene ids
SHARD_CHUNKS = 32  # inner chunks per shard file
BLOCK_ROWS = 4096  # rows gathered from the source matrix per step
MAX_NNZ = (1 << 32) - 1  # indptr is uint32


def morton_order(xy: np.ndarray) -> np.ndarray:
    """Bundle rows sorted along a Z-order curve over their coordinates (a 65,536-cell grid across the section)."""
    xy = np.asarray(xy, dtype=np.float64)
    if not len(xy):
        return np.zeros(0, dtype=np.int64)
    lo = xy.min(axis=0)
    span = np.maximum(xy.max(axis=0) - lo, 1e-9)
    q = np.clip(np.floor((xy - lo) / span * 65535.0), 0, 65535).astype(np.uint16)
    return np.argsort(morton(q[:, 0], q[:, 1]), kind="stable")


def write_rows(
    M: sp.csr_matrix | sp.csc_matrix,
    out_dir: Path,
    *,
    keep: np.ndarray,
    gmin: np.ndarray,
    gmax: np.ndarray,
    xy: np.ndarray,
    perm: np.ndarray,
    log=lambda *_: None,
) -> dict:
    """Write out_dir/rows.zarr from the normalized source matrix M (n_obs, n_vars). `keep` marks the genes the
    gene-major store kept (its row order is the kept genes in source order), `gmin`/`gmax` are their quantization
    ranges, `xy` the bundle-order coordinates and `perm` the bundle order (bundle row i = source row perm[i]).
    Returns the manifest's `rows` entry."""
    n_obs, n_vars = M.shape
    if sp.issparse(M) and M.format != "csr":
        M = M.tocsr()  # a second copy, for sections (embeddings large enough to hurt leave the store off)
    elif not sp.issparse(M):
        M = sp.csr_matrix(M)
    kept = np.flatnonzero(keep)
    kept_index = np.full(n_vars, -1, dtype=np.int64)
    kept_index[kept] = np.arange(len(kept))
    G = len(kept)
    gene_dtype = "uint16" if np.iinfo(np.uint16).max >= G else "uint32"
    gmin = np.asarray(gmin, dtype=np.float32)
    gmax = np.asarray(gmax, dtype=np.float32)

    order = morton_order(xy)  # bundle rows in store order
    pos = np.empty(n_obs, dtype=np.uint32)
    pos[order] = np.arange(n_obs, dtype=np.uint32)
    src_rows = np.asarray(perm)[order]  # source row of each store row

    store = zarr.storage.LocalStore(str(out_dir / ROWS_DIR))
    root = zarr.open_group(store, mode="w", zarr_format=3)
    root.attrs.update({"order": "morton", "chunk": CHUNK, "n_genes": G})
    shard = CHUNK * SHARD_CHUNKS
    nnz_total = int(M.indptr[-1]) if hasattr(M, "indptr") else int(M.nnz)
    if nnz_total > MAX_NNZ:
        raise ValueError(f"the row store holds at most {MAX_NNZ:,} stored values; this sample has {nnz_total:,} (set `expression.rows: false`)")
    gene_arr = root.create_array("gene", shape=(nnz_total,), chunks=(CHUNK,), shards=(shard,), dtype=gene_dtype, compressors=[ZstdCodec(level=ZSTD_LEVEL)], fill_value=0)
    value_arr = root.create_array("value", shape=(nnz_total,), chunks=(CHUNK,), shards=(shard,), dtype="uint8", compressors=[ZstdCodec(level=ZSTD_LEVEL)], fill_value=0)
    indptr = np.zeros(n_obs + 1, dtype=np.uint32)

    buf_g: list[np.ndarray] = []
    buf_v: list[np.ndarray] = []
    buffered = 0
    written = 0

    def flush(final: bool) -> None:
        nonlocal buf_g, buf_v, buffered, written
        if not buffered:
            return
        g = np.concatenate(buf_g)
        v = np.concatenate(buf_v)
        n = len(g) if final else (len(g) // shard) * shard  # whole shards only, so zarr never rewrites one
        if n:
            gene_arr[written : written + n] = g[:n]
            value_arr[written : written + n] = v[:n]
            written += n
        buf_g, buf_v = ([g[n:]], [v[n:]]) if n < len(g) else ([], [])
        buffered = len(g) - n

    for b0 in range(0, n_obs, BLOCK_ROWS):
        rows = src_rows[b0 : b0 + BLOCK_ROWS]
        sub = csr_rows(M, rows)
        g = kept_index[sub.indices]
        vals = sub.data.astype(np.float32, copy=False)
        rid = np.repeat(np.arange(len(rows)), np.diff(sub.indptr))
        ok = (g >= 0) & (vals != 0) & np.isfinite(vals)
        g, vals, rid = g[ok], vals[ok], rid[ok]
        srt = np.lexsort((g, rid))  # by row, genes ascending within a row
        g, vals, rid = g[srt], vals[srt], rid[srt]
        codes = quantize_values(vals, gmin[g], gmax[g]) if len(g) else np.zeros(0, dtype=np.uint8)
        counts = np.bincount(rid, minlength=len(rows))
        indptr[b0 + 1 : b0 + 1 + len(rows)] = counts
        buf_g.append(gene_steps(g, rid).astype(gene_dtype))
        buf_v.append(codes)
        buffered += len(g)
        if buffered >= shard:
            flush(final=False)
        if (b0 // BLOCK_ROWS) % 16 == 15:
            log(f"  rows {min(n_obs, b0 + BLOCK_ROWS)}/{n_obs}")
    flush(final=True)
    np.cumsum(indptr, out=indptr)
    nnz = int(indptr[-1])
    if written != nnz:
        raise RuntimeError(f"row store wrote {written:,} values for {nnz:,} stored")
    if nnz < nnz_total:  # zeros and dropped genes were stored in the source: shrink the arrays to what was written
        gene_arr.resize((nnz,))
        value_arr.resize((nnz,))
    root.create_array("indptr", shape=(n_obs + 1,), chunks=(max(1, min(n_obs + 1, CHUNK)),), dtype="uint32", compressors=[ZstdCodec(level=3)])
    root["indptr"][:] = indptr
    root.create_array("pos", shape=(n_obs,), chunks=(max(1, min(n_obs, CHUNK)),), dtype="uint32", compressors=[ZstdCodec(level=3)])
    if n_obs:
        root["pos"][:] = pos
    return {"nnz": nnz, "chunk": CHUNK, "order": "morton"}


def gene_steps(gene: np.ndarray, row: np.ndarray) -> np.ndarray:
    """Gene ids sorted within rows -> the step from the previous id of the same row, the first of a row as it is."""
    if not len(gene):
        return gene
    steps = np.diff(gene, prepend=gene[:1])
    first = np.ones(len(gene), dtype=bool)
    first[1:] = row[1:] != row[:-1]
    steps[first] = gene[first]
    return steps


def gene_ids(steps: np.ndarray) -> np.ndarray:
    """The ids of one row back from its steps."""
    return np.cumsum(steps, dtype=np.int64)


def read_rows(sample_dir: Path, bundle_rows: np.ndarray) -> sp.csr_matrix:
    """The stored values of the given bundle rows as a CSR matrix (rows in the order asked, columns = kept genes),
    codes as uint8. For tests and scripts; the viewer's worker does the same with range requests."""
    g = zarr.open_group(str(Path(sample_dir) / ROWS_DIR), mode="r")
    pos = np.asarray(g["pos"][:])[np.asarray(bundle_rows)]
    indptr = np.asarray(g["indptr"][:])
    gene, value = g["gene"], g["value"]
    n_genes = int(g.attrs.get("n_genes", 0)) or None
    data, indices, out_ptr = [], [], [0]
    for p in pos:
        a, b = int(indptr[p]), int(indptr[p + 1])
        data.append(np.asarray(value[a:b]))
        indices.append(gene_ids(np.asarray(gene[a:b])))
        out_ptr.append(out_ptr[-1] + (b - a))
    d = np.concatenate(data) if data else np.zeros(0, dtype=np.uint8)
    i = np.concatenate(indices) if indices else np.zeros(0, dtype=np.int64)
    width = n_genes or (int(i.max()) + 1 if len(i) else 0)
    return sp.csr_matrix((d, i.astype(np.int64), np.asarray(out_ptr)), shape=(len(pos), width))
