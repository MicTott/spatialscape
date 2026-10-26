"""Readers for per-cell boundary polygons: a long-format parquet file (one row per vertex) or an obsm array.
The build tiles them with spatialscape.shapes."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def read_polygon_table(path: Path, id_col: str, x_col: str, y_col: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One row per vertex, from Parquet or CSV / TSV (gzipped or not); ids come back as strings, numeric ones included."""
    from .tables import read_columns, table_columns

    present = table_columns(path)
    missing = [c for c in (id_col, x_col, y_col) if c not in present]
    if missing:
        raise KeyError(f"{path}: column{'s' if len(missing) > 1 else ''} {', '.join(repr(c) for c in missing)} not found; columns are {sorted(present)}")
    t = read_columns(path, [id_col, x_col, y_col])
    ids = np.asarray(t.column(id_col).to_pylist(), dtype=str)
    x = t.column(x_col).to_numpy(zero_copy_only=False).astype(np.float64)
    y = t.column(y_col).to_numpy(zero_copy_only=False).astype(np.float64)
    return ids, x, y


def read_polygon_obsm(adata, key: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Flatten an obsm array of shape (n_obs, n_vertices, 2) into (ids, x, y); NaN-padded vertices are dropped."""
    arr = np.asarray(adata.obsm[key], dtype=np.float64)
    if arr.ndim != 3 or arr.shape[2] != 2:
        raise ValueError(f"obsm/{key}: expected shape (n_obs, n_vertices, 2), got {arr.shape}")
    _n, v, _ = arr.shape
    ids = np.repeat(np.asarray(adata.obs_names, dtype=str), v)
    x, y = arr[:, :, 0].ravel(), arr[:, :, 1].ravel()
    ok = np.isfinite(x) & np.isfinite(y)
    return ids[ok], x[ok], y[ok]


def apply_affine(x: np.ndarray, y: np.ndarray, affine) -> tuple[np.ndarray, np.ndarray]:
    a, b, c, d, e, f = (float(v) for v in affine)
    return a * x + b * y + c, d * x + e * y + f
