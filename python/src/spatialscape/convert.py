"""`spatialscape convert`: an R object (.rds / .rda) -> the on-disk inputs the rest of the CLI reads.

Spatial objects (anything with spatialCoords) become one folder per sample in the SpaceRanger-like layout
that `images: auto` and the micron inference understand:

    <out>/<sample>/adata.h5ad                       X = assay, obs = chosen colData, obsm/spatial = spatialCoords
    <out>/<sample>/spatial/tissue_<id>_image.png    from imgData (loaded rasters, or stored image files)
    <out>/<sample>/spatial/scalefactors_json.json   tissue_<id>_scalef + spot_diameter_fullres or microns_per_pixel

Objects without spatialCoords (snRNA-seq references) become one <out>/<stem>.h5ad with obsm/X_umap.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sp

from .rds import RExperiment, RImage, read_experiment

Log = Callable[[str], None]
VISIUM_SPOT_UM = 55.0
VISIUM_SPACING_UM = 100.0
EMBEDDING_PREFERENCE = ("UMAP", "umap", "X_umap", "UMAP-HARMONY", "UMAP_HARMONY", "UMAP.HARMONY")


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name))


def _pick_obs(obs: pd.DataFrame, cols: list[str] | None) -> pd.DataFrame:
    if cols is None:
        return obs
    missing = [c for c in cols if c not in obs.columns]
    if missing:
        raise KeyError(f"colData column(s) not found: {', '.join(missing)}; available: {', '.join(obs.columns)}")
    return obs[cols]


def _anndata(x: RExperiment, assay: str, rows: np.ndarray | None, cols: list[str] | None) -> ad.AnnData:
    if assay not in x.assays:
        raise KeyError(f"assay {assay!r} not found; available: {', '.join(x.assays)}")
    m = x.assays[assay]
    if rows is not None:
        m = m[:, rows]
    X = m.T.tocsr() if sp.issparse(m) else np.ascontiguousarray(np.asarray(m).T)
    obs = _pick_obs(x.obs, cols)
    if rows is not None:
        obs = obs.iloc[rows]
    a = ad.AnnData(X=X, obs=obs.copy(), var=x.var.copy())
    a.var_names_make_unique()
    return a


def _write_image(img: RImage, dest: Path) -> bool:
    import imageio.v3 as iio

    if img.rgb is not None:
        iio.imwrite(dest, img.rgb)
        return True
    if img.path and Path(img.path).exists():
        iio.imwrite(dest, iio.imread(img.path)[..., :3])
        return True
    return False


def convert_object(
    path: str | Path,
    out: str | Path,
    *,
    assay: str = "logcounts",
    cols: list[str] | None = None,
    sample_col: str = "sample_id",
    embedding: str | None = None,
    microns_per_pixel: float | None = None,
    spot_um: float = VISIUM_SPOT_UM,
    spacing_um: float = VISIUM_SPACING_UM,
    object_name: str | None = None,
    log: Log = print,
) -> list[Path]:
    """Convert one R object. Returns the h5ad files written."""
    path = Path(path)
    out = Path(out)
    log(f"reading {path} ...")
    x = read_experiment(path, object_name=object_name)
    log(f"  {x.class_name}: {x.n_vars} genes x {x.n_obs} cells, assays {', '.join(x.assays)}" + (f", {len(x.images)} image(s)" if x.images else ""))
    written: list[Path] = []
    if x.class_name != "SpatialExperiment" or x.spatial is None:
        # ---- embedding (snRNA-seq reference)
        name = embedding or next((k for k in EMBEDDING_PREFERENCE if k in x.reduced_dims), next(iter(x.reduced_dims), None))
        if name is None or name not in x.reduced_dims:
            raise ValueError(f"no 2-D embedding found; reducedDims are: {', '.join(x.reduced_dims) or 'none'} (set --embedding)")
        a = _anndata(x, assay, None, cols)
        a.obsm["X_umap"] = np.asarray(x.reduced_dims[name][:, :2], dtype=np.float32)
        out.mkdir(parents=True, exist_ok=True)
        dest = out / f"{_safe(path.stem)}.h5ad"
        a.write_h5ad(dest)
        log(f"  wrote {dest}  ({a.n_obs} cells, embedding {name!r} -> obsm/X_umap)")
        return [dest]
    # ---- spatial: one folder per sample
    if sample_col not in x.obs.columns:
        raise KeyError(f"sample column {sample_col!r} not in colData; available: {', '.join(x.obs.columns)}")
    sample_values = x.obs[sample_col].astype(str).to_numpy()
    for s in pd.unique(sample_values):
        rows = np.flatnonzero(sample_values == s)
        d = out / _safe(s)
        (d / "spatial").mkdir(parents=True, exist_ok=True)
        a = _anndata(x, assay, rows, cols)
        coords = x.spatial[rows]
        a.obsm["spatial"] = np.asarray(coords, dtype=np.float64)
        sf: dict[str, float] = {}
        for img in [i for i in x.images if i.sample_id == s]:
            if _write_image(img, d / "spatial" / f"tissue_{_safe(img.image_id)}_image.png"):
                sf[f"tissue_{_safe(img.image_id)}_scalef"] = img.scale_factor
            else:
                log(f"  warning: image {img.image_id!r} of sample {s} could not be written ({img.path or 'no pixels in the object'})")
        if microns_per_pixel is not None:
            sf["microns_per_pixel"] = float(microns_per_pixel)
        elif len(rows) > 1:
            from scipy.spatial import cKDTree

            nn = cKDTree(coords).query(coords, k=2)[0][:, 1]
            sf["spot_diameter_fullres"] = float(np.median(nn) * spot_um / spacing_um)
        (d / "spatial" / "scalefactors_json.json").write_text(json.dumps(sf, indent=1))
        dest = d / "adata.h5ad"
        a.write_h5ad(dest)
        written.append(dest)
        log(f"  wrote {dest}  ({a.n_obs} cells, {len([k for k in sf if k.startswith('tissue_')])} image(s))")
    return written
