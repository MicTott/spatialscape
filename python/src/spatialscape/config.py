"""Input schema: the dataset.yaml a contributor writes."""

from __future__ import annotations

import glob as _glob
import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

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


def is_remote(p: object) -> bool:
    """`ssh://host/path`: read over ssh at build time, nothing stored locally."""
    return isinstance(p, str) and p.startswith("ssh://")


def _file_or_url(v: str | Path) -> Path | str:
    return v if is_remote(v) else Path(v)


class BigWigsSpec(_Model):
    """Tracks another tool exported (ArchR `getGroupBW`, Signac `ExportGroupBW`, deepTools `bamCoverage` per group):
    one bigWig per category of each field, named by a path template with `{label}` or listed label by label."""

    by: dict[str, str | dict[str, Path]]  # field id -> "GroupBigWigs/{label}.bw" or {category label: path}
    all: Path | None = None  # a bigWig of every cell, when there is one

    @model_validator(mode="after")
    def _templates(self):
        for f, v in self.by.items():
            if isinstance(v, str) and "{label}" not in v:
                raise ValueError(f"tracks.bigwigs.by.{f}: a path template needs `{{label}}` (or list the files per category label)")
        return self


class TracksSpec(_Model):
    """Genome tracks for an ATAC sample, shown by the viewer's genome panel: pseudobulk accessibility per category of
    each field in `by`. Built from Cell Ranger style fragment files (insertions per million, binned; one file, or
    one per run for an object pooled from several 10x runs) or copied from bigWigs another tool exported, plus the
    sample's peaks and optional gene models and peak-gene links. Needs `pip install "spatialscape[tracks]"`."""

    fragments: str | Path | dict[str, str | Path] | None = None  # fragments.tsv.gz, or run id -> file for an object pooled from runs; a file may be `ssh://host/path` (streamed, never stored)
    bigwigs: BigWigsSpec | None = None  # tracks that already exist, instead of `fragments`
    by: list[str] = Field(default_factory=list)  # categorical field ids to aggregate by (with `bigwigs`: its fields)
    genome: str = "hg38"  # assembly id (hg38, mm10, ...): names the RefSeq gene models and the default chromosome sizes
    bin: int | None = Field(default=None, ge=1)  # bp per bin: 25 for fragments; read from the files for bigwigs
    normalize: Literal["nfrags", "tss", "cells"] = "nfrags"  # per group: per million insertions; per million insertions at gene TSSs (robust to background, ArchR's ReadsInTSS); per nucleus
    tss_window: int = Field(default=50, ge=1)  # bp either side of a TSS that count as "at the TSS" for `normalize: tss`
    chrom_sizes: Path | None = None  # two-column chrom\tsize file; default: the genome's primary chromosomes
    sample_column: str | None = None  # obs column naming the run each observation came from (required with several fragment files)
    barcode_column: str | None = None  # obs column holding the fragment-file barcode; default: the observation names, minus a run prefix or suffix
    units: str | None = None  # what the tracks measure, for the panel's scale: "insertions per million" for fragments, "signal" for bigwigs
    genes: str | None = "refseq"  # gene models: a GTF, UCSC genePred table or BED; `refseq` downloads UCSC's table for `genome` once; `none` for no gene track
    links: Path | None = None  # BEDPE of peak-gene links, drawn as arcs

    @model_validator(mode="after")
    def _one_source(self):
        if (self.fragments is None) == (self.bigwigs is None):
            raise ValueError("tracks: give either `fragments` or `bigwigs`")
        if isinstance(self.fragments, dict):
            if not self.fragments:
                raise ValueError("tracks.fragments: no files")
            if not self.sample_column:
                raise ValueError("tracks: several fragment files need `sample_column`, the obs column naming each observation's run")
        if self.bigwigs is not None:
            extra = [f for f in self.by if f not in self.bigwigs.by]
            if extra:
                raise ValueError(f"tracks.by lists {extra} but `bigwigs.by` has no files for them")
            if not self.by:
                self.by = list(self.bigwigs.by)
        elif not self.by:
            raise ValueError("tracks: `by` names the categorical fields to aggregate by")
        return self

    @property
    def genes_file(self) -> Path | None:
        """The gene-model file, or None for the `refseq` / `none` keywords."""
        return None if self.genes is None or self.genes in ("refseq", "none") else Path(self.genes)

    @property
    def fragment_files(self) -> list[tuple[str | None, Path | str]]:
        """(run id, file) pairs; the run is None for a single file. A remote file stays an `ssh://host/path` string."""
        if isinstance(self.fragments, dict):
            return [(str(k), _file_or_url(v)) for k, v in self.fragments.items()]
        return [(None, _file_or_url(self.fragments))] if self.fragments is not None else []

    @property
    def input_files(self) -> list[Path | str]:
        """Every file the tracks are built from, for the build fingerprint: fragment files (remote ones as their
        URL), bigWigs (a template is globbed), chromosome sizes, gene models and links."""
        files: list[Path | str | None] = [p for _, p in self.fragment_files] + [self.chrom_sizes, self.genes_file, self.links]
        if self.bigwigs is not None:
            files.append(self.bigwigs.all)
            for v in self.bigwigs.by.values():
                if isinstance(v, dict):
                    files.extend(v.values())
                else:
                    files.extend(sorted(_glob.glob(str(v).replace("{label}", "*"))))
        return [f if is_remote(f) else Path(f) for f in files if f is not None]


class SubsetSpec(_Model):
    """Keep only the observations whose `column` takes one of `values`, so one object can appear as several
    samples (one panel per broad cell class, one per condition, ...)."""

    column: str
    values: list[str]


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
    subset: SubsetSpec | None = None  # rows to keep; the default is every observation in the file
    tracks: TracksSpec | None = None  # genome tracks from a fragment file (ATAC)
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
    columns: int | None = Field(default=None, ge=1)  # grid: a fixed number of columns (default: fitted to the window)


class DefaultColorSpec(_Model):
    gene: str | None = None
    field: str | None = None

    @model_validator(mode="after")
    def _one(self):
        if (self.gene is None) == (self.field is None):
            raise ValueError("default_color: set exactly one of gene / field")
        return self


R_SUFFIXES = (".rds", ".rda", ".rdata")
R_ENTRY_KEYS = ("sample_col", "assay", "embedding", "object")


def is_r_object(path: Any) -> bool:
    return isinstance(path, (str, Path)) and str(path).lower().endswith(R_SUFFIXES)


class RObjectEntry(_Model):
    """A `samples:` entry whose `path` is an R object (`.rds`, `.rda`, `.RData`) holding a SpatialExperiment,
    SingleCellExperiment or Seurat object. `build` converts it once into a cache next to the bundle and expands it
    into one sample per `sample_col` value (objects with spatialCoords) or one embedding sample (objects without).
    Every other key of the entry (platform, templated id / name / group, fields, microns, ...) applies to those
    samples. For a Seurat object `assay` names a layer of the gene assay (`data`, `counts`; `logcounts` means
    `data`), and its other assays become prefixed features (`peak: `, `activity: `, `motif: `)."""

    path: Path
    sample_col: str = "sample_id"
    assay: str = "logcounts"
    embedding: str | None = None  # reducedDims entry / Seurat reduction for objects without spatialCoords; default: a UMAP
    object: str | None = None  # which object to take from an .rda that holds several
    template: dict[str, Any] = Field(default_factory=dict)  # the rest of the entry, applied to the expanded samples
    index: int = 0  # position in the yaml's `samples:` list


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

    # set by load_config: where the yaml lives, its raw content (for re-expansion) and its R object entries
    _path: Path | None = PrivateAttr(default=None)
    _raw: dict | None = PrivateAttr(default=None)
    _r_objects: list[RObjectEntry] = PrivateAttr(default_factory=list)

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def raw(self) -> dict:
        return self._raw or {}

    @property
    def r_objects(self) -> list[RObjectEntry]:
        return self._r_objects

    @property
    def default_bundle_dir(self) -> Path:
        """`bundles/<id>` next to the yaml: where `build` writes when `-o` is not given."""
        if self._path is None:
            raise ValueError("this config was not loaded from a file; pass an output directory")
        return self._path.parent / "bundles" / self.id

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
    """Paths are relative to the config file; `~` and `${ENV_VAR}` are expanded so configs stay portable."""

    def res(p: Path | None) -> Path | None:
        if p is None:
            return None
        p = Path(os.path.expandvars(str(p))).expanduser()
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
        if s.tracks is not None:
            t = s.tracks
            if isinstance(t.fragments, dict):
                t.fragments = {k: os.path.expandvars(v) if is_remote(v) else res(Path(v)) for k, v in t.fragments.items()}
            elif is_remote(t.fragments):
                t.fragments = os.path.expandvars(t.fragments)  # ssh://${CLUSTER_USER}@host/... keeps logins out of the yaml
            elif t.fragments is not None:
                t.fragments = res(Path(t.fragments))
            if t.bigwigs is not None:
                t.bigwigs.all = res(t.bigwigs.all)
                t.bigwigs.by = {
                    f: str(res(Path(v))) if isinstance(v, str) else {lab: res(pth) for lab, pth in v.items()} for f, v in t.bigwigs.by.items()
                }
            t.chrom_sizes = res(t.chrom_sizes)
            if t.genes_file is not None:
                t.genes = str(res(t.genes_file))
            t.links = res(t.links)
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


def _merged_entry(entry: dict, raw: dict) -> dict:
    """`defaults` < `platforms.<platform>` < the entry itself."""
    defaults = raw.get("defaults") or {}
    platforms = raw.get("platforms") or {}
    merged = _deep_merge(defaults, {})
    merged = _deep_merge(merged, platforms.get(entry.get("platform", merged.get("platform", "")), {}))
    return _deep_merge(merged, entry)


def expand_samples(raw: dict, base: Path) -> list[dict]:
    """Expand glob entries and apply `defaults` / `platforms` blocks. Returns plain dicts for SampleSpec.
    Entries whose `path` is an R object are skipped here; `build` converts and expands them (see convert.py)."""
    out: list[dict] = []
    for entry in raw.get("samples") or []:
        entry = dict(entry)
        pattern = entry.pop("glob", None)
        if pattern is None and is_r_object(entry.get("path")):
            continue
        if pattern is None:
            matches = [None]
        else:
            pat = str(Path(os.path.expandvars(str(pattern))).expanduser())
            if not Path(pat).is_absolute():
                pat = str(base / pat)
            matches = sorted(_glob.glob(pat, recursive=True))
            if not matches:
                raise ValueError(f"glob matched nothing: {pattern} (paths in dataset.yaml are relative to its folder, {base})")
        names = [_template_vars(Path(m), i)["name"] for i, m in enumerate(matches) if m is not None]
        flat = len(set(names)) < len(names)  # samples/A.h5ad, samples/B.h5ad: the folder name is shared, the stem is the sample
        for i, m in enumerate(matches):
            e = dict(entry)
            if m is not None:
                e["path"] = m
                vars_ = _template_vars(Path(m), i)
                e = _render(e, vars_)
                e.setdefault("id", re.sub(r"[^A-Za-z0-9_.-]+", "_", vars_["stem" if flat else "name"]))
            merged = _merged_entry(e, raw)
            if m is not None:
                merged = _render(merged, _template_vars(Path(m), i))
            out.append(merged)
    return out


def r_object_entries(raw: dict, base: Path) -> list[RObjectEntry]:
    """The `samples:` entries that point at R objects, with their templates checked against the sample schema."""
    out: list[RObjectEntry] = []
    for i, entry in enumerate(raw.get("samples") or []):
        if not isinstance(entry, dict) or "glob" in entry or not is_r_object(entry.get("path")):
            continue
        entry = dict(entry)
        r_keys = {k: entry.pop(k) for k in R_ENTRY_KEYS if k in entry}
        path = Path(os.path.expandvars(str(entry.pop("path")))).expanduser()
        path = path if path.is_absolute() else (base / path).resolve()
        # validate the template now (platform, fields, microns, ...) so typos surface before a long conversion
        probe = _merged_entry({**entry, "path": "probe/adata.h5ad", "id": "probe"}, raw)
        probe.setdefault("platform", "other")
        SampleSpec.model_validate(_render(probe, _template_vars(Path("probe/adata.h5ad"), 0)))
        out.append(RObjectEntry(path=path, template=entry, index=i, **r_keys))
    return out


def config_from_raw(raw: dict, path: Path, *, original: dict | None = None) -> DatasetConfig:
    """Validate an already-parsed yaml document. `path` is the yaml's location (paths resolve against its folder)."""
    base = path.parent
    r_entries = r_object_entries(raw, base)
    cfg = DatasetConfig.model_validate({**raw, "samples": expand_samples(raw, base)})
    cfg = _resolve_paths(cfg, base)
    cfg._path = path
    cfg._raw = original if original is not None else raw
    cfg._r_objects = r_entries
    return cfg


def load_config(path: str | Path) -> DatasetConfig:
    path = Path(path).expanduser().resolve()
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a mapping (id, name, samples, ...) at the top level")
    return config_from_raw(dict(raw), path)
