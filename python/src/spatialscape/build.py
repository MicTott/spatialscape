"""Orchestrate: dataset.yaml -> bundle directory."""

from __future__ import annotations

import gc
import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp

from . import __version__
from .comparisons import ComparisonAction, plan_comparisons, read_info, samples_signature, write_comparison
from .config import DatasetConfig, FieldSpec, PolygonSpec, SampleSpec
from .convert import SourceStatus, expand_r_objects
from .discover import auto_fields, infer_field_spec
from .expression import column_moments, detect_lognorm, get_matrix, log1p_cp10k, write_expression
from .fingerprint import read_sidecar, resolve_auto_images, sample_fingerprint, why_stale, write_sidecar
from .geometry import default_point_radius, microns_per_unit, transform_points
from .images import (
    DEFAULT_CHANNEL_COLORS,
    ImageReadRefused,
    auto_windows,
    ome_channel_names,
    prepare_image,
    read_image_shape,
    write_ome_zarr,
)
from .manifest import (
    BUILTIN_COLORMAPS,
    CategoricalField,
    ColorSpec,
    ComparisonInfo,
    ContinuousField,
    ExprSpec,
    FeatureGroup,
    ImageChannel,
    Layout,
    Manifest,
    MetaKey,
    MoleculesInfo,
    Sample,
    SampleImage,
    ShapesInfo,
)
from .molecules import write_molecules
from .obs import write_obs
from .outlines import compute_outlines, write_outlines
from .polygons import apply_affine, read_polygon_obsm, read_polygon_table
from .readers import load_sample
from .shapes import write_shapes
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


def crop_to_points(img: np.ndarray, pixel_size: float, translate: tuple[float, float], bbox: tuple[float, float, float, float], margin: float = 0.03) -> tuple[np.ndarray, tuple[float, float]]:
    """Cut an image (c, y, x) placed at `translate` (um) with `pixel_size` um/px down to the points' bounding box plus
    a margin (a fraction of its longer side), and return the image with its new translate. A slide scan reaches well
    past the capture area; without this the H&E, not the tissue, sets the size of every grid cell."""
    x0, y0, x1, y1 = bbox
    pad = margin * max(x1 - x0, y1 - y0)
    _c, h, w = img.shape
    px0 = int(np.clip(np.floor((x0 - pad - translate[0]) / pixel_size), 0, w))
    px1 = int(np.clip(np.ceil((x1 + pad - translate[0]) / pixel_size), 0, w))
    py0 = int(np.clip(np.floor((y0 - pad - translate[1]) / pixel_size), 0, h))
    py1 = int(np.clip(np.ceil((y1 + pad - translate[1]) / pixel_size), 0, h))
    if px1 - px0 < 2 or py1 - py0 < 2:  # the points lie outside the image: leave it alone
        return img, translate
    if (px0, py0, px1, py1) == (0, 0, w, h):
        return img, translate
    out = np.ascontiguousarray(img[:, py0:py1, px0:px1])
    return out, (translate[0] + px0 * pixel_size, translate[1] + py0 * pixel_size)


def mask_to_points(img: np.ndarray, pixel_size: float, translate: tuple[float, float], xy: np.ndarray, margin_um: float, *, rgb: bool) -> np.ndarray:
    """Blank every pixel farther than `margin_um` from any point (white for RGB, black for fluorescence), so a slide
    image shared by several sections shows only this section's tissue."""
    from scipy import ndimage

    _c, h, w = img.shape
    px = np.clip(((xy[:, 0] - translate[0]) / pixel_size).astype(np.int64), 0, w - 1)
    py = np.clip(((xy[:, 1] - translate[1]) / pixel_size).astype(np.int64), 0, h - 1)
    hit = np.zeros((h, w), dtype=bool)
    hit[py, px] = True
    far = ndimage.distance_transform_edt(~hit) * pixel_size > margin_um
    out = np.array(img, copy=True)
    out[:, far] = np.iinfo(out.dtype).max if (rgb and np.issubdtype(out.dtype, np.integer)) else (1.0 if rgb else 0)
    return out


def most_variable_gene(M, keep: np.ndarray, genes: list[str], *, seed: int = 0, max_rows: int = 4000) -> str | None:
    """Gene with the largest variance of normalized expression over a row subsample: a better opening gene than the
    alphabetically first one. `M` is (n_obs, n_vars) normalized; `keep` selects the retained genes."""
    if not genes:
        return None
    n = M.shape[0]
    rows = np.sort(np.random.default_rng(seed).choice(n, size=max_rows, replace=False)) if n > max_rows else None
    if sp.issparse(M):
        sub = (M[rows] if rows is not None else M).tocsc()
        _mean, var = column_moments(sub)
    else:
        sub = np.asarray(M, dtype=np.float64)
        var = (sub[rows] if rows is not None else sub).var(axis=0)
    var = var[keep]
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
    meta = resolve_meta(spec, adata)
    if sinput.name_column and not spec.gene_column:
        log(f"[{spec.id}] gene names from var column {sinput.name_column!r} (var_names are Ensembl ids)")
    if spec.fields == "auto":
        spec = spec.model_copy(update={"fields": auto_fields(adata, spec)})
        log(f"[{spec.id}] auto fields: {list(spec.fields)}")
    discovered = spec.images == "auto"  # images found next to the data are skipped with a note when they cannot be read
    if spec.images == "auto" or spec.microns == type(spec.microns)():
        was_auto = spec.images == "auto"
        spec = resolve_auto_images(spec)
        if was_auto and spec.images:
            log(f"[{spec.id}] auto image: {spec.images[0].path}")
    for fid, col in spec.fields.items():
        if fid not in vocab.fields:
            if col not in adata.obs:
                raise KeyError(f"sample {spec.id}: obs column {col!r} (field {fid}) not found")
            vocab.declare(infer_field_spec(fid, adata, col))
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    # --- coordinate scale first: a wrong `microns:` must not leave a half-written sample behind
    upu = microns_per_unit(spec, sinput)  # microns per source unit
    if spec.kind == "spatial":
        log(f"[{spec.id}] coordinates: 1 unit = {upu:.4g} um")

    # --- expression -------------------------------------------------------
    M = get_matrix(adata, spec.expression.layer)
    mode = spec.expression.normalized
    if mode == "auto":
        mode = "lognorm" if detect_lognorm(M) else "counts"
        mx = float(M.data.max()) if getattr(M, "nnz", 1) else 0.0
        why = "non-integer values" if mode == "lognorm" else f"all-integer values, max {mx:g}"
        log(f"[{spec.id}] expression layer {spec.expression.layer!r} looks {'log-normalized' if mode == 'lognorm' else 'like counts'} ({why})" + ("" if mode == "lognorm" else ": applying log1p(CP10k)"))
    if mode == "counts":
        M = log1p_cp10k(M)
    rng = np.random.default_rng(spec.seed)
    perm = rng.permutation(n_obs)  # rows are written shuffled once, so any prefix is a uniform subsample
    log(f"[{spec.id}] writing expression ({M.shape[1]} genes x {n_obs} obs)")
    res = write_expression(
        M, out_dir, shard_genes=cfg.shard_genes, sharded=sharded, keep_f16=spec.expression.keep_f16, order=perm, log=log
    )
    genes = [str(g) for g in sinput.gene_names[res.keep]]
    n_dropped = int((~res.keep).sum())
    if n_dropped:
        log(f"[{spec.id}] {n_dropped} all-zero feature{'s' if n_dropped != 1 else ''} left out ({len(genes)} kept)")
    with open(out_dir / "genes.json", "w") as fh:
        json.dump(genes, fh, separators=(",", ":"))
    suggested = most_variable_gene(M, res.keep, genes, seed=spec.seed)

    # --- geometry ---------------------------------------------------------
    coords = sinput.coords
    auto_px_images = [im for im in spec.images if im.pixel_size == "auto"]
    if auto_px_images:
        _c, h, w = read_image_shape(auto_px_images[0].path, rgb=auto_px_images[0].kind == "rgb")
        if auto_px_images[0].transpose:
            h, w = w, h
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
            arr = pd.to_numeric(series, errors="coerce").to_numpy(dtype=np.float32, na_value=np.nan)
            scale = spec.field_scales.get(fid, 1.0)
            nums[fid] = arr * np.float32(scale) if scale != 1.0 else arr
    ids = [str(s) for s in adata.obs_names[perm]]
    write_obs(out_dir, xy=xy, order=perm.astype(np.uint32), ids=ids, cats=cats, nums=nums)
    tracks_info = None
    if spec.tracks is not None:
        from .tracks import write_tracks

        tr = spec.tracks
        for col, key in ((tr.barcode_column, "barcode_column"), (tr.sample_column, "sample_column")):
            if col and col not in adata.obs:
                raise KeyError(f"sample {spec.id}: tracks.{key} {col!r} is not an obs column")
        barcodes = [str(b) for b in adata.obs[tr.barcode_column].iloc[perm]] if tr.barcode_column else None
        runs = [str(r) for r in adata.obs[tr.sample_column].iloc[perm]] if tr.sample_column else None
        tracks_info = write_tracks(
            tr, out_dir, ids=ids, barcodes=barcodes, runs=runs, cats=cats,
            categories={fid: list(vocab.vocabs[vocab.vocab_id(fid)]["categories"]) for fid in cats},
            aliases={fid: dict(vocab.vocabs[vocab.vocab_id(fid)]["aliases"]) for fid in cats}, feature_names=genes, log=log,
        )
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

    # --- cell shapes ------------------------------------------------------
    shapes_info = None
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
        st = write_shapes(out_dir, ids, xy, pids, pxy, max_vertices=ps.max_vertices, packed=sharded)
        shapes_info = ShapesInfo(cells=st.cells, vertices=st.vertices, tile=st.tile, tiles=st.tiles, bytes=st.bytes)
        dropped = "".join(f", {k} {v} dropped" for k, v in (("unmatched", st.unmatched), ("degenerate", st.degenerate)) if v)
        log(f"[{spec.id}] cell shapes for {st.cells}/{n_obs} cells: {st.tiles} tiles of {st.tile} um, {st.bytes / 2**20:.1f} MB ({st.bytes / max(st.cells, 1):.0f} B per cell){dropped}")
        with_poly, dev = st.cells, st.centroid_offset
        if with_poly and dev > max(10.0, 2.0 * radius):
            log(
                f"[{spec.id}] warning: polygon centroids sit a median {dev:.1f} um from their cells; "
                "the boundary file is probably in a different frame than the coordinates (see polygons.affine)"
            )

    # --- molecules --------------------------------------------------------
    molecules_info = None
    if spec.molecules:
        ms = spec.molecules
        affine = ms.affine or (spec.polygons.affine if spec.polygons else None)
        log(f"[{spec.id}] molecules {ms.path}")

        def to_frame(raw: np.ndarray, _affine=affine) -> np.ndarray:
            x, y = raw[:, 0], raw[:, 1]
            if _affine:
                x, y = apply_affine(x, y, _affine)
            return transform_points(np.column_stack([x, y]), frame_w, frame_h, spec.transform.flip, spec.transform.rotate) * upu - shift

        mst = write_molecules(
            out_dir,
            ms.path,
            to_frame=to_frame,
            columns={"feature": ms.feature_column, "x": ms.x_column, "y": ms.y_column, "qv": ms.qv_column or "", "cell": ms.cell_column or "", "nucleus": ms.nucleus_column or ""},
            min_qv=ms.min_qv,
            packed=sharded,
            log=lambda m: log(f"[{spec.id}] {m}"),
        )
        molecules_info = MoleculesInfo(count=mst.count, genes=mst.genes, tile=mst.tile, tiles=mst.tiles, bytes=mst.bytes)
        log(
            f"[{spec.id}] molecules: {mst.count:,} of {mst.read:,} rows kept ({mst.low_quality:,} below Q{ms.min_qv:g}, {mst.controls:,} controls), "
            f"{mst.genes} genes, {mst.tiles} tiles of {mst.tile} um, {mst.bytes / 2**20:.0f} MB ({mst.bytes / max(mst.count, 1):.1f} B each) in {mst.seconds:.0f} s"
        )
        unknown = [g for g in json.loads((out_dir / "molecules.json").read_text())["genes"] if g not in set(genes)]
        if unknown:
            log(f"[{spec.id}] note: {len(unknown)} molecule feature{'s' if len(unknown) != 1 else ''} not in the expression matrix (for example {', '.join(unknown[:3])}); they draw in grey only")

    # --- images -----------------------------------------------------------
    images: list[SampleImage] = []
    for im in spec.images:
        log(f"[{spec.id}] image {im.path}")
        rgb = im.kind == "rgb"
        img = None
        max_size = im.max_size
        while img is None:
            try:
                img = prepare_image(im.path, spec.transform.flip, spec.transform.rotate, max_size, rgb=rgb, transpose=im.transpose, image_flip=im.flip)
            except ImageReadRefused as e:
                if not discovered:
                    raise
                if e.kind == "memory" and max_size and max_size >= 2048:  # a smaller copy on a smaller machine
                    max_size //= 2
                    log(f"[{spec.id}] note: the image found next to the data does not fit in memory at that size; reading it at most {max_size:,} px per side")
                    continue
                log(f"[{spec.id}] note: skipping the image found next to the data: {e}")
                break
        if img is None:
            continue
        if im.pixel_size == "auto":
            # pixels_per_unit image px per coord unit; after max_size downsampling the ratio changes
            _c, h0, w0 = read_image_shape(im.path, rgb=rgb)
            ds = max(h0, w0) / max(img.shape[1], img.shape[2]) if max_size else 1.0
            pixel_size = upu / im.pixels_per_unit * ds
        else:
            pixel_size = float(im.pixel_size)
        translate = (float(-shift[0] + im.translate[0]), float(-shift[1] + im.translate[1]))
        if im.crop:
            img, translate = crop_to_points(img, pixel_size, translate, bbox)
            log(f"[{spec.id}] image cropped to the points: {img.shape[2]} x {img.shape[1]} px")
        if im.mask:
            img = mask_to_points(img, pixel_size, translate, xy, im.mask_margin, rgb=rgb)
            log(f"[{spec.id}] image blanked beyond {im.mask_margin:g} um of the sample's own points (a slide image shared with another section)")
        names = [ch.name for ch in im.channels] if im.channels else None
        colors = [ch.color for ch in im.channels] if im.channels else None
        wins = [ch.window for ch in im.channels] if im.channels and all(ch.window for ch in im.channels) else None
        chans = None
        if not rgb:
            # fluorescence: names from the file's OME metadata, a distinct colour each, and a window fitted to the
            # signal wherever the yaml gives none (a 16-bit channel drawn against 0..65535 looks black)
            nch = img.shape[0]
            if im.channels and len(im.channels) != nch:
                log(f"[{spec.id}] warning: `channels:` lists {len(im.channels)} entries but {im.path.name} has {nch} channels; using the file's names, default colours and fitted windows")
            listed = im.channels if im.channels and len(im.channels) == nch else None
            if nch > 6:
                log(f"[{spec.id}] note: {im.path.name} has {nch} channels; the viewer draws the first 6 until per-channel controls arrive")
            if listed is None:
                ome = ome_channel_names(im.path)
                names = ome if ome and len(ome) == nch else ([im.name] if nch == 1 else [f"{im.name} {k + 1}" for k in range(nch)])
            default_colors = ["#ffffff"] if nch == 1 else [DEFAULT_CHANNEL_COLORS[k % len(DEFAULT_CHANNEL_COLORS)] for k in range(nch)]
            colors = [(listed[k].color if listed and listed[k].color else default_colors[k]) for k in range(nch)]
            given = [ch.window for ch in listed] if listed else [None] * nch
            fitted = auto_windows(img) if any(w is None for w in given) else []
            wins = [tuple(w) if w is not None else fitted[k] for k, w in enumerate(given)]
            chans = [ImageChannel(name=names[k], color=colors[k], window=wins[k]) for k in range(nch)]
            if fitted:
                log(f"[{spec.id}] image channel windows fitted to the signal: " + ", ".join(f"{names[k]} {wins[k][0]:g}-{wins[k][1]:g}" for k in range(nch) if given[k] is None))
        elif im.channels:
            maxv = 255 if img.dtype == np.uint8 else int(np.iinfo(img.dtype).max)
            chans = [ImageChannel(name=ch.name, color=ch.color or "#ffffff", window=ch.window or (0, maxv)) for ch in im.channels]
            colors = [ch.color or "#ffffff" for ch in im.channels]
        out_path = out_dir / f"{im.id}.ome.zarr"
        write_ome_zarr(img, out_path, rgb=rgb, channel_names=names, channel_colors=colors, windows=wins)
        images.append(
            SampleImage(
                id=im.id,
                name=im.name,
                path=out_path.name,
                kind=im.kind,
                pixelSize=pixel_size,
                translate=translate,
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
        meta=meta,
        nObs=n_obs,
        nGenes=len(genes),
        bbox=bbox,
        pointRadius=radius,
        expr=ExprSpec(kind="u8", sharded=res.sharded, shardGenes=res.shard_genes, normalized="log1p_cp10k" if mode == "counts" else "lognorm"),
        hasF16=spec.expression.keep_f16,
        fields=list(spec.fields.keys()),
        images=images,
        outlines=outlines,
        shapes=shapes_info,
        molecules=molecules_info,
        suggestedGene=suggested,
        tracks=tracks_info,
    )


def _any_feature(genes: list[str], groups: list[dict]) -> str:
    """Something to color by when the dataset has no categorical field and no default: the first gene, else the
    first grouped feature (a peaks-only dataset), else a clear error instead of an IndexError after a long build."""
    if genes:
        return genes[0]
    for g in groups:
        if g.get("features"):
            return g["features"][0]["id"]
    raise ValueError("the dataset has no features to color by; check `expression:` and the inputs")


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


def gene_union(out: Path, samples: list[Sample]) -> set[str]:
    union: set[str] = set()
    for s in samples:
        with open(out / "samples" / s.id / "genes.json") as fh:
            union.update(json.load(fh))
    return union


def _write_dataset_files(out: Path, cfg: DatasetConfig, samples: list[Sample], vocab: VocabRegistry, comparisons: list[ComparisonInfo] | None = None) -> Manifest:
    union = gene_union(out, samples)
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
        dc = ColorSpec(kind="field", field=cat_fields[0].id) if cat_fields else ColorSpec(kind="gene", gene=suggested_default(samples, genes) or _any_feature(genes, groups))
    default_gene = cfg.default_gene or (dc.gene if dc.kind == "gene" else suggested_default(samples, genes))
    order = cfg.layout.order or [s.id for s in samples]
    manifest = Manifest(
        id=cfg.id,
        name=cfg.name,
        description=cfg.description,
        defaultGene=default_gene,
        defaultColor=dc,
        layout=Layout(mode=cfg.layout.mode, gutterFraction=cfg.layout.gutter_fraction, order=order, columns=cfg.layout.columns),
        colormaps=cfg.colormaps or list(BUILTIN_COLORMAPS),
        vocabularies=vocab.to_manifest(),
        fields=_fields_manifest(_all_fields(cfg, vocab), vocab),
        featureGroups=[
            FeatureGroup(id=g["id"], name=g["name"], units=g["units"], count=len(g["features"])) for g in groups
        ],
        samples=samples,
        thumbnailSample=cfg.thumbnail_sample,
        meta=meta_keys(cfg, samples),
        comparisons=comparisons or [],
    )
    with open(out / "manifest.json", "w") as fh:
        fh.write(manifest.model_dump_json(indent=1, exclude_none=True))
    with open(out / "build-info.json", "w") as fh:
        json.dump({"spatialscape": __version__, "config": str(cfg.path) if cfg.path else None, "built": datetime.now(UTC).isoformat(timespec="seconds")}, fh, indent=1)
    return manifest


def resolve_meta(spec: SampleSpec, adata) -> dict[str, str]:
    """The sample's metadata values: yaml strings as given, `{column: x}` read from obs, where it must hold one value."""
    out: dict[str, str] = {}
    for key, v in spec.meta.items():
        if isinstance(v, str):
            out[key] = v
            continue
        if v.column not in adata.obs:
            raise KeyError(f"sample {spec.id}: meta column {v.column!r} (key {key}) not found; obs columns: {', '.join(map(str, adata.obs.columns))}")
        vals = [str(x) for x in pd.unique(adata.obs[v.column].dropna().astype(str))]
        if not vals:
            raise ValueError(f"sample {spec.id}: meta column {v.column!r} (key {key}) has no values")
        if len(vals) > 1:
            raise ValueError(
                f"sample {spec.id}: meta column {v.column!r} (key {key}) holds {len(vals)} values ({', '.join(vals[:6])}{', ...' if len(vals) > 6 else ''}); "
                f"a meta key is one value per sample. Split the file into one sample per value with `subset: {{ column: {v.column}, values: [{vals[0]}] }}`, "
                "or expose the column as an annotation under `fields:`"
            )
        out[key] = vals[0]
    return out


def meta_keys(cfg: DatasetConfig, samples: list[Sample]) -> list[MetaKey]:
    """The manifest's metadata keys: declared ones first with their names and level order, then every key a sample
    uses; values a declaration does not list are appended in sample order, so nothing a sample says disappears."""
    declared = {m.id: m for m in cfg.meta}
    order = [m.id for m in cfg.meta]
    for s in samples:
        for k in s.meta:
            if k not in order:
                order.append(k)
    out: list[MetaKey] = []
    for k in order:
        d = declared.get(k)
        levels = list(d.levels or []) if d else []
        for s in samples:
            v = s.meta.get(k)
            if v is not None and v not in levels:
                levels.append(v)
        name = d.name if d and d.name else (k[:1].upper() + k[1:]).replace("_", " ")
        out.append(MetaKey(id=k, name=name, levels=levels))
    return out


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
    comparisons: list[ComparisonAction] = field(default_factory=list)
    removed_comparisons: list[str] = field(default_factory=list)

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
    plan = BuildPlan(out, actions, [f for f in folders if f not in wanted], existing)
    plan.comparisons, plan.removed_comparisons = plan_comparisons(cfg, out, samples_signature({a.spec.id: a.fingerprint for a in actions}), force=force)
    return plan


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
    if plan.comparisons:
        w = max(len(a.spec.id) for a in plan.comparisons)
        for a in plan.comparisons:
            lines.append(f"  comparison {a.spec.id:<{w}}  {'build' if a.build else 'skip '}  {a.reason}")
    for cid in plan.removed_comparisons:
        lines.append(f"  comparison {cid}: removed (no longer in the yaml)")
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
    built: list[tuple[Path, dict]] = []
    for a in plan.actions:
        if a.build:
            s = build_sample(a.spec, cfg, out / "samples" / a.spec.id, vocab, sharded=sharded, log=log)
            gc.collect()  # an AnnData is a reference cycle: free this sample's object before the next one is read
            built.append((out / "samples" / a.spec.id, a.fingerprint))
        else:
            prev = by_id[a.spec.id]
            # values given in the yaml apply without a rebuild; values read from a column were fixed when the sample was built
            meta = {k: (v if isinstance(v, str) else prev.meta.get(k)) for k, v in a.spec.meta.items()}
            s = prev.model_copy(update={"name": a.spec.name or a.spec.id, "group": a.spec.group, "meta": {k: v for k, v in meta.items() if v is not None}})
        samples.append(s)
    for sid in plan.removed:
        shutil.rmtree(out / "samples" / sid, ignore_errors=True)
        log(f"removed sample {sid}")
    comparisons: list[ComparisonInfo] = []
    if plan.comparisons:
        union = gene_union(out, samples)
        mkeys = meta_keys(cfg, samples)
        for a in plan.comparisons:
            info = None if a.build else read_info(out, a.spec.id)
            if info is None:  # to build, or a folder that lost its description
                info = write_comparison(out, a.spec, samples, mkeys, union, log=log)
                built.append((out / "comparisons" / a.spec.id, a.fingerprint))
            else:
                info = info.model_copy(update={"name": a.spec.name or a.spec.id.replace("_", " "), "description": a.spec.description, "units": a.spec.units})
            comparisons.append(info)
    for cid in plan.removed_comparisons:
        shutil.rmtree(out / "comparisons" / cid, ignore_errors=True)
        log(f"removed comparison {cid}")
    manifest = _write_dataset_files(out, cfg, samples, vocab, comparisons=comparisons)
    # Sidecars last: a sample is "current" only together with the manifest whose vocabularies its codes were
    # assigned against. A run that dies before this point leaves the new folders without sidecars (rebuilt next
    # time) and the old manifest intact, instead of a sample that decodes against the wrong categories.
    for d, fp in built:
        write_sidecar(d, fp)
    return manifest


@dataclass
class BuildResult:
    out: Path
    plan: BuildPlan
    manifest: Manifest | None  # None for a dry run
    problems: list[str] = field(default_factory=list)


def build_bundle(cfg: DatasetConfig, out: Path | None = None, *, sharded: bool | None = None, force: bool = False, dry_run: bool = False, log: Log = print) -> BuildResult:
    """Everything `spatialscape build` does: convert R objects into the cache, plan, build, render thumbnails,
    validate. `site build` runs the same for every dataset yaml it lists. `sharded` defaults to the yaml's
    `sharded:` so a bundle built for a host without Range support stays that way in every later build."""
    if sharded is None:
        sharded = cfg.sharded
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
