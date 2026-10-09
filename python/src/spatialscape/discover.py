"""Automatic discovery: which obs columns to expose, and which images sit next to a sample."""
from __future__ import annotations

import json
import re
from pathlib import Path

import anndata as ad
import pandas as pd

from .config import FieldSpec, ImageSpec, MicronsSpec, SampleSpec

MAX_LEVELS = 200
SKIP_COLUMNS = re.compile(r"^(sample_id|sample|key|barcode|cell_id|cell|index|in_tissue|array_row|array_col|exclude_.*|discard.*|qc_filter|.*_1|.*_2)$", re.I)
NUMERIC_KEEP = re.compile(r"count|sum|detected|percent|ratio|area|score|umi|genes|mito|nucleus|transcript|total|ncount|nfeature", re.I)


def field_id(column: str) -> str:
    fid = re.sub(r"[^A-Za-z0-9]+", "_", column).strip("_").lower()
    return fid or "field"


def auto_fields(adata: ad.AnnData, sample: SampleSpec) -> dict[str, str]:
    """field id -> obs column for every categorical (2..MAX_LEVELS levels) and QC-like numeric column."""
    out: dict[str, str] = {}
    n = adata.n_obs
    for col in adata.obs.columns:
        if SKIP_COLUMNS.match(str(col)):
            continue
        s = adata.obs[col]
        if isinstance(s.dtype, pd.CategoricalDtype) or s.dtype == object or str(s.dtype) in ("string", "bool", "boolean"):
            k = s.nunique(dropna=True)
            if 2 <= k <= MAX_LEVELS and k < n:
                out[field_id(str(col))] = str(col)
        elif pd.api.types.is_numeric_dtype(s) and NUMERIC_KEEP.search(str(col)):
            out[field_id(str(col))] = str(col)
    return out


def infer_field_spec(fid: str, adata: ad.AnnData, column: str) -> FieldSpec:
    s = adata.obs[column]
    categorical = isinstance(s.dtype, pd.CategoricalDtype) or s.dtype == object or str(s.dtype) in ("string", "bool", "boolean")
    name = re.sub(r"[_\.]+", " ", column).strip()
    name = name[:1].upper() + name[1:]
    return FieldSpec(id=fid, name=name, type="categorical" if categorical else "continuous")


def auto_images(sample: SampleSpec) -> tuple[list[ImageSpec], MicronsSpec | None]:
    """Images next to the sample path. Returns (images, microns override or None)."""
    d = Path(sample.path)
    d = d if d.is_dir() and not (d / ".zattrs").exists() and not (d / "zarr.json").exists() else d.parent
    if sample.kind != "spatial":
        return [], None
    # 1. OME-Zarr exported in the coordinate frame of the sample (level-0 pixels), e.g. image.ome.zarr
    for cand in [d / "image.ome.zarr", *sorted(d.glob("*.ome.zarr"))]:
        if cand.is_dir() and ((cand / ".zattrs").exists() or (cand / "zarr.json").exists()):
            return [ImageSpec(id="he", name="H&E", path=cand, pixel_size="auto")], None
    # 2. SpaceRanger layout: spatial/tissue_hires_image.png + scalefactors (coords are full-res pixels)
    sp = d / "spatial"
    sf = sp / "scalefactors_json.json"
    for png in ("tissue_hires_image.png", "tissue_lowres_image.png"):
        if (sp / png).exists() and sf.exists():
            scale = json.loads(sf.read_text())
            key = "tissue_hires_scalef" if "hires" in png else "tissue_lowres_scalef"
            if key in scale:
                return [ImageSpec(id="he", name="H&E", path=sp / png, pixel_size="auto", pixels_per_unit=float(scale[key]))], MicronsSpec(scalefactors_json=sf)
    if sf.exists():  # scale factors without an image (e.g. `convert` of an object whose image file was gone)
        return [], MicronsSpec(scalefactors_json=sf)
    # 3. Xenium morphology image
    for tif in sorted(d.glob("morphology_focus*.ome.tif")) + sorted(d.glob("morphology*.ome.tif")):
        return [ImageSpec(id="dapi", name="DAPI", path=tif, kind="multichannel", pixel_size="auto", pixels_per_unit=1 / 0.2125)], None
    return [], None
