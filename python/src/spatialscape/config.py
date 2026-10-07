"""Input schema: the dataset.yaml a contributor writes."""

from __future__ import annotations

import glob as _glob
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .manifest import LayoutMode, Platform, SampleKind


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MicronsSpec(_Model):
    """How to convert the coordinate units of `coords` into microns.

    Exactly one of the explicit options may be set. With none set, `auto` is used:
    xenium/merfish -> already microns; visium -> uns["spot_nn_spacing_level0_px"] or
    uns["spatial"][...]["scalefactors"]; embedding -> rescaled to `extent`.
    """

    already_microns: bool = False
    microns_per_unit: float | None = None
    spot_diameter_fullres: float | None = None  # Visium: 55 um spot diameter in coord units
    spot_spacing: float | None = None  # Visium: 100 um center-to-center in coord units
    scalefactors_json: Path | None = None  # SpaceRanger scalefactors_json.json (fullres coords)

    @model_validator(mode="after")
    def _one_of(self):
        n = sum(
            [
                self.already_microns,
                self.microns_per_unit is not None,
                self.spot_diameter_fullres is not None,
                self.spot_spacing is not None,
                self.scalefactors_json is not None,
            ]
        )
        if n > 1:
            raise ValueError("microns: set at most one option")
        return self


class TransformSpec(_Model):
    flip: Literal["none", "x", "y"] = "none"
    rotate: Literal[0, 90, 180, 270] = 0


class ExpressionSpec(_Model):
    layer: str = "X"
    normalized: Literal["auto", "lognorm", "counts"] = "auto"
    keep_f16: bool = False


class ImageChannelSpec(_Model):
    name: str
    color: str = "#ffffff"
    window: tuple[float, float] | None = None


class ImageSpec(_Model):
    id: str = "image"
    name: str = "Image"
    path: Path
    kind: Literal["rgb", "multichannel"] = "rgb"
    # um per level-0 pixel; "auto" means the image shares the coordinate frame of `coords`
    pixel_size: float | Literal["auto"] = "auto"
    # image pixels per coordinate unit (e.g. tissue_hires_scalef when coords are fullres px)
    pixels_per_unit: float = 1.0
    translate: tuple[float, float] = (0.0, 0.0)  # um, applied after everything else
    channels: list[ImageChannelSpec] | None = None
    default_opacity: float = 1.0
    max_size: int | None = None  # optionally downsample level 0 to at most this many px per side


class PolygonSpec(_Model):
    """Per-cell boundary polygons, from a long-format parquet file (`path`: one row per vertex) or from an
    `obsm` array of shape (n_obs, n_vertices, 2) inside the object. Vertex coordinates share the frame of
    `coords`; set `affine` when the boundary file is in a different frame (e.g. the object's coordinates were
    transposed after segmentation)."""

    path: Path | None = None
    obsm: str | None = None
    id_column: str = "cell_id"
    x_column: str = "vertex_x"
    y_column: str = "vertex_y"
    max_vertices: int = 24
    # (a, b, c, d, e, f): x' = a*x + b*y + c ; y' = d*x + e*y + f, applied to the raw vertices first.
    # transpose = [0, 1, 0, 1, 0, 0]; anti-transpose with extents = [0, -1, Ymax, -1, 0, Xmax].
    affine: tuple[float, float, float, float, float, float] | None = None

    @model_validator(mode="after")
    def _one_source(self):
        if (self.path is None) == (self.obsm is None):
            raise ValueError("polygons: set exactly one of `path` or `obsm`")
        return self


class FieldMap(_Model):
    """Long form of a field mapping: `{column, scale}`. `scale` multiplies a numeric column (e.g. 100 to turn a
    ratio into a percent) so one field can be shared by samples that store the same quantity in different units."""

    column: str
    scale: float = 1.0


class SampleSpec(_Model):
    """One sample. In dataset.yaml an entry may instead carry `glob:` and templated strings
    ("{name}", "{stem}", "{dir}", "{i}") that expand into one SampleSpec per match; `platforms.<platform>`
    and `defaults` blocks fill in keys the entry omits."""

    id: str
    name: str | None = None
    platform: Platform
    kind: SampleKind = "spatial"
    group: str | None = None
    path: Path
    table: str | None = None  # SpatialData table key
    coords: str = "obsm/spatial"  # "obsm/<key>" or "obs/<xcol>,obs/<ycol>"
    expression: ExpressionSpec = Field(default_factory=ExpressionSpec)
    microns: MicronsSpec = Field(default_factory=MicronsSpec)
    transform: TransformSpec = Field(default_factory=TransformSpec)
    # field id -> obs column (or {column, scale}), or "auto" to expose every categorical (<= 200 levels) and
    # QC-like numeric column. Long-form entries are normalized into `fields` + `field_scales`.
    fields: dict[str, str] | Literal["auto"] = Field(default_factory=dict)
    field_scales: dict[str, float] = Field(default_factory=dict)
    # explicit list, or "auto" to pick up image.ome.zarr / *.ome.zarr / spatial/tissue_hires_image.png next to the data
    images: list[ImageSpec] | Literal["auto"] = "auto"
    polygons: PolygonSpec | None = None
    extent: float = 5000.0  # embedding samples: rescale longest side to this many "um"
    point_radius: float | None = None  # um; default depends on platform
    seed: int = 7
    gene_column: str | None = None  # var column holding symbols; default var_names

    @model_validator(mode="before")
    @classmethod
    def _normalize_field_maps(cls, data):
        if not isinstance(data, dict) or not isinstance(data.get("fields"), dict):
            return data
        fields: dict[str, str] = {}
        scales: dict[str, float] = dict(data.get("field_scales") or {})
        for fid, v in data["fields"].items():
            if isinstance(v, dict):
                fm = FieldMap.model_validate(v)
                fields[fid] = fm.column
                if fm.scale != 1.0:
                    scales[fid] = fm.scale
            else:
                fields[fid] = v
        return {**data, "fields": fields, "field_scales": scales}


class FieldSpec(_Model):
    id: str
    name: str | None = None
    type: Literal["categorical", "continuous"] = "categorical"
    vocabulary: str | None = None  # defaults to id
    categories: list[str] | None = None  # explicit order; others appended first-seen
    aliases: dict[str, str] = Field(default_factory=dict)
    palette_key: str | None = None  # key inside the palette file; defaults to vocabulary
    colormap: str | None = None
    range: tuple[float, float] | None = None
    description: str | None = None


class FeatureGroupSpec(_Model):
    """Features whose var names match `pattern` are listed under their own tab instead of the gene list."""

    id: str
    name: str
    pattern: str  # regex searched in var names, e.g. "^RCTD: "
    strip: str | None = None  # regex removed from the label; defaults to pattern
    units: str | None = None  # e.g. "weight"


class LayoutSpec(_Model):
    mode: LayoutMode = "grid"
    order: list[str] | None = None
    gutter_fraction: float = 0.1


class DefaultColorSpec(_Model):
    gene: str | None = None
    field: str | None = None

    @model_validator(mode="after")
    def _one(self):
        if (self.gene is None) == (self.field is None):
            raise ValueError("default_color: set exactly one of gene / field")
        return self


class DatasetConfig(_Model):
    """Top-level dataset.yaml. `samples` are expanded (globs, templates, defaults) by `load_config`."""

    id: str
    name: str
    description: str | None = None
    default_gene: str | None = None
    default_color: DefaultColorSpec | None = None
    layout: LayoutSpec = Field(default_factory=LayoutSpec)
    palette: Path | None = None
    colormaps: list[str] | None = None
    shard_genes: int = 512
    thumbnail_sample: str | None = None  # sample shown on the dataset's gallery card (default: first in layout order)
    feature_groups: list[FeatureGroupSpec] = Field(default_factory=list)
    # Optional declarations (display names, explicit category order, aliases, palette keys). Fields that
    # samples reference without a declaration are declared automatically at build time.
    fields: list[FieldSpec] = Field(default_factory=list)
    defaults: dict[str, Any] = Field(default_factory=dict)  # merged into every sample entry
    platforms: dict[str, dict[str, Any]] = Field(default_factory=dict)  # merged into samples of that platform
    samples: list[SampleSpec]

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [s.id for s in self.samples]
        if len(set(ids)) != len(ids):
            raise ValueError(f"sample ids must be unique: {sorted({i for i in ids if ids.count(i) > 1})}")
        fids = [f.id for f in self.fields]
        if len(set(fids)) != len(fids):
            raise ValueError("field ids must be unique")
        return self

    def field_spec(self, fid: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.id == fid), None)


def _resolve_paths(cfg: DatasetConfig, base: Path) -> DatasetConfig:
    def res(p: Path | None) -> Path | None:
        if p is None:
            return None
        p = Path(p).expanduser()
        return p if p.is_absolute() else (base / p).resolve()

    cfg.palette = res(cfg.palette)
    for s in cfg.samples:
        s.path = res(s.path)
        s.microns.scalefactors_json = res(s.microns.scalefactors_json)
        if isinstance(s.images, list):
            for im in s.images:
                im.path = res(im.path)
        if s.polygons and s.polygons.path is not None:
            s.polygons.path = res(s.polygons.path)
    return cfg


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _render(value: Any, vars_: dict[str, str]) -> Any:
    if isinstance(value, str):
        try:
            return value.format(**vars_)
        except (KeyError, IndexError, ValueError):
            return value
    if isinstance(value, list):
        return [_render(v, vars_) for v in value]
    if isinstance(value, dict):
        return {k: _render(v, vars_) for k, v in value.items()}
    return value


def _template_vars(p: Path, i: int) -> dict[str, str]:
    stem = p.name
    for suf in (".h5ad", ".zarr", ".h5"):
        if stem.endswith(suf):
            stem = stem[: -len(suf)]
    return {
        "path": str(p),
        "dir": str(p.parent),
        "name": p.parent.name if p.is_dir() or p.suffix else p.name,
        "stem": stem,
        "i": str(i),
    }


def expand_samples(raw: dict, base: Path) -> list[dict]:
    """Expand glob entries and apply `defaults` / `platforms` blocks. Returns plain dicts for SampleSpec."""
    defaults = raw.get("defaults") or {}
    platforms = raw.get("platforms") or {}
    out: list[dict] = []
    for entry in raw.get("samples") or []:
        entry = dict(entry)
        pattern = entry.pop("glob", None)
        if pattern is None:
            matches = [None]
        else:
            pat = str(Path(pattern).expanduser())
            if not Path(pat).is_absolute():
                pat = str(base / pat)
            matches = sorted(_glob.glob(pat))
            if not matches:
                raise ValueError(f"glob matched nothing: {pattern}")
        for i, m in enumerate(matches):
            e = dict(entry)
            if m is not None:
                e["path"] = m
                vars_ = _template_vars(Path(m), i)
                e = _render(e, vars_)
                e.setdefault("id", re.sub(r"[^A-Za-z0-9_.-]+", "_", vars_["name"]))
            merged = _deep_merge(defaults, {})
            merged = _deep_merge(merged, platforms.get(e.get("platform", merged.get("platform", "")), {}))
            merged = _deep_merge(merged, e)
            if m is not None:
                merged = _render(merged, _template_vars(Path(m), i))
            out.append(merged)
    return out


def load_config(path: str | Path) -> DatasetConfig:
    path = Path(path).expanduser().resolve()
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    raw = dict(raw)
    raw["samples"] = expand_samples(raw, path.parent)
    cfg = DatasetConfig.model_validate(raw)
    return _resolve_paths(cfg, path.parent)
