"""Automatic discovery: which obs columns to expose, and which images sit next to a sample."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import anndata as ad
import pandas as pd

from .config import FieldSpec, ImageSpec, MicronsSpec, SampleSpec, SegmentationSpec

MAX_LEVELS = 200
XENIUM_PIXEL_UM = 0.2125  # morphology pixel size when experiment.xenium does not say
AUTO_MORPHOLOGY_UM_PER_PX = 0.85  # discovered Xenium morphology is read at about this pixel size (4x the source), never whole
AUTO_MORPHOLOGY_FALLBACK_PX = 8192  # when the file's size cannot be read from its header
SKIP_COLUMNS = re.compile(r"^(sample_id|sample|key|barcode|cell_id|cell|index|in_tissue|array_row|array_col|exclude_.*|discard.*|qc_filter|.*_1|.*_2)$", re.I)
NUMERIC_KEEP = re.compile(r"count|sum|detected|percent|ratio|area|score|umi|genes|mito|nucleus|transcript|total|ncount|nfeature", re.I)


def is_textual(s: pd.Series) -> bool:
    """Categorical, object, string (pandas 2 `string`, pandas 3 `str`) or boolean: a column whose values are labels."""
    return isinstance(s.dtype, pd.CategoricalDtype) or s.dtype == object or str(s.dtype) in ("string", "str", "bool", "boolean")


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
        if is_textual(s):
            k = s.nunique(dropna=True)
            if 2 <= k <= MAX_LEVELS and k < n:
                out[field_id(str(col))] = str(col)
        elif pd.api.types.is_numeric_dtype(s) and NUMERIC_KEEP.search(str(col)):
            out[field_id(str(col))] = str(col)
    return out


def infer_field_spec(fid: str, adata: ad.AnnData, column: str) -> FieldSpec:
    s = adata.obs[column]
    categorical = is_textual(s)
    name = re.sub(r"[_\.]+", " ", column).strip()
    name = name[:1].upper() + name[1:]
    return FieldSpec(id=fid, name=name, type="categorical" if categorical else "continuous")


def shared_image(png: Path, limit: int = 64) -> bool:
    """Whether sibling sample folders (`../<other>/spatial/<same name>`) hold the very same file: one slide image that
    several sections were cut from (two Visium HD sections on one slide, say). Such an image is masked to each
    section's own cells, or the neighbour's tissue shows up under this sample with no cells on it."""
    try:
        here = png.resolve()
        root = here.parent.parent.parent
        size = here.stat().st_size
        mine = None
        for other in sorted(root.iterdir())[:limit]:
            cand = other / here.parent.name / here.name
            if other == here.parent.parent or not cand.is_file() or cand.stat().st_size != size:
                continue
            if mine is None:
                mine = hashlib.sha1(here.read_bytes()).hexdigest()
            if hashlib.sha1(cand.read_bytes()).hexdigest() == mine:
                return True
    except OSError:
        return False
    return False


def auto_images(sample: SampleSpec) -> tuple[list[ImageSpec], MicronsSpec | None]:
    """Images next to the sample path. Returns (images, microns override or None)."""
    d = Path(sample.path)
    d = d if d.is_dir() and not (d / ".zattrs").exists() and not (d / "zarr.json").exists() else d.parent
    if sample.kind != "spatial":
        return [], None
    # 1. OME-Zarr exported in the coordinate frame of the sample (level-0 pixels), e.g. image.ome.zarr
    for cand in [d / "image.ome.zarr", *visible(d.glob("*.ome.zarr"))]:
        if cand.is_dir() and ((cand / ".zattrs").exists() or (cand / "zarr.json").exists()):
            return [ImageSpec(id="he", name="H&E", path=cand, pixel_size="auto")], None
    # 2. SpaceRanger layout: spatial/tissue_hires_image.png + scalefactors (coords are full-res pixels)
    sp = d / "spatial"
    sf = sp / "scalefactors_json.json"
    if sf.exists():
        scale = json.loads(sf.read_text())
        # tissue_<id>_image.png with a tissue_<id>_scalef: hires first, then any other id, lowres last
        pngs = sorted(visible(sp.glob("tissue_*_image.png")), key=lambda q: (0 if "hires" in q.name else 2 if "lowres" in q.name else 1, q.name))
        for png in pngs:
            key = png.name.replace("tissue_", "tissue_", 1).replace("_image.png", "_scalef")
            if key in scale:
                spec = ImageSpec(id="he", name="H&E", path=png, pixel_size="auto", pixels_per_unit=float(scale[key]), mask=shared_image(png))
                return [spec], MicronsSpec(scalefactors_json=sf)
    if sf.exists():  # scale factors without an image (e.g. `convert` of an object whose image file was gone)
        return [], MicronsSpec(scalefactors_json=sf)
    # 3. Xenium morphology image: the 2D focus image (or the max projection), never the 3D morphology.ome.tif stack
    tif = xenium_morphology(d)
    if tif is not None:
        from .images import read_image_shape

        px = xenium_pixel_size(d)
        try:
            nch, h, w = read_image_shape(tif, rgb=False)
            # a pixel-size target, not a pixel count, so every section is equally sharp: 0.85 um/px is source level 2
            max_size = max(1, math.ceil(max(h, w) * px / AUTO_MORPHOLOGY_UM_PER_PX))
        except Exception:
            nch, max_size = 1, AUTO_MORPHOLOGY_FALLBACK_PX
        return [
            ImageSpec(
                id="morphology",
                name="DAPI" if nch == 1 else "Morphology",
                path=tif,
                kind="multichannel",
                pixel_size="auto",
                pixels_per_unit=1 / px,
                max_size=max_size,  # full resolution waits for the streaming converter (design/images-molecules-shapes.md)
            )
        ], None
    return [], None


def auto_segmentations(sample: SampleSpec) -> list[SegmentationSpec]:
    """The segmentations a sample compares against: the yaml's list, or, for `auto`, Xenium's nucleus boundaries
    found next to the polygons' cell_boundaries.parquet (the same run, the same frame)."""
    if isinstance(sample.segmentations, list):
        return sample.segmentations
    p = sample.polygons.path if sample.polygons is not None else None
    if p is not None and p.name == "cell_boundaries.parquet" and (p.with_name("nucleus_boundaries.parquet")).is_file():
        return [SegmentationSpec(id="nucleus", name="Nuclei", path=p.with_name("nucleus_boundaries.parquet"))]
    return []


def xenium_morphology(d: Path) -> Path | None:
    """The morphology image of a Xenium outs folder. XOA 2 and later write morphology_focus/ with one OME-TIFF per
    stain (morphology_focus_0000.ome.tif, or ch0000_dapi.ome.tif in XOA 4); the first file holds the multi-file
    series of all of them. XOA 1 writes morphology_focus.ome.tif, morphology_mip.ome.tif and the 3D z-stack
    morphology.ome.tif, which is not used."""
    folder = d / "morphology_focus"
    if folder.is_dir():
        files = visible(folder.glob("*.ome.tif"))
        if files:
            return files[0]
    for name in ("morphology_focus.ome.tif", "morphology_mip.ome.tif"):
        if (d / name).is_file():
            return d / name
    return None


def xenium_pixel_size(d: Path) -> float:
    """Microns per morphology pixel, from experiment.xenium when present."""
    meta = d / "experiment.xenium"
    try:
        raw = json.loads(meta.read_text()).get("pixel_size", XENIUM_PIXEL_UM)
    except (OSError, ValueError, TypeError, AttributeError):
        return XENIUM_PIXEL_UM
    if isinstance(raw, bool):
        return XENIUM_PIXEL_UM
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return XENIUM_PIXEL_UM
    return v if math.isfinite(v) and 0 < v < 10 else XENIUM_PIXEL_UM


def visible(paths) -> list[Path]:
    """Sorted, without hidden files: macOS writes `._<name>` sidecars next to every file it copies to exFAT, FAT or
    SMB drives, and they sort before the real file."""
    return sorted(p for p in paths if not p.name.startswith("."))
