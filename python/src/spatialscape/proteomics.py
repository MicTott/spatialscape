"""spatialproteomics objects (Meyer-Bender et al. 2026: an xarray Dataset saved as Zarr) read as a sample.

The object holds one multiplexed image and everything derived from it, on shared dimensions:

    _image / _image_raw   (channels, y, x)      the stains, processed and as scanned
    _segmentation         (y, x)                the label mask, one integer per cell
    _intensity            (cells, channels)     a marker's summary per cell (mean, arcsinh ...): the expression layer
    _obs                  (cells, features)     centroids, `_labels`, `_neighborhoods`, `<marker>_binarized`, graph measures
    _la_properties        (labels, la_props)    cell type names and colours; _nh_properties the same for neighbourhoods
    _la_layers            (cells, la_features)  the cell type at every level of a gating tree (labels_0, labels_1 ...)

What comes out is an AnnData the build already understands: X = the intensities (channels as features), obs with
readable categoricals (names instead of label numbers, "positive"/"negative" instead of 1/0), `obsm["spatial"]` =
the centroids in pixels, and the source's colours in `uns["<column>_colors"]`. The image and the mask stay on disk:
the yaml points `images:` at `<object>/_image_raw` and `polygons: { labels: <object>/_segmentation }`.
"""

from __future__ import annotations

from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import zarr

LABELS = "_labels"
NEIGHBORHOODS = "_neighborhoods"
CENTROID_Y, CENTROID_X = "centroid-0", "centroid-1"  # skimage order: row, column
BINARIZED = "_binarized"
IMAGE_KEYS = ("_image_raw", "_image")


def is_spatialproteomics(path: Path) -> bool:
    """A directory with the object's `_obs` table and an image, and the `cells` coordinate they share."""
    path = Path(path)
    if not path.is_dir() or not (path / "_obs").is_dir() or not (path / "cells").is_dir():
        return False
    return any((path / k).is_dir() for k in IMAGE_KEYS)


def image_key(path: Path) -> str | None:
    """The image to draw: the scan as recorded when the object keeps it, else the processed one."""
    return next((k for k in IMAGE_KEYS if (Path(path) / k).is_dir()), None)


def _strings(arr) -> list[str]:
    return [str(v) for v in np.asarray(arr[:]).tolist()]


def _properties(g: zarr.Group, table: str, ids_key: str, props_key: str) -> tuple[dict[int, str], dict[str, str]]:
    """id -> name and name -> colour from a (ids, props) table with `_name` and `_color` columns."""
    if table not in g or ids_key not in g or props_key not in g:
        return {}, {}
    props = _strings(g[props_key])
    ids = [int(v) for v in np.asarray(g[ids_key][:]).tolist()]
    rows = np.asarray(g[table][:], dtype=object)
    name_col = props.index("_name") if "_name" in props else None
    color_col = props.index("_color") if "_color" in props else None
    names = {i: (str(rows[k, name_col]) if name_col is not None else str(i)) for k, i in enumerate(ids)}
    colors = {names[i]: str(rows[k, color_col]) for k, i in enumerate(ids)} if color_col is not None else {}
    return names, colors


def _named(values: np.ndarray, names: dict[int, str]) -> pd.Categorical:
    """Integer ids as a categorical of their names, in id order; an id without a name keeps its number."""
    ids = sorted({int(v) for v in values if np.isfinite(v)})
    cats = [names.get(i, str(i)) for i in ids]
    lookup = dict(zip(ids, cats, strict=True))
    return pd.Categorical([lookup.get(int(v)) if np.isfinite(v) else None for v in values], categories=cats)


def read_obs(path: Path) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """The per-cell table with readable categoricals, and the colours the object gives some of them."""
    g = zarr.open_group(str(path), mode="r")
    cells = _strings(g["cells"])
    features = _strings(g["features"])
    obs = pd.DataFrame(np.asarray(g["_obs"][:]), columns=features, index=pd.Index(cells, name=None))
    colors: dict[str, list[str]] = {}
    label_names, label_colors = _properties(g, "_la_properties", "labels", "la_props")
    if LABELS in obs:
        cat = _named(obs[LABELS].to_numpy(), label_names)
        obs["labels"] = cat
        colors["labels"] = [label_colors.get(c, "") for c in cat.categories]
        obs = obs.drop(columns=[LABELS])
    nh_names, nh_colors = _properties(g, "_nh_properties", "neighborhoods", "nh_props")
    if NEIGHBORHOODS in obs:
        cat = _named(obs[NEIGHBORHOODS].to_numpy(), nh_names)
        obs["neighborhoods"] = cat
        colors["neighborhoods"] = [nh_colors.get(c, "") for c in cat.categories]
        obs = obs.drop(columns=[NEIGHBORHOODS])
    for col in [c for c in obs.columns if c.endswith(BINARIZED)]:
        v = obs[col].to_numpy()
        obs[col] = pd.Categorical(np.where(v > 0, "positive", "negative"), categories=["negative", "positive"])
    if "_la_layers" in g and "la_features" in g:  # the gating tree's levels, coarse to fine
        layers = np.asarray(g["_la_layers"][:], dtype=object)
        for j, name in enumerate(_strings(g["la_features"])):
            level = pd.Series(layers[:, j]).astype(str)
            cats = list(dict.fromkeys(level))  # first seen
            obs[name] = pd.Categorical(level.to_numpy(), categories=cats)
            colors[name] = [label_colors.get(c, "") for c in cats]
    return obs, {k: v for k, v in colors.items() if any(v)}


def read_spatialproteomics(path: Path) -> ad.AnnData:
    """The object as an AnnData: intensities as X, the table as obs, centroids as `obsm["spatial"]` (pixels)."""
    path = Path(path)
    g = zarr.open_group(str(path), mode="r")
    if "_intensity" not in g:
        raise ValueError(f"{path}: the object has no `_intensity` layer (per-cell marker summaries); run `pp.add_quantification` in spatialproteomics first")
    obs, colors = read_obs(path)
    if CENTROID_X not in obs or CENTROID_Y not in obs:
        raise ValueError(f"{path}: `_obs` has no {CENTROID_Y!r}/{CENTROID_X!r} columns; run `pp.add_observations('centroid')` first")
    X = np.asarray(g["_intensity"][:], dtype=np.float32)
    channels = _strings(g["channels"])
    if X.shape != (len(obs), len(channels)):
        raise ValueError(f"{path}: `_intensity` is {X.shape}, expected ({len(obs)}, {len(channels)})")
    var = pd.DataFrame(index=pd.Index(channels, name=None))
    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.obsm["spatial"] = obs[[CENTROID_X, CENTROID_Y]].to_numpy(dtype=np.float64)
    for col, cols in colors.items():
        adata.uns[f"{col}_colors"] = cols
    key = image_key(path)
    adata.uns["spatialproteomics"] = {"image": key or "", "segmentation": "_segmentation" if "_segmentation" in g else ""}
    return adata
