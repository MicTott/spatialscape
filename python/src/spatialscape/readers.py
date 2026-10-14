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
    if spec.subset is not None:
        col = spec.subset.column
        if col not in adata.obs:
            raise KeyError(f"sample {spec.id}: subset column {col!r} not found; obs columns: {', '.join(map(str, adata.obs.columns))}")
        keep = adata.obs[col].astype(str).isin([str(v) for v in spec.subset.values]).to_numpy()
        if not keep.any():
            raise ValueError(f"sample {spec.id}: subset {col} in {spec.subset.values} matches no observations")
        adata = adata[keep].copy()
    coords = get_coords(adata, spec.coords)
    if coords.shape[0] != adata.n_obs:
        raise ValueError("coords length does not match n_obs")
    uns = dict(adata.uns) if adata.uns is not None else {}
    return SampleInput(adata=adata, coords=coords, gene_names=gene_names(adata, spec.gene_column), uns=uns)


@dataclass
class Peek:
    """What `init` and `inspect` need from a sample file without reading its matrix."""

    obs: pd.DataFrame
    obsm: list[str]
    layers: list[str]
    n_vars: int


def _table_dir(path: Path, table: str | None) -> Path:
    tables = path / "tables"
    if table is None:
        keys = sorted(p.name for p in tables.iterdir() if p.is_dir())
        if len(keys) != 1:
            raise ValueError(f"SpatialData store has tables {keys}; set `table:`")
        table = keys[0]
    return tables / table


def _peek_group(g, read_elem) -> Peek:
    obs = read_elem(g["obs"])
    obsm = list(g["obsm"].keys()) if "obsm" in g else []
    layers = [k for k in (g["layers"].keys() if "layers" in g else []) if k]
    n_vars = len(read_elem(g["var"])) if "var" in g else 0
    return Peek(obs=obs, obsm=obsm, layers=layers, n_vars=n_vars)


def peek(path: Path, table: str | None = None) -> Peek:
    """Read `obs` plus the `obsm` and layer keys of an h5ad / AnnData Zarr / SpatialData table; the matrix stays on disk."""
    from anndata.io import read_elem

    path = Path(path)
    if path.is_file():
        if path.suffix != ".h5ad":
            raise ValueError(f"unsupported file type: {path}")
        import h5py

        with h5py.File(path, "r") as f:
            return _peek_group(f, read_elem)
    if not path.is_dir():
        raise FileNotFoundError(path)
    import zarr

    target = _table_dir(path, table) if (path / "tables").is_dir() else path
    return _peek_group(zarr.open_group(str(target), mode="r"), read_elem)
