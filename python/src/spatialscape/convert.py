"""R objects (.rds / .rda) as build inputs: converted once into a cache next to the bundle, then expanded into samples.

A `samples:` entry whose `path` is an R object is converted on the first `build` into
`<bundles>/.cache/<dataset id>/<key>/`, where `<key>` fingerprints the file (path, size, mtime) and the
conversion settings (sample_col, assay, embedding, object). The cache holds every colData column, so editing
`fields:` in the yaml never triggers a reconversion; a re-saved object or a changed `assay:` makes a new key.

Spatial objects (anything with spatialCoords) become one folder per sample in the SpaceRanger-like layout
that `images: auto` and the micron inference understand:

    <key>/<sample>/adata.h5ad                       X = assay, obs = all colData, obsm/spatial = spatialCoords
    <key>/<sample>/spatial/tissue_<id>_image.png    from imgData (loaded rasters, or stored image files)
    <key>/<sample>/spatial/scalefactors_json.json   tissue_<id>_scalef + a spot diameter measured from the spacing

Objects without spatialCoords (snRNA-seq references) become <key>/<stem>/adata.h5ad with obsm/X_umap.
Either way the entry is rewritten into `glob: <key>/*/adata.h5ad` and expanded like any other glob entry.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sp

from .config import DatasetConfig, RObjectEntry, _merged_entry, config_from_raw
from .rds import RExperiment, RImage, read_experiment

Log = Callable[[str], None]
CONVERT_VERSION = 3  # bump when the cache layout or its contents change for the same object (3: feature names from the assay dimnames)
VISIUM_SPOT_UM = 55.0
VISIUM_SPACING_UM = 100.0
EMBEDDING_PREFERENCE = ("UMAP", "umap", "X_umap", "UMAP-HARMONY", "UMAP_HARMONY", "UMAP.HARMONY")
LAYER_ALIASES = {"logcounts": "data", "normcounts": "data"}  # Bioconductor assay names -> Seurat layer names


def pick_embedding(keys) -> str | None:
    """The reducedDim / reduction to draw when none is named: the usual UMAP names, else anything containing
    "umap" (a joint `wnn.umap` before a per-modality one), else t-SNE, else the first."""
    keys = list(keys)
    for k in EMBEDDING_PREFERENCE:
        if k in keys:
            return k
    umaps = [k for k in keys if "umap" in k.lower()]
    if umaps:
        return next((k for k in umaps if "wnn" in k.lower()), umaps[0])
    return next((k for k in keys if "tsne" in k.lower()), keys[0] if keys else None)
INDEX = "index.json"


@dataclass
class SourceStatus:
    """What `build` found for one R object entry."""

    entry: RObjectEntry
    key: str | None
    cache_dir: Path | None
    state: str  # cached | converted | pending | missing
    samples: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return {
            "cached": f"cached ({len(self.samples)} sample{'s' if len(self.samples) != 1 else ''})",
            "converted": f"converted ({len(self.samples)} sample{'s' if len(self.samples) != 1 else ''})",
            "pending": "not converted yet; `build` converts it, then lists its samples",
            "missing": "file not found",
        }[self.state]


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name))


def cache_key(entry: RObjectEntry) -> str:
    """Identity of a conversion: the file (path, size, mtime) and the settings that change its output."""
    st = entry.path.stat()
    parts = [str(entry.path.resolve()), st.st_size, st.st_mtime_ns, entry.sample_col, entry.assay, entry.embedding, entry.object, CONVERT_VERSION]
    return hashlib.sha1(json.dumps(parts).encode()).hexdigest()[:16]


def read_index(cache_dir: Path) -> dict | None:
    p = Path(cache_dir) / INDEX
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _anndata(x: RExperiment, assay: str, rows: np.ndarray | None) -> ad.AnnData:
    layer = assay
    if layer not in x.assays:
        alias = LAYER_ALIASES.get(assay)
        if x.class_name == "Seurat" and alias in x.assays:
            layer = alias
        else:
            raise KeyError(f"assay {assay!r} not found; available: {', '.join(x.assays)}")
    mats = [x.assays[layer]]
    var = x.var.copy()
    for fs in x.feature_sets:  # a Seurat object's other assays, as prefixed features under the genes
        fl = layer if layer in fs.assays else "data" if "data" in fs.assays else next(iter(fs.assays))
        mats.append(fs.assays[fl])
        v = fs.var.copy()
        v.index = pd.Index([f"{fs.prefix}{i}" for i in v.index.astype(str)])
        var = pd.concat([var, v])
    if len(mats) > 1:
        m = sp.vstack([a if sp.issparse(a) else sp.csc_matrix(np.asarray(a)) for a in mats]).tocsc()
    else:
        m = mats[0]
    if rows is not None:
        m = m[:, rows]
    X = m.T.tocsr() if sp.issparse(m) else np.ascontiguousarray(np.asarray(m).T)
    obs = x.obs if rows is None else x.obs.iloc[rows]
    for c in var.columns:
        if var[c].dtype == object:
            var[c] = var[c].astype("category")
    if var.index.has_duplicates:  # duplicate symbols get -1, -2 suffixes (what var_names_make_unique would do)
        var.index = ad.utils.make_index_unique(pd.Index(var.index.astype(str)), join="-")
    return ad.AnnData(X=X, obs=obs.copy(), var=var)


def _write_image(img: RImage, dest: Path) -> bool:
    import imageio.v3 as iio

    if img.rgb is not None:
        iio.imwrite(dest, img.rgb)
        return True
    if img.path and Path(img.path).exists():
        arr = np.asarray(iio.imread(img.path))
        if arr.ndim == 2:  # grayscale: three equal planes, never a 3-pixel-wide slice
            arr = np.stack([arr, arr, arr], axis=-1)
        iio.imwrite(dest, arr[..., :3])
        return True
    return False


def _write_spatial(x: RExperiment, out: Path, *, assay: str, sample_col: str, log: Log) -> list[str]:
    if sample_col not in x.obs.columns:
        raise KeyError(f"sample column {sample_col!r} not in colData; available: {', '.join(x.obs.columns)}")
    sample_values = x.obs[sample_col].astype(str).to_numpy()
    names: list[str] = []
    for s in pd.unique(sample_values):
        rows = np.flatnonzero(sample_values == s)
        d = out / _safe(s)
        (d / "spatial").mkdir(parents=True, exist_ok=True)
        a = _anndata(x, assay, rows)
        coords = x.spatial[rows]
        a.obsm["spatial"] = np.asarray(coords, dtype=np.float64)
        sf: dict[str, float] = {}
        for img in [i for i in x.images if i.sample_id == s]:
            if _write_image(img, d / "spatial" / f"tissue_{_safe(img.image_id)}_image.png"):
                sf[f"tissue_{_safe(img.image_id)}_scalef"] = img.scale_factor
            else:
                log(f"  warning: image {img.image_id!r} of sample {s} could not be written ({img.path or 'no pixels in the object'})")
        finite = coords[np.isfinite(coords).all(axis=1)]
        if len(finite) > 1:  # Visium rule: neighbouring spots are 100 um apart, a spot is 55 um wide
            from scipy.spatial import cKDTree

            nn = cKDTree(finite).query(finite, k=2)[0][:, 1]
            spacing = float(np.median(nn))
            if spacing > 0:
                sf["spot_diameter_fullres"] = spacing * VISIUM_SPOT_UM / VISIUM_SPACING_UM
            else:
                log(f"  warning: {d.name}: coordinates repeat (median spot spacing 0); set `microns:` for this sample")
        (d / "spatial" / "scalefactors_json.json").write_text(json.dumps(sf, indent=1))
        a.write_h5ad(d / "adata.h5ad")
        names.append(d.name)
        log(f"  {d.name}: {a.n_obs} cells, {len([k for k in sf if k.startswith('tissue_')])} image(s)")
    ids = {i.image_id for i in x.images}
    if ids and ids <= {"lowres"}:
        log("  note: the object holds only the low-resolution H&E (SpaceRanger's tissue_lowres_image, about 600-1200 px wide)."
            " For detail, point `images:` in the yaml at tissue_hires_image.png or the full-resolution scan of each sample.")
    return names


def _write_embedding(x: RExperiment, out: Path, *, assay: str, embedding: str | None, name: str, log: Log) -> tuple[str, str]:
    key = embedding or pick_embedding(x.reduced_dims)
    if key is None or key not in x.reduced_dims:
        raise ValueError(f"no 2-D embedding found; reducedDims are: {', '.join(x.reduced_dims) or 'none'} (set `embedding:` on the entry)")
    a = _anndata(x, assay, None)
    a.obsm["X_umap"] = np.asarray(x.reduced_dims[key][:, :2], dtype=np.float32)
    d = out / _safe(name)
    d.mkdir(parents=True, exist_ok=True)
    a.write_h5ad(d / "adata.h5ad")
    log(f"  {d.name}: {a.n_obs} cells, embedding {key!r} -> obsm/X_umap")
    return d.name, key


def write_cache(entry: RObjectEntry, cache_root: Path, *, log: Log = print) -> dict:
    """Convert one R object into `cache_root/<key>/` (written to a temporary folder first). Returns the index."""
    key = cache_key(entry)
    dest = Path(cache_root) / key
    tmp = Path(cache_root) / f"{key}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    log(f"reading {entry.path} (the whole object is parsed; about as long as loading it in R)")
    x = read_experiment(entry.path, object_name=entry.object)
    spatial = x.class_name == "SpatialExperiment" and x.spatial is not None
    what = f"{x.class_name} ({x.assay_name})" if x.assay_name else x.class_name
    log(f"  {what}: {x.n_vars} genes x {x.n_obs} cells, assays {', '.join(x.assays)}" + (f", {len(x.images)} image(s)" if x.images else ""))
    for fs in x.feature_sets:
        log(f"  + {fs.name}: {len(fs.var):,} features as {fs.prefix!r}")
    for note in x.notes:
        log(f"  note: {note}")
    used_embedding = None
    if spatial:
        samples = _write_spatial(x, tmp, assay=entry.assay, sample_col=entry.sample_col, log=log)
    else:
        name, used_embedding = _write_embedding(x, tmp, assay=entry.assay, embedding=entry.embedding, name=entry.path.stem, log=log)
        samples = [name]
    st = entry.path.stat()
    index = {
        "source": str(entry.path),
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "sample_col": entry.sample_col,
        "assay": entry.assay,
        "embedding": used_embedding,
        "object": entry.object,
        "class": x.class_name,
        "spatial": spatial,
        "assays": list(x.assays),
        "feature_sets": [{"name": fs.name, "prefix": fs.prefix, "features": len(fs.var)} for fs in x.feature_sets],
        "fragments": [f.path for f in x.fragments],
        "samples": samples,
        "cells": x.n_obs,
        "converted": datetime.now(UTC).isoformat(timespec="seconds"),
        "version": CONVERT_VERSION,
    }
    (tmp / INDEX).write_text(json.dumps(index, indent=1))
    if dest.exists():
        shutil.rmtree(dest)
    tmp.rename(dest)
    return index


def prune_cache(cache_root: Path, keep: set[str]) -> list[Path]:
    """Remove cache folders no entry references any more (old keys, leftover temporary folders)."""
    cache_root = Path(cache_root)
    if not cache_root.is_dir():
        return []
    gone: list[Path] = []
    for p in cache_root.iterdir():
        if p.is_dir() and p.name not in keep:
            shutil.rmtree(p)
            gone.append(p)
    return gone


def _glob_entry(entry: RObjectEntry, cache_dir: Path, index: dict, raw: dict) -> dict:
    """The R entry rewritten as a glob over its cache folder, with defaults that depend on what the object is.
    Those defaults sit below `defaults` / `platforms` / the entry itself, so anything the yaml says wins."""
    e = dict(entry.template)
    e["glob"] = str(cache_dir / "*" / "adata.h5ad")

    def merged() -> dict:
        return _merged_entry(e, raw)

    if not index.get("spatial"):
        if "platform" not in merged():
            e["platform"] = "snrnaseq"
        for k, v in (("kind", "embedding"), ("coords", "obsm/X_umap")):
            if k not in merged():
                e[k] = v
    elif merged().get("platform") in ("xenium", "merfish") and "microns" not in merged():
        e["microns"] = {"already_microns": True}  # the cache's spot-spacing rule is for Visium only
    return e


def expand_r_objects(cfg: DatasetConfig, cache_root: Path, *, convert: bool, log: Log = print) -> tuple[DatasetConfig, list[SourceStatus]]:
    """Replace every R object entry by the samples in its cache, converting first when `convert` is set.
    Without `convert` (a dry run) uncached objects are reported as pending and left out."""
    if not cfg.r_objects:
        return cfg, []
    if cfg.path is None:
        raise ValueError("R object entries need a config loaded from a file")
    cache_root = Path(cache_root)
    raw_samples: list[dict | None] = list(cfg.raw.get("samples") or [])
    statuses: list[SourceStatus] = []
    keep: set[str] = set()
    for entry in cfg.r_objects:
        if not entry.path.exists():
            if convert:
                raise FileNotFoundError(str(entry.path))
            statuses.append(SourceStatus(entry, None, None, "missing"))
            raw_samples[entry.index] = None
            continue
        key = cache_key(entry)
        d = cache_root / key
        index = read_index(d)
        state = "cached"
        if index is None:
            if not convert:
                statuses.append(SourceStatus(entry, key, d, "pending"))
                raw_samples[entry.index] = None
                continue
            log(f"converting {entry.path} -> {d}")
            index = write_cache(entry, cache_root, log=log)
            state = "converted"
        keep.add(key)
        raw_samples[entry.index] = _glob_entry(entry, d, index, cfg.raw)
        statuses.append(SourceStatus(entry, key, d, state, list(index.get("samples", []))))
    if convert:
        for p in prune_cache(cache_root, keep):
            log(f"removed stale cache {p}")
    new_raw = {**cfg.raw, "samples": [s for s in raw_samples if s is not None]}
    new_cfg = config_from_raw(new_raw, cfg.path, original=cfg.raw)
    new_cfg._r_objects = list(cfg.r_objects)
    return new_cfg, statuses

