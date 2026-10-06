"""Per-cell boundary polygons packed as int16 deltas from the cell centroid.

Files (sample-local µm frame, bundle row order):
  polygons.offsets.u32  uint32[n_obs + 1]  vertex start index per cell (zero-length = no polygon)
  polygons.i16          int16[n_vertices * 2]  (dx, dy) * 10 relative to the cell's xy
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

SCALE = 0.1  # µm per unit


def read_polygon_table(path: Path, id_col: str, x_col: str, y_col: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    t = pq.read_table(path, columns=[id_col, x_col, y_col])
    ids = np.asarray(t.column(id_col).to_pylist(), dtype=str)
    x = t.column(x_col).to_numpy(zero_copy_only=False).astype(np.float64)
    y = t.column(y_col).to_numpy(zero_copy_only=False).astype(np.float64)
    return ids, x, y


def pack_polygons(
    obs_ids: list[str],
    xy_um: np.ndarray,
    poly_ids: np.ndarray,
    poly_xy_um: np.ndarray,
    *,
    max_vertices: int = 24,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Return (offsets uint32[n+1], deltas int16[nv*2], n_cells_with_polygon) in bundle row order."""
    order = np.argsort(poly_ids, kind="stable")
    poly_ids = poly_ids[order]
    poly_xy_um = poly_xy_um[order]
    uniq, start, counts = np.unique(poly_ids, return_index=True, return_counts=True)
    lookup = {u: (int(s), int(c)) for u, s, c in zip(uniq, start, counts, strict=True)}
    n = len(obs_ids)
    offsets = np.zeros(n + 1, dtype=np.uint32)
    chunks: list[np.ndarray] = []
    total = 0
    with_poly = 0
    for i, cid in enumerate(obs_ids):
        hit = lookup.get(str(cid))
        if hit:
            s, c = hit
            pts = poly_xy_um[s : s + c]
            if c > max_vertices:
                pts = pts[np.linspace(0, c - 1, max_vertices).round().astype(int)]
            d = np.rint((pts - xy_um[i]) / SCALE)
            d = np.clip(d, -32767, 32767).astype(np.int16)
            chunks.append(d.ravel())
            total += len(pts)
            with_poly += 1
        offsets[i + 1] = total
    deltas = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
    return offsets, deltas, with_poly


def write_polygons(out_dir: Path, offsets: np.ndarray, deltas: np.ndarray) -> None:
    (Path(out_dir) / "polygons.offsets.u32").write_bytes(offsets.astype("<u4").tobytes())
    (Path(out_dir) / "polygons.i16").write_bytes(deltas.astype("<i2").tobytes())
