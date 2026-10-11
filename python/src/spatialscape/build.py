"""Orchestrate: dataset.yaml -> bundle directory."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .config import DatasetConfig, FieldSpec, PolygonSpec, SampleSpec
from .convert import SourceStatus, expand_r_objects
from .discover import auto_fields, auto_images, infer_field_spec
from .expression import detect_lognorm, get_matrix, log1p_cp10k, write_expression
from .fingerprint import read_sidecar, sample_fingerprint, why_stale, write_sidecar
from .geometry import default_point_radius, microns_per_unit, transform_points
from .images import prepare_image, read_image_shape, write_ome_zarr
from .manifest import (
    BUILTIN_COLORMAPS,
    CategoricalField,
    ColorSpec,
    ContinuousField,
    ExprSpec,
    FeatureGroup,
    ImageChannel,
    Layout,
    Manifest,
    PolygonInfo,
    Sample,
    SampleImage,
)
from .obs import write_obs
from .outlines import compute_outlines, write_outlines
from .polygons import SCALE as POLY_SCALE
from .polygons import apply_affine, pack_polygons, read_polygon_obsm, read_polygon_table, write_polygons
from .readers import load_sample
from .vocab import VocabRegistry, load_palette

Log = Callable[[str], None]
AUTO_POLYGON_OBSM = ("segmentations", "cell_boundaries", "boundaries", "polygons")


def _fields_manifest(fields: list[FieldSpec], vocab: VocabRegistry):
    out = []
    for f in fields:
        name = f.name or f.id
        if f.type == "categorical":
            out.append(CategoricalField(id=f.id, name=name, vocabulary=vocab.vocab_id(f.id), description=f.description))
        else:
            out.append(
                ContinuousField(id=f.id, name=name, range=f.range, colormap=f.colormap, description=f.description)
            )
    return out


def most_variable_gene(M, keep: np.ndarray, genes: list[str], *, seed: int = 0, max_rows: int = 4000) -> str | None:
    """Gene with the largest variance of normalized expression over a row subsample: a better opening gene than the
    alphabetically first one. `M` is (n_obs, n_vars) normalized; `keep` selects the retained genes."""
    if not genes:
        return None
    n = M.shape[0]
    rng = np.random.default_rng(seed)
    rows = np.sort(rng.choice(n, size=min(n, max_rows), replace=False)) if n > max_rows else slice(None)
    sub = M[rows][:, keep] if hasattr(M, "tocsr") else np.asarray(M)[rows][:, keep]
    if hasattr(sub, "multiply"):
        mean = np.asarray(sub.mean(axis=0)).ravel()
        sq = np.asarray(sub.multiply(sub).mean(axis=0)).ravel()
    else:
        mean = sub.mean(axis=0)
        sq = (sub * sub).mean(axis=0)
    var = sq - mean * mean
    if not np.isfinite(var).any():
        return genes[0]
    return genes[int(np.nanargmax(var))]


def suggested_default(samples: list[Sample], genes: list[str]) -> str | None:
    """Default gene for the dataset: the first spatial sample's most variable gene, else any sample's, else the first gene."""
    for s in samples:
        if s.kind == "spatial" and s.suggestedGene in genes:
            return s.suggestedGene
    for s in samples:
        if s.suggestedGene in genes:
            return s.suggestedGene
    return genes[0] if genes else None


def build_sample(
    spec: SampleSpec,
    cfg: DatasetConfig,
    out_dir: Path,
    vocab: VocabRegistry,
    *,
    sharded: bool = True,
    outline_fields: list[str] | bool | None = None,
    log: Log = print,
) -> Sample:
    log(f"[{spec.id}] reading {spec.path}")
    sinput = load_sample(spec)
    adata = sinput.adata
    n_obs = adata.n_obs
    if spec.fields == "auto":
        spec = spec.model_copy(update={"fields": auto_fields(adata, spec)})
        log(f"[{spec.id}] auto fields: {list(spec.fields)}")
    if spec.images == "auto":
        imgs, microns = auto_images(spec)
        upd: dict = {"images": imgs}
        if microns is not None and spec.microns == type(spec.microns)():
            upd["microns"] = microns
        spec = spec.model_copy(update=upd)
        if imgs:
            log(f"[{spec.id}] auto image: {imgs[0].path}")
    for fid, col in spec.fields.items():
        if fid not in vocab.fields:
            if col not in adata.obs:
                raise KeyError(f"sample {spec.id}: obs column {col!r} (field {fid}) not found")
            vocab.declare(infer_field_spec(fid, adata, col))
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    # --- expression -------------------------------------------------------
    M = get_matrix(adata, spec.expression.layer)
    mode = spec.expression.normalized
    if mode == "auto":
        mode = "lognorm" if detect_lognorm(M) else "counts"
        log(f"[{spec.id}] detected expression as {mode}")
    if mode == "counts":
        M = log1p_cp10k(M)
    rng = np.random.default_rng(spec.seed)
    perm = rng.permutation(n_obs)
    M = M[perm]  # rows shuffled once so any prefix is a uniform subsample
    log(f"[{spec.id}] writing expression ({M.shape[1]} genes x {n_obs} obs)")
    res = write_expression(
        M, out_dir, shard_genes=cfg.shard_genes, sharded=sharded, keep_f16=spec.expression.keep_f16, log=log
    )
    genes = [str(g) for g in sinput.gene_names[res.keep]]
    with open(out_dir / "genes.json", "w") as fh:
        json.dump(genes, fh, separators=(",", ":"))
    suggested = most_variable_gene(M, res.keep, genes, seed=spec.seed)

    # --- geometry ---------------------------------------------------------
    upu = microns_per_unit(spec, sinput)  # microns per source unit
    coords = sinput.coords
    auto_px_images = [im for im in spec.images if im.pixel_size == "auto"]
    if auto_px_images:
        _c, h, w = read_image_shape(auto_px_images[0].path)
        frame_w, frame_h = w / auto_px_images[0].pixels_per_unit, h / auto_px_images[0].pixels_per_unit
    else:
        frame_w, frame_h = float(coords[:, 0].max()), float(coords[:, 1].max())
    xy = transform_points(coords, frame_w, frame_h, spec.transform.flip, spec.transform.rotate) * upu
    shift = xy.min(axis=0)
    xy = xy - shift
    xy = xy[perm]
    bbox = (0.0, 0.0, float(xy[:, 0].max()), float(xy[:, 1].max()))
    radius = default_point_radius(spec, xy)

    # --- obs --------------------------------------------------------------
    cats: dict[str, np.ndarray] = {}
    nums: dict[str, np.ndarray] = {}
    for fid, col in spec.fields.items():
        if col not in adata.obs:
            raise KeyError(f"sample {spec.id}: obs column {col!r} (field {fid}) not found")
        f = vocab.fields[fid]
        series = adata.obs[col].iloc[perm]
        if f.type == "categorical":
            cats[fid] = vocab.encode(fid, series.reset_index(drop=True))
        else:
            arr = pd.to_numeric(series, errors="coerce").to_numpy(dtype=np.float32)
            scale = spec.field_scales.get(fid, 1.0)
            nums[fid] = arr * np.float32(scale) if scale != 1.0 else arr
    ids = [str(s) for s in adata.obs_names[perm]]
    write_obs(out_dir, xy=xy, order=perm.astype(np.uint32), ids=ids, cats=cats, nums=nums)
    outlines: list[str] = []
    if spec.kind == "spatial" and outline_fields is not False:
        for fid, codes in cats.items():
            if outline_fields and fid not in outline_fields:
                continue
            vid = vocab.vocab_id(fid)
            v = vocab.vocabs[vid]
            na = {v["categories"].index("NA")} if "NA" in v["categories"] else set()
            log(f"[{spec.id}] outlines for {fid}")
            write_outlines(out_dir, fid, compute_outlines(xy, codes, len(v["categories"]), skip_codes=na))
            outlines.append(fid)

    # --- polygons ---------------------------------------------------------
    poly_info = None
    if spec.polygons is None and spec.kind == "spatial":
        for key in AUTO_POLYGON_OBSM:
            arr = adata.obsm.get(key, None)
            if arr is not None and np.ndim(arr) == 3 and np.shape(arr)[2] == 2:
                spec = spec.model_copy(update={"polygons": PolygonSpec(obsm=key)})
                log(f"[{spec.id}] auto polygons: obsm/{key}")
                break
    if spec.polygons:
        ps = spec.polygons
        if ps.obsm:
            log(f"[{spec.id}] polygons from obsm/{ps.obsm}")
            pids, px_, py_ = read_polygon_obsm(adata, ps.obsm)
        else:
            log(f"[{spec.id}] polygons {ps.path}")
            pids, px_, py_ = read_polygon_table(ps.path, ps.id_column, ps.x_column, ps.y_column)
        if ps.affine:
            px_, py_ = apply_affine(px_, py_, ps.affine)
        pxy = (
            transform_points(np.column_stack([px_, py_]), frame_w, frame_h, spec.transform.flip, spec.transform.rotate)
            * upu
            - shift
        )
        offsets, deltas, with_poly, dev = pack_polygons(ids, xy, pids, pxy, max_vertices=ps.max_vertices)
        write_polygons(out_dir, offsets, deltas)
        poly_info = PolygonInfo(cells=with_poly, vertices=int(len(deltas) // 2), scale=POLY_SCALE)
        log(f"[{spec.id}] polygons matched {with_poly}/{n_obs} cells, {len(deltas) // 2} vertices")
        if with_poly and dev > max(10.0, 2.0 * radius):
            log(
                f"[{spec.id}] warning: polygon centroids sit a median {dev:.1f} um from their cells; "
                "the boundary file is probably in a different frame than the coordinates (see polygons.affine)"
            )

    # --- images -----------------------------------------------------------
    images: list[SampleImage] = []
    for im in spec.images:
        log(f"[{spec.id}] image {im.path}")
        img = prepare_image(im.path, spec.transform.flip, spec.transform.rotate, im.max_size)
        rgb = im.kind == "rgb"
        if im.pixel_size == "auto":
            # pixels_per_unit image px per coord unit; after max_size downsampling the ratio changes
            _c, h0, w0 = read_image_shape(im.path)
            ds = max(h0, w0) / max(img.shape[1], img.shape[2]) if im.max_size else 1.0
            pixel_size = upu / im.pixels_per_unit * ds
        else:
            pixel_size = float(im.pixel_size)
        names = [ch.name for ch in im.channels] if im.channels else None
        colors = [ch.color for ch in im.channels] if im.channels else None
        wins = [ch.window for ch in im.channels] if im.channels and all(ch.window for ch in im.channels) else None
        out_path = out_dir / f"{im.id}.ome.zarr"
        write_ome_zarr(img, out_path, rgb=rgb, channel_names=names, channel_colors=colors, windows=wins)
        chans = None
        if im.channels:
            maxv = 255 if img.dtype == np.uint8 else int(np.iinfo(img.dtype).max)
            chans = [ImageChannel(name=ch.name, color=ch.color, window=ch.window or (0, maxv)) for ch in im.channels]
        images.append(
            SampleImage(
                id=im.id,
                name=im.name,
                path=out_path.name,
                kind=im.kind,
                pixelSize=pixel_size,
                translate=(float(-shift[0] + im.translate[0]), float(-shift[1] + im.translate[1])),
                size=(int(img.shape[1]), int(img.shape[2])),
                channels=chans,
                defaultOpacity=im.default_opacity,
            )
        )

    return Sample(
        id=spec.id,
        name=spec.name or spec.id,
        platform=spec.platform,
        kind=spec.kind,
        group=spec.group,
        nObs=n_obs,
        nGenes=len(genes),
        bbox=bbox,
        pointRadius=radius,
        expr=ExprSpec(kind="u8", sharded=res.sharded, shardGenes=res.shard_genes),
        hasF16=spec.expression.keep_f16,
        fields=list(spec.fields.keys()),
        images=images,
        outlines=outlines,
        polygons=poly_info,
        suggestedGene=suggested,
    )


def _split_features(cfg: DatasetConfig, names: list[str]) -> tuple[list[str], list[dict]]:
    """Split the feature union into plain genes and configured groups (first matching pattern wins)."""
    groups = [{"id": g.id, "name": g.name, "units": g.units, "features": []} for g in cfg.feature_groups]
    pats = [(re.compile(g.pattern), re.compile(g.strip or g.pattern)) for g in cfg.feature_groups]
    genes: list[str] = []
    for n in names:
        for gi, (pat, strip) in enumerate(pats):
            if pat.search(n):
                groups[gi]["features"].append({"id": n, "label": strip.sub("", n).strip() or n})
                break
        else:
            genes.append(n)
    for g in groups:
        g["features"].sort(key=lambda f: f["label"].lower())
    return genes, groups


def _all_fields(cfg: DatasetConfig, vocab: VocabRegistry) -> list[FieldSpec]:
    declared = {f.id: f for f in cfg.fields}
    out = list(cfg.fields)
    out += [f for fid, f in vocab.fields.items() if fid not in declared]
    return out


def _write_dataset_files(out: Path, cfg: DatasetConfig, samples: list[Sample], vocab: VocabRegistry) -> Manifest:
    union: set[str] = set()
    for s in samples:
        with open(out / "samples" / s.id / "genes.json") as fh:
            union.update(json.load(fh))
    genes, groups = _split_features(cfg, sorted(union))
    with open(out / "genes.json", "w") as fh:
        json.dump(genes, fh, separators=(",", ":"))
    with open(out / "features.json", "w") as fh:
        json.dump({"genes": genes, "groups": groups}, fh, separators=(",", ":"))

    if cfg.default_color is not None:
        dc = (
            ColorSpec(kind="gene", gene=cfg.default_color.gene)
            if cfg.default_color.gene
            else ColorSpec(kind="field", field=cfg.default_color.field)
        )
    elif cfg.default_gene:
        dc = ColorSpec(kind="gene", gene=cfg.default_gene)
    else:
        cat_fields = [f for f in cfg.fields if f.type == "categorical"]
        dc = ColorSpec(kind="field", field=cat_fields[0].id) if cat_fields else ColorSpec(kind="gene", gene=suggested_default(samples, genes) or genes[0])
    default_gene = cfg.default_gene or (dc.gene if dc.kind == "gene" else suggested_default(samples, genes))
    order = cfg.layout.order or [s.id for s in samples]
    manifest = Manifest(
        id=cfg.id,
        name=cfg.name,
        description=cfg.description,
        defaultGene=default_gene,
        defaultColor=dc,
        layout=Layout(mode=cfg.layout.mode, gutterFraction=cfg.layout.gutter_fraction, order=order),
        colormaps=cfg.colormaps or list(BUILTIN_COLORMAPS),
        vocabularies=vocab.to_manifest(),
        fields=_fields_manifest(_all_fields(cfg, vocab), vocab),
        featureGroups=[
            FeatureGroup(id=g["id"], name=g["name"], units=g["units"], count=len(g["features"])) for g in groups
        ],
        samples=samples,
        thumbnailSample=cfg.thumbnail_sample,
    )
    with open(out / "manifest.json", "w") as fh:
        fh.write(manifest.model_dump_json(indent=1, exclude_none=True))
    with open(out / "build-info.json", "w") as fh:
        json.dump({"spatialscape": __version__, "config": str(cfg.path) if cfg.path else None, "built": datetime.now(UTC).isoformat(timespec="seconds")}, fh, indent=1)
    return manifest


def read_manifest(out: Path) -> Manifest | None:
    p = Path(out) / "manifest.json"
    if not p.exists():
        return None
    try:
        return Manifest.model_validate_json(p.read_text())
    except Exception:
        return None


@dataclass
class SampleAction:
    spec: SampleSpec
    build: bool
    reason: str  # new | source changed | settings changed | field declarations changed | format changed | forced | unchanged
    fingerprint: dict


@dataclass
class BuildPlan:
    """What a `build` would do to a bundle directory. Pure: computed from the yaml, the input files and the sidecars."""

    out: Path
    actions: list[SampleAction]
    removed: list[str]  # sample folders in the bundle that the yaml no longer lists
    existing: Manifest | None
    sources: list[SourceStatus] = field(default_factory=list)

    @property
    def to_build(self) -> list[SampleAction]:
        return [a for a in self.actions if a.build]

    @property
    def reused(self) -> list[SampleAction]:
        return [a for a in self.actions if not a.build]


def plan_build(cfg: DatasetConfig, out: Path, *, sharded: bool = True, force: bool = False) -> BuildPlan:
    out = Path(out)
    existing = read_manifest(out)
    present = {s.id for s in existing.samples} if existing else set()
    actions: list[SampleAction] = []
    for spec in cfg.samples:
        fp = sample_fingerprint(spec, cfg, sharded=sharded)
        d = out / "samples" / spec.id
        if force:
            reason: str | None = "forced"
        elif spec.id not in present or not (d / "expr.zarr").exists():
            reason = "new"
        else:
            reason = why_stale(read_sidecar(d), fp)
        actions.append(SampleAction(spec, reason is not None, reason or "unchanged", fp))
    wanted = {s.id for s in cfg.samples}
    folders = sorted(p.name for p in (out / "samples").iterdir() if p.is_dir()) if (out / "samples").is_dir() else []
    return BuildPlan(out, actions, [f for f in folders if f not in wanted], existing)


def describe_plan(plan: BuildPlan) -> list[str]:
    lines: list[str] = []
    if plan.sources:
        lines.append("sources")
        for st in plan.sources:
            lines.append(f"  {st.entry.path}: {st.label}")
    if plan.actions:
        w = max(len(a.spec.id) for a in plan.actions)
        for a in plan.actions:
            lines.append(f"  {a.spec.id:<{w}}  {'build' if a.build else 'skip '}  {a.reason}")
    for sid in plan.removed:
        lines.append(f"  {sid}: removed (no longer in the yaml)")
    n_build, n_skip = len(plan.to_build), len(plan.reused)
    pending = sum(st.state == "pending" for st in plan.sources)
    if pending:
        lines.append(f"{pending} R object{'s' if pending != 1 else ''} to convert first (their samples are listed once converted)")
    lines.append(f"{n_build} sample{'s' if n_build != 1 else ''} to build, {n_skip} unchanged; manifest.json, genes.json, features.json and thumbnails are rewritten every time")
    return lines


def _registry_for(cfg: DatasetConfig, existing: Manifest | None, reused: list[SampleAction]) -> VocabRegistry:
    """Fresh vocabularies when every sample is rebuilt; otherwise the vocabularies that reused samples depend on are
    kept from the existing manifest so their codes stay valid, and new labels append. Palette colors always apply."""
    palette = load_palette(cfg.palette)
    if existing is None or not reused:
        return VocabRegistry(cfg.fields, palette)
    by_id = {s.id: s for s in existing.samples}
    reused_fields = {fid for a in reused for fid in by_id[a.spec.id].fields}
    keep_vocabs = {f.vocabulary for fid in reused_fields if (f := existing.field_by_id(fid)) is not None and f.type == "categorical"}
    vocab = VocabRegistry(cfg.fields, palette, existing={vid: v for vid, v in existing.vocabularies.items() if vid in keep_vocabs})
    vocab.adopt_manifest_fields(existing, only=reused_fields)
    vocab.recolor_from_palette()
    return vocab


def build_dataset(cfg: DatasetConfig, out: Path, *, sharded: bool = True, force: bool = False, plan: BuildPlan | None = None, log: Log = print) -> Manifest:
    """Bring the bundle directory in line with the yaml: build new and changed samples, keep the rest, drop
    samples the yaml no longer lists, and rewrite the dataset-level files."""
    out = Path(out)
    (out / "samples").mkdir(parents=True, exist_ok=True)
    plan = plan or plan_build(cfg, out, sharded=sharded, force=force)
    vocab = _registry_for(cfg, plan.existing, plan.reused)
    by_id = {s.id: s for s in plan.existing.samples} if plan.existing else {}
    samples: list[Sample] = []
    for a in plan.actions:
        if a.build:
            s = build_sample(a.spec, cfg, out / "samples" / a.spec.id, vocab, sharded=sharded, log=log)
            write_sidecar(out / "samples" / a.spec.id, a.fingerprint)
        else:
            s = by_id[a.spec.id].model_copy(update={"name": a.spec.name or a.spec.id, "group": a.spec.group})
        samples.append(s)
    for sid in plan.removed:
        shutil.rmtree(out / "samples" / sid, ignore_errors=True)
        log(f"removed sample {sid}")
    return _write_dataset_files(out, cfg, samples, vocab)


@dataclass
class BuildResult:
    out: Path
    plan: BuildPlan
    manifest: Manifest | None  # None for a dry run
    problems: list[str] = field(default_factory=list)


def build_bundle(cfg: DatasetConfig, out: Path | None = None, *, sharded: bool = True, force: bool = False, dry_run: bool = False, log: Log = print) -> BuildResult:
    """Everything `spatialscape build` does: convert R objects into the cache, plan, build, render thumbnails,
    validate. `site build` runs the same for every dataset yaml it lists."""
    from .thumbnail import write_thumbnails
    from .validate import validate_local

    out = Path(out) if out is not None else cfg.default_bundle_dir
    cache_root = out.parent / ".cache" / out.name
    cfg, sources = expand_r_objects(cfg, cache_root, convert=not dry_run, log=log)
    plan = plan_build(cfg, out, sharded=sharded, force=force)
    plan.sources = sources
    for line in describe_plan(plan):
        log(line)
    if dry_run:
        return BuildResult(out, plan, None)
    m = build_dataset(cfg, out, sharded=sharded, force=force, plan=plan, log=log)
    try:
        write_thumbnails(out, hero_id=cfg.thumbnail_sample, log=log)
    except Exception as e:  # thumbnails are a nicety; never fail a build over them
        log(f"thumbnails skipped: {e}")
    return BuildResult(out, plan, m, validate_local(out))


def add_outlines(
    cfg: DatasetConfig,
    out: Path,
    *,
    sample_ids: list[str] | None = None,
    fields: list[str] | None = None,
    smooth_um: float = 150.0,
    min_feature_um: float = 300.0,
    log: Log = print,
) -> Manifest:
    """Compute outlines for categorical fields from the arrays already in the bundle (no source data needed)."""
    import zarr

    out = Path(out)
    with open(out / "manifest.json") as fh:
        existing = Manifest.model_validate_json(fh.read())
    vocab = VocabRegistry(cfg.fields, load_palette(cfg.palette), existing=existing.vocabularies)
    vocab.adopt_manifest_fields(existing)
    vocab.recolor_from_palette()  # palette edits apply on refresh; codes stay put
    for s in existing.samples:
        if sample_ids and s.id not in sample_ids:
            continue
        if s.kind != "spatial":
            continue
        d = out / "samples" / s.id
        og = zarr.open_group(str(d / "obs.zarr"), mode="r")
        xy = og["xy"][:]
        done: list[str] = []
        for fid in s.fields:
            f = existing.field_by_id(fid)
            if not f or f.type != "categorical" or (fields and fid not in fields):
                continue
            codes = og["cat"][fid][:]
            v = existing.vocabularies[f.vocabulary]
            na = {v.categories.index("NA")} if "NA" in v.categories else set()
            log(f"[{s.id}] outlines for {fid}")
            write_outlines(
                d,
                fid,
                compute_outlines(
                    xy, codes, len(v.categories), skip_codes=na, smooth_um=smooth_um, min_feature_um=min_feature_um
                ),
            )
            done.append(fid)
        s.outlines = sorted(set(s.outlines) | set(done))
    return _write_dataset_files(out, cfg, existing.samples, vocab)
