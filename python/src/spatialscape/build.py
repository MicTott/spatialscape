"""Orchestrate: dataset.yaml -> bundle directory."""
from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .config import DatasetConfig, FieldSpec, SampleSpec
from .expression import detect_lognorm, get_matrix, log1p_cp10k, write_expression
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
from .polygons import pack_polygons, read_polygon_table, write_polygons
from .readers import load_sample
from .vocab import VocabRegistry, load_palette

Log = Callable[[str], None]


def _fields_manifest(fields: list[FieldSpec], vocab: VocabRegistry):
    out = []
    for f in fields:
        name = f.name or f.id
        if f.type == "categorical":
            out.append(CategoricalField(id=f.id, name=name, vocabulary=vocab.vocab_id(f.id), description=f.description))
        else:
            out.append(ContinuousField(id=f.id, name=name, range=f.range, colormap=f.colormap, description=f.description))
    return out


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

    # --- geometry ---------------------------------------------------------
    upu = microns_per_unit(spec, sinput)  # microns per source unit
    coords = sinput.coords
    auto_images = [im for im in spec.images if im.pixel_size == "auto"]
    if auto_images:
        _c, h, w = read_image_shape(auto_images[0].path)
        frame_w, frame_h = w / auto_images[0].pixels_per_unit, h / auto_images[0].pixels_per_unit
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
            nums[fid] = pd.to_numeric(series, errors="coerce").to_numpy(dtype=np.float32)
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
    if spec.polygons:
        log(f"[{spec.id}] polygons {spec.polygons.path}")
        pids, px_, py_ = read_polygon_table(spec.polygons.path, spec.polygons.id_column, spec.polygons.x_column, spec.polygons.y_column)
        pxy = transform_points(np.column_stack([px_, py_]), frame_w, frame_h, spec.transform.flip, spec.transform.rotate) * upu - shift
        offsets, deltas, with_poly = pack_polygons(ids, xy, pids, pxy, max_vertices=spec.polygons.max_vertices)
        write_polygons(out_dir, offsets, deltas)
        poly_info = PolygonInfo(cells=with_poly, vertices=int(len(deltas) // 2), scale=POLY_SCALE)
        log(f"[{spec.id}] polygons matched {with_poly}/{n_obs} cells, {len(deltas) // 2} vertices")

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
        dc = ColorSpec(kind="gene", gene=cfg.default_color.gene) if cfg.default_color.gene else ColorSpec(kind="field", field=cfg.default_color.field)
    elif cfg.default_gene:
        dc = ColorSpec(kind="gene", gene=cfg.default_gene)
    else:
        cat_fields = [f for f in cfg.fields if f.type == "categorical"]
        dc = ColorSpec(kind="field", field=cat_fields[0].id) if cat_fields else ColorSpec(kind="gene", gene=genes[0])
    default_gene = cfg.default_gene or (dc.gene if dc.kind == "gene" else genes[0] if genes else None)
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
        fields=_fields_manifest(cfg.fields, vocab),
        featureGroups=[FeatureGroup(id=g["id"], name=g["name"], units=g["units"], count=len(g["features"])) for g in groups],
        samples=samples,
    )
    with open(out / "manifest.json", "w") as fh:
        fh.write(manifest.model_dump_json(indent=1, exclude_none=True))
    with open(out / "build-info.json", "w") as fh:
        json.dump({"sscape": __version__}, fh)
    return manifest


def build_dataset(cfg: DatasetConfig, out: Path, *, sharded: bool = True, log: Log = print) -> Manifest:
    out = Path(out)
    (out / "samples").mkdir(parents=True, exist_ok=True)
    vocab = VocabRegistry(cfg.fields, load_palette(cfg.palette))
    samples = [build_sample(spec, cfg, out / "samples" / spec.id, vocab, sharded=sharded, log=log) for spec in cfg.samples]
    return _write_dataset_files(out, cfg, samples, vocab)


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
            write_outlines(d, fid, compute_outlines(xy, codes, len(v.categories), skip_codes=na, smooth_um=smooth_um, min_feature_um=min_feature_um))
            done.append(fid)
        s.outlines = sorted(set(s.outlines) | set(done))
    return _write_dataset_files(out, cfg, existing.samples, vocab)


def refresh(cfg: DatasetConfig, out: Path) -> Manifest:
    """Rewrite manifest/genes/features from the samples already in the bundle (no sample rebuild)."""
    out = Path(out)
    with open(out / "manifest.json") as fh:
        existing = Manifest.model_validate_json(fh.read())
    vocab = VocabRegistry(cfg.fields, load_palette(cfg.palette), existing=existing.vocabularies)
    order = {s.id: i for i, s in enumerate(cfg.samples)}
    samples = sorted(existing.samples, key=lambda s: order.get(s.id, 1e9))
    return _write_dataset_files(out, cfg, samples, vocab)


def add_sample(
    cfg: DatasetConfig, out: Path, sample_id: str, *, sharded: bool = True, allow_vocab_append: bool = True, log: Log = print
) -> Manifest:
    out = Path(out)
    with open(out / "manifest.json") as fh:
        existing = Manifest.model_validate_json(fh.read())
    spec = next((s for s in cfg.samples if s.id == sample_id), None)
    if spec is None:
        raise KeyError(f"sample {sample_id!r} not in dataset.yaml")
    vocab = VocabRegistry(cfg.fields, load_palette(cfg.palette), existing=existing.vocabularies, frozen=not allow_vocab_append)
    new = build_sample(spec, cfg, out / "samples" / sample_id, vocab, sharded=sharded, log=log)
    samples = [s for s in existing.samples if s.id != sample_id] + [new]
    order = {s.id: i for i, s in enumerate(cfg.samples)}
    samples.sort(key=lambda s: order.get(s.id, 1e9))
    return _write_dataset_files(out, cfg, samples, vocab)
