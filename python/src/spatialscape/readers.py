"""Read AnnData (h5ad / zarr v2 / zarr v3) and SpatialData tables into a uniform object."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anndata as ad
import numpy as np
import pandas as pd

from .config import SampleSpec


@dataclass
class SampleInput:
    adata: ad.AnnData
    coords: np.ndarray  # (n_obs, 2) float64 in source units
    gene_names: np.ndarray  # (n_vars,) str
    uns: dict[str, Any] = field(default_factory=dict)


def read_anndata(path: Path, table: str | None = None) -> ad.AnnData:
    path = Path(path)
    if path.is_file():
        if path.suffix == ".h5ad":
            return ad.read_h5ad(path)
        raise ValueError(f"unsupported file type: {path}")
    if not path.is_dir():
        raise FileNotFoundError(path)
    tables = path / "tables"
    if tables.is_dir():  # SpatialData store
        if table is None:
            keys = sorted(p.name for p in tables.iterdir() if p.is_dir())
            if len(keys) != 1:
                raise ValueError(f"SpatialData store has tables {keys}; set `table:`")
            table = keys[0]
        return ad.read_zarr(tables / table)
    return ad.read_zarr(path)


def get_coords(adata: ad.AnnData, spec: str) -> np.ndarray:
    if spec.startswith("obsm/"):
        key = spec[len("obsm/") :]
        if key not in adata.obsm:
            raise KeyError(f"obsm['{key}'] not found; available: {list(adata.obsm.keys())}")
        arr = adata.obsm[key]
        arr = arr.to_numpy() if isinstance(arr, pd.DataFrame) else np.asarray(arr)
        return np.asarray(arr[:, :2], dtype=np.float64)
    if "," in spec:
        xs, ys = (s.strip() for s in spec.split(",", 1))
        cols = []
        for s in (xs, ys):
            if not s.startswith("obs/"):
                raise ValueError(f"coords column spec must be obs/<col>, got {s}")
            cols.append(np.asarray(adata.obs[s[4:]], dtype=np.float64))
        return np.stack(cols, axis=1)
    raise ValueError(f"unrecognised coords spec: {spec!r}")


def gene_names(adata: ad.AnnData, column: str | None) -> np.ndarray:
    names = adata.var[column] if column else adata.var_names
    names = pd.Index(np.asarray(names, dtype=str))
    if names.has_duplicates:
        names = ad.utils.make_index_unique(names, join=".")
    return np.asarray(names, dtype=str)


def load_sample(spec: SampleSpec) -> SampleInput:
    adata = read_anndata(spec.path, spec.table)
    coords = get_coords(adata, spec.coords)
    if coords.shape[0] != adata.n_obs:
        raise ValueError("coords length does not match n_obs")
    uns = dict(adata.uns) if adata.uns is not None else {}
    return SampleInput(adata=adata, coords=coords, gene_names=gene_names(adata, spec.gene_column), uns=uns)
