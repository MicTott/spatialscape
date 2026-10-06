"""Input schema: the dataset.yaml a contributor writes."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

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
    """Per-cell boundary polygons (e.g. Xenium Ranger cell_boundaries.parquet). Coordinates share the frame of `coords`."""

    path: Path
    id_column: str = "cell_id"
    x_column: str = "vertex_x"
    y_column: str = "vertex_y"
    max_vertices: int = 24


class SampleSpec(_Model):
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
    fields: dict[str, str] = Field(default_factory=dict)  # field id -> obs column
    images: list[ImageSpec] = Field(default_factory=list)
    polygons: PolygonSpec | None = None
    extent: float = 5000.0  # embedding samples: rescale longest side to this many "um"
    point_radius: float | None = None  # um; default depends on platform
    seed: int = 7
    gene_column: str | None = None  # var column holding symbols; default var_names


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
    id: str
    name: str
    description: str | None = None
    default_gene: str | None = None
    default_color: DefaultColorSpec | None = None
    layout: LayoutSpec = Field(default_factory=LayoutSpec)
    palette: Path | None = None
    colormaps: list[str] | None = None
    shard_genes: int = 512
    feature_groups: list[FeatureGroupSpec] = Field(default_factory=list)
    fields: list[FieldSpec] = Field(default_factory=list)
    samples: list[SampleSpec]

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [s.id for s in self.samples]
        if len(set(ids)) != len(ids):
            raise ValueError("sample ids must be unique")
        fids = [f.id for f in self.fields]
        if len(set(fids)) != len(fids):
            raise ValueError("field ids must be unique")
        declared = set(fids)
        for s in self.samples:
            for fid in s.fields:
                if fid not in declared:
                    raise ValueError(f"sample {s.id}: field '{fid}' is not declared in fields[]")
        return self


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
        for im in s.images:
            im.path = res(im.path)
        if s.polygons:
            s.polygons.path = res(s.polygons.path)
    return cfg


def load_config(path: str | Path) -> DatasetConfig:
    path = Path(path).expanduser().resolve()
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    cfg = DatasetConfig.model_validate(raw)
    return _resolve_paths(cfg, path.parent)
