"""Fidelity: what a bundle stores against the data it was built from.

The viewer draws 8-bit codes, positions through a frame transform, decoded shape and molecule tiles, and tests on
the per-cell row store. Each check here reads the bundle back with the reference decoders (the same functions
`validate` uses) and the source through the package's readers, then measures the difference:

- expression: dequantised codes against the normalised source column, for a sample of genes. The bound is half a
  code step, (gmax - gmin) / 510, except for a positive value under half a step, which the build rounds up to code 1
  so an expressed cell never draws as zero (error up to one step). Zeros are exact.
- rows: the row store against the same source rows, and against the gene-major codes (one encoding, two layouts).
- positions: obs.zarr/xy against the source coordinates through the micron rule, flip, rotation and shift;
  `order` against the build's permutation; ids against obs_names.
- shapes: every ring's vertices against the source polygons through the same frame, within half a grid step.
- molecules: per gene, the count and the nearest-neighbour distance between stored and source positions, after
  the build's quality and control-feature filters.
- the browser test: a dump of the viewer's region test (app/e2e/fidelity.spec.ts) against the same statistics
  computed here from the row store, and against scipy's Mann-Whitney on the dequantised values.

Run on a bundle: `python -m spatialscape.fidelity bundle dataset.yaml bundles/<id> [--sample ID] [--out report.json]`.
Check a browser dump: `python -m spatialscape.fidelity browser-de dump.json bundles/<id>`.
The tests in python/tests/test_fidelity.py run the same functions on the synthetic dataset in CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import scipy.sparse as sp
import zarr

from .config import DatasetConfig, SampleSpec, load_config
from .expression import get_matrix, log1p_cp10k
from .geometry import microns_per_unit, transform_points
from .molecules import CONTROL_RE, read_molecules
from .molecules import GRID as MOLECULE_GRID
from .polygons import apply_affine, read_polygon_labels, read_polygon_obsm, read_polygon_table
from .readers import SampleInput, load_sample
from .rows import read_rows
from .shapes import GRID as SHAPE_GRID
from .shapes import read_shapes, rings_from_vertices, thin

MIN_CELLS = 3  # as app/src/data/de.ts
DEFAULT_MIN_PCT = 0.1


# --- source side -----------------------------------------------------------


def source_matrix(spec: SampleSpec, sinput: SampleInput, normalized: str | None) -> sp.csc_matrix:
    """The normalised source matrix (n_obs, n_vars) as CSC, on the scale the bundle records: `log1p_cp10k` means
    the build applied it to counts; `lognorm` and `raw` mean the layer was stored as it was."""
    M = get_matrix(sinput.adata, spec.expression.layer)
    if normalized == "log1p_cp10k":
        M = log1p_cp10k(M)
    Mc = sp.csc_matrix(M, dtype=np.float32)
    Mc.sum_duplicates()
    return Mc


def kept_columns(Mc: sp.csc_matrix) -> np.ndarray:
    """Source columns the build keeps: features with a value other than zero somewhere."""
    keep = np.zeros(Mc.shape[1], dtype=bool)
    nz = np.diff(Mc.indptr) > 0
    for j in np.flatnonzero(nz):
        d = Mc.data[Mc.indptr[j] : Mc.indptr[j + 1]]
        keep[j] = bool(d.max() > 0 or d.min() < 0)
    return np.flatnonzero(keep)


def source_frame(spec: SampleSpec, sinput: SampleInput) -> dict[str, Any]:
    """The frame the build put the sample in: microns per unit, the flip/rotate frame size, and the shift that
    moved the cells' minimum to the origin. Mirrors build.py, computed from the spec alone."""
    upu = microns_per_unit(spec, sinput)
    coords = np.asarray(sinput.coords, dtype=np.float64)
    auto_px = [im for im in spec.images if im.pixel_size == "auto"] if isinstance(spec.images, list) else []
    if auto_px:
        from .images import read_image_shape

        im0 = auto_px[0]
        _c, h, w = read_image_shape(im0.path, rgb=im0.kind == "rgb")
        if im0.transpose:
            h, w = w, h
        width, height = w / im0.pixels_per_unit + im0.offset[0], h / im0.pixels_per_unit + im0.offset[1]
    else:
        width, height = float(coords[:, 0].max()), float(coords[:, 1].max())
    xy = transform_points(coords, width, height, spec.transform.flip, spec.transform.rotate) * upu
    shift = xy.min(axis=0)
    return {"upu": upu, "width": width, "height": height, "shift": shift, "xy": xy - shift}


def to_frame(frame: dict[str, Any], spec: SampleSpec, raw: np.ndarray, affine=None) -> np.ndarray:
    """Raw source points (n, 2) into the sample frame in microns, as the build's _Frame.points does."""
    if affine:
        x, y = apply_affine(raw[:, 0], raw[:, 1], affine)
        raw = np.column_stack([x, y])
    return (
        transform_points(raw, frame["width"], frame["height"], spec.transform.flip, spec.transform.rotate)
        * frame["upu"]
        - frame["shift"]
    )


def build_permutation(spec: SampleSpec, n_obs: int) -> np.ndarray:
    """Bundle row i holds source observation perm[i]."""
    return np.random.default_rng(spec.seed).permutation(n_obs)


# --- bundle side -----------------------------------------------------------


def dequantize(codes: np.ndarray, gmin: np.ndarray, gmax: np.ndarray) -> np.ndarray:
    """What the viewer shows for a code: gmin + code / 255 * (gmax - gmin), in float32 like the shader."""
    gmin = np.asarray(gmin, dtype=np.float32)
    gmax = np.asarray(gmax, dtype=np.float32)
    return (gmin + codes.astype(np.float32) / np.float32(255) * (gmax - gmin)).astype(np.float32)


def _expr(sample_dir: Path):
    g = zarr.open_group(str(sample_dir / "expr.zarr"), mode="r")
    gmin = np.asarray(g["gmin"][:], dtype=np.float32) if "gmin" in g else np.zeros(g["u8"].shape[0], dtype=np.float32)
    return g["u8"], gmin, np.asarray(g["gmax"][:], dtype=np.float32)


def _genes(sample_dir: Path) -> list[str]:
    return json.loads((sample_dir / "genes.json").read_text())


def _zero_genes(sample_dir: Path) -> list[str]:
    p = sample_dir / "zero_genes.json"
    return json.loads(p.read_text()) if p.exists() else []


def _ids(sample_dir: Path) -> list[str]:
    ids: list[str] = []
    for b in sorted((sample_dir / "ids").glob("*.json"), key=lambda p: int(p.stem)):
        ids.extend(json.loads(b.read_text()))
    return ids


# --- checks -----------------------------------------------------------------


def _gene_errors(vals: np.ndarray, src: np.ndarray, gmin: float, gmax: float) -> dict[str, float]:
    from scipy.stats import pearsonr, spearmanr

    span = float(gmax - gmin)
    err = np.abs(vals.astype(np.float64) - src.astype(np.float64))
    bumped = (gmin >= 0) & (src > 0) & (src * 255 / span < 0.5) if span > 0 else np.zeros_like(src, dtype=bool)
    out = {
        "max_error": float(err.max()),
        "max_error_steps": float(err.max() / (span / 255)) if span > 0 else 0.0,  # 0.5 is half a code step
        "max_error_steps_unbumped": float(err[~bumped].max() / (span / 255)) if span > 0 and (~bumped).any() else 0.0,
        "bumped": int(bumped.sum()),
    }
    if gmin >= 0:
        out["zeros_preserved"] = bool(np.array_equal(src == 0, vals == 0))
        out["nonzero_preserved"] = bool(np.all(vals[src > 0] > 0))
    if src.std() > 0 and vals.std() > 0:
        out["pearson"] = float(pearsonr(src, vals)[0])
        out["spearman"] = float(spearmanr(src, vals)[0])
    return out


def check_expression(
    sample_dir: Path, Mc: sp.csc_matrix, perm: np.ndarray, kept: np.ndarray, *, n_genes: int = 200, seed: int = 0
) -> dict[str, Any]:
    """Dequantised gene-major codes against the source, for `n_genes` random kept genes."""
    u8, gmin, gmax = _expr(sample_dir)
    genes = _genes(sample_dir)
    if len(genes) != len(kept):
        raise AssertionError(f"{sample_dir.name}: {len(genes)} stored genes, {len(kept)} nonzero source columns")
    rng = np.random.default_rng(seed)
    pick = np.sort(rng.choice(len(kept), size=min(n_genes, len(kept)), replace=False))
    per_gene = {}
    for i in pick:
        j = int(kept[i])
        codes = np.asarray(u8[int(i), :])
        src = Mc[:, j].toarray().ravel()[perm]
        per_gene[genes[i]] = _gene_errors(dequantize(codes, gmin[i], gmax[i]), src, float(gmin[i]), float(gmax[i]))
    vals = list(per_gene.values())
    return {
        "genes_checked": len(vals),
        "max_error_steps": max(v["max_error_steps"] for v in vals),
        "max_error_steps_unbumped": max(v["max_error_steps_unbumped"] for v in vals),
        "bumped_values": sum(v["bumped"] for v in vals),
        "zeros_preserved": all(v.get("zeros_preserved", True) for v in vals),
        "nonzero_preserved": all(v.get("nonzero_preserved", True) for v in vals),
        "min_pearson": min(v["pearson"] for v in vals if "pearson" in v),
        "min_spearman": min(v["spearman"] for v in vals if "spearman" in v),
        "per_gene": per_gene,
    }


def check_rows(
    sample_dir: Path, Mc: sp.csc_matrix, perm: np.ndarray, kept: np.ndarray, *, n_rows: int = 500, seed: int = 0
) -> dict[str, Any]:
    """The row store against the source rows and against the gene-major codes."""
    if not (sample_dir / "rows.zarr").exists():
        return {"present": False}
    u8, gmin, gmax = _expr(sample_dir)
    n_obs = u8.shape[1]
    rng = np.random.default_rng(seed)
    rows = np.sort(rng.choice(n_obs, size=min(n_rows, n_obs), replace=False))
    R = read_rows(sample_dir, rows)  # (len(rows), kept genes) codes
    if R.shape[1] != len(kept):
        raise AssertionError(f"{sample_dir.name}: row store has {R.shape[1]} genes, the gene-major store {len(kept)}")
    column_codes = np.asarray(u8[:, rows]).T  # (len(rows), G)
    R_dense = R.toarray()
    same_codes = bool(np.array_equal(R_dense, column_codes))
    Mr = sp.csr_matrix(Mc)[perm[rows]][:, kept].toarray()
    vals = dequantize(R_dense, gmin[None, :], gmax[None, :])
    span = gmax - gmin
    with np.errstate(divide="ignore", invalid="ignore"):
        steps = np.abs(vals.astype(np.float64) - Mr) / np.where(span > 0, span / 255, np.inf)[None, :]
    bumped = (gmin[None, :] >= 0) & (Mr > 0) & (Mr * 255 / np.where(span > 0, span, np.inf)[None, :] < 0.5)
    return {
        "present": True,
        "rows_checked": len(rows),
        "codes_match_gene_major": same_codes,
        "max_error_steps": float(steps.max()),
        "max_error_steps_unbumped": float(steps[~bumped].max()) if (~bumped).any() else 0.0,
        "zeros_preserved": bool(
            np.array_equal((Mr == 0) & (gmin[None, :] >= 0), (R_dense == 0) & (gmin[None, :] >= 0))
        ),
    }


def check_positions(
    sample_dir: Path, spec: SampleSpec, sinput: SampleInput, frame: dict[str, Any], perm: np.ndarray
) -> dict[str, Any]:
    g = zarr.open_group(str(sample_dir / "obs.zarr"), mode="r")
    xy = np.asarray(g["xy"][:], dtype=np.float64)
    order = np.asarray(g["order"][:])
    expected = frame["xy"][perm]
    err = np.abs(xy - expected)
    ids = _ids(sample_dir)
    names = [str(s) for s in sinput.adata.obs_names[perm]]
    return {
        "cells": len(xy),
        "max_error_um": float(err.max()),
        "order_is_build_permutation": bool(np.array_equal(order, perm)),
        "ids_match": ids == names,
        "extent_um": [float(v) for v in xy.max(axis=0)],
    }


def _source_rings(
    spec: SampleSpec, sinput: SampleInput, frame: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    """(rows, starts, counts, xy_um) of the source polygons of known cells, grouped and thinned as the build does."""
    ps = spec.polygons
    if not ps:
        return None
    if ps.obsm:
        pids, px, py = read_polygon_obsm(sinput.adata, ps.obsm)
    elif ps.labels:
        pids, px, py = read_polygon_labels(ps.labels, ps.max_vertices)
    else:
        pids, px, py = read_polygon_table(ps.path, ps.id_column, ps.x_column, ps.y_column)
    pxy = to_frame(frame, spec, np.column_stack([px, py]), ps.affine)
    obs_ids = [str(s) for s in sinput.adata.obs_names]
    rows, starts, counts, _unmatched, _degenerate = rings_from_vertices(
        obs_ids, pids, pxy, max_vertices=ps.max_vertices
    )
    vidx, counts = thin(starts, counts, max(3, min(int(ps.max_vertices), 255)))
    return rows, np.cumsum(np.concatenate([[0], counts[:-1]])), counts, pxy[vidx]


def check_shapes(
    sample_dir: Path, spec: SampleSpec, sinput: SampleInput, frame: dict[str, Any], perm: np.ndarray
) -> dict[str, Any]:
    if not (sample_dir / "shapes.json").exists():
        return {"present": False}
    src = _source_rings(spec, sinput, frame)
    if src is None:
        return {"present": True, "source": False}
    rows, starts, counts, vxy = src
    inv = np.empty(len(perm), dtype=np.int64)
    inv[perm] = np.arange(len(perm))
    stored = read_shapes(sample_dir)
    max_err = 0.0
    missing = 0
    count_mismatch = 0
    for r, s, c in zip(rows, starts, counts, strict=True):
        ring = stored.get(int(inv[r]))
        if ring is None:
            missing += 1
            continue
        if len(ring) != c:
            count_mismatch += 1
            continue
        max_err = max(max_err, float(np.abs(ring - vxy[s : s + c]).max()))
    return {
        "present": True,
        "source_rings": len(rows),
        "stored_rings": len(stored),
        "missing": missing,
        "vertex_count_mismatch": count_mismatch,
        "max_vertex_error_um": max_err,
        "grid_um": SHAPE_GRID,
    }


def check_molecules(
    sample_dir: Path, spec: SampleSpec, frame: dict[str, Any], *, n_genes: int = 20, seed: int = 0
) -> dict[str, Any]:
    """Per gene: stored molecules against the source rows past the build's filters, by count and nearest-neighbour
    distance (the tiles store positions on a 1/64 um grid)."""
    from scipy.spatial import cKDTree

    from .tables import iter_batches, table_columns

    if not (sample_dir / "molecules.json").exists():
        return {"present": False}
    ms = spec.molecules
    if not ms:
        return {"present": True, "source": False}
    names, gene, xy, _flags = read_molecules(sample_dir)
    rng = np.random.default_rng(seed)
    pick = sorted(rng.choice(len(names), size=min(n_genes, len(names)), replace=False).tolist())
    chosen = {names[i]: i for i in pick}
    cols = [ms.feature_column, ms.x_column, ms.y_column]
    present = set(table_columns(ms.path))
    qv = ms.qv_column if ms.qv_column and ms.qv_column in present else None
    if qv:
        cols.append(qv)
    affine = ms.affine or (spec.polygons.affine if spec.polygons else None)
    src: dict[str, list[np.ndarray]] = {g: [] for g in chosen}
    for t in iter_batches(ms.path, cols):
        feat = np.asarray(t.column(ms.feature_column).to_pylist(), dtype=str)
        ok = np.isin(feat, list(chosen))
        if qv:
            ok &= t.column(qv).to_numpy(zero_copy_only=False) >= ms.min_qv
        if not ok.any():
            continue
        raw = np.column_stack(
            [t.column(ms.x_column).to_numpy(zero_copy_only=False), t.column(ms.y_column).to_numpy(zero_copy_only=False)]
        ).astype(np.float64)[ok]
        pts = to_frame(frame, spec, raw, affine)
        for g in np.unique(feat[ok]):
            src[g].append(pts[feat[ok] == g])
    per_gene = {}
    for g, gi in chosen.items():
        s = np.concatenate(src[g]) if src[g] else np.zeros((0, 2))
        b = xy[gene == gi]
        entry: dict[str, Any] = {"source": len(s), "stored": len(b)}
        if len(s) and len(b):
            d, _ = cKDTree(s).query(b)
            entry["max_nn_distance_um"] = float(d.max())
        per_gene[g] = entry
    return {
        "present": True,
        "genes_checked": len(per_gene),
        "counts_match": all(v["source"] == v["stored"] for v in per_gene.values()),
        "max_nn_distance_um": max((v.get("max_nn_distance_um", 0.0) for v in per_gene.values()), default=0.0),
        "grid_um": MOLECULE_GRID,
        "controls_in_store": [n for n in names if CONTROL_RE.match(n)],
        "per_gene": per_gene,
    }


def check_sample(
    cfg: DatasetConfig,
    spec: SampleSpec,
    bundle: Path,
    *,
    n_genes: int = 200,
    n_rows: int = 500,
    molecule_genes: int = 20,
    seed: int = 0,
) -> dict[str, Any]:
    """Every check for one sample of a built bundle."""
    from .fingerprint import resolve_auto_images
    from .sdata import resolve_sample

    manifest = json.loads((bundle / "manifest.json").read_text())
    entry = next((s for s in manifest["samples"] if s["id"] == spec.id), None)
    if entry is None:
        raise KeyError(f"sample {spec.id} is not in {bundle / 'manifest.json'}")
    sample_dir = bundle / "samples" / spec.id
    spec = resolve_sample(spec)
    if spec.images == "auto" or spec.microns == type(spec.microns)():
        spec = resolve_auto_images(spec)
    sinput = load_sample(spec)
    perm = build_permutation(spec, sinput.adata.n_obs)
    Mc = source_matrix(spec, sinput, entry.get("expr", {}).get("normalized"))
    kept = kept_columns(Mc)
    frame = source_frame(spec, sinput)
    out: dict[str, Any] = {
        "sample": spec.id,
        "platform": spec.platform,
        "normalized": entry.get("expr", {}).get("normalized"),
        "expression": check_expression(sample_dir, Mc, perm, kept, n_genes=n_genes, seed=seed),
        "rows": check_rows(sample_dir, Mc, perm, kept, n_rows=n_rows, seed=seed),
        "positions": check_positions(sample_dir, spec, sinput, frame, perm),
    }
    if spec.kind == "spatial":
        out["shapes"] = check_shapes(sample_dir, spec, sinput, frame, perm)
        out["molecules"] = check_molecules(sample_dir, spec, frame, n_genes=molecule_genes, seed=seed)
    zero = _zero_genes(sample_dir)
    expected = int(Mc.shape[1] - len(kept))
    # a bundle built before 0.6 has no list and no count in its manifest: stale, not wrong
    out["zero_genes"] = {
        "listed": len(zero),
        "expected": expected,
        "match": len(zero) == expected,
        "in_bundle": "nZeroGenes" in entry,
    }
    return out


def check_bundle(config: Path, bundle: Path, *, samples: list[str] | None = None, **kw) -> dict[str, Any]:
    cfg = load_config(config)
    out = {"dataset": cfg.id, "bundle": str(bundle), "samples": []}
    for spec in cfg.samples:
        if samples and spec.id not in samples:
            continue
        out["samples"].append(check_sample(cfg, spec, bundle, **kw))
    return out


def verdict(report: dict[str, Any]) -> list[str]:
    """What is wrong, in words; empty when every check holds."""
    problems = []
    for s in report["samples"]:
        e = s["expression"]
        if e["max_error_steps_unbumped"] > 0.5 + 1e-3:
            problems.append(
                f"{s['sample']}: a dequantised value is {e['max_error_steps_unbumped']:.3f} code steps off (bound 0.5)"
            )
        if e["max_error_steps"] > 1 + 1e-3:
            problems.append(f"{s['sample']}: a rounded-up value is {e['max_error_steps']:.3f} code steps off (bound 1)")
        if not e["zeros_preserved"] or not e["nonzero_preserved"]:
            problems.append(f"{s['sample']}: zeros or nonzeros are not preserved exactly")
        r = s["rows"]
        if r.get("present") and (
            not r["codes_match_gene_major"] or r["max_error_steps_unbumped"] > 0.5 + 1e-3 or not r["zeros_preserved"]
        ):
            problems.append(f"{s['sample']}: the row store disagrees with the gene-major store or the source")
        p = s["positions"]
        if (
            p["max_error_um"] > 1e-3 * max(1.0, max(p["extent_um"]) / 1e4)
            or not p["order_is_build_permutation"]
            or not p["ids_match"]
        ):
            problems.append(
                f"{s['sample']}: positions, order or ids differ from the source ({p['max_error_um']:.2g} um)"
            )
        sh = s.get("shapes", {})
        if (
            sh.get("present")
            and sh.get("source") is not False
            and (sh["missing"] or sh["vertex_count_mismatch"] or sh["max_vertex_error_um"] > sh["grid_um"] / 2 + 1e-9)
        ):
            problems.append(
                f"{s['sample']}: shapes differ from the source polygons (max {sh['max_vertex_error_um']:.3f} um, {sh['missing']} missing)"
            )
        m = s.get("molecules", {})
        if (
            m.get("present")
            and m.get("source") is not False
            and (
                not m["counts_match"] or m["max_nn_distance_um"] > m["grid_um"] * 0.71 + 1e-9 or m["controls_in_store"]
            )
        ):
            problems.append(
                f"{s['sample']}: molecules differ from the source table (max {m['max_nn_distance_um']:.4f} um, counts match: {m['counts_match']})"
            )
        z = s["zero_genes"]
        if not z["in_bundle"] and z["expected"]:
            problems.append(
                f"{s['sample']}: built before the zero-gene list existed; its {z['expected']} all-zero features draw as unmeasured until it is rebuilt"
            )
        elif not z["match"]:
            problems.append(
                f"{s['sample']}: zero_genes.json lists {z['listed']} features, the source has {z['expected']} all-zero columns"
            )
    return problems


# --- the browser test --------------------------------------------------------


def point_in_polygon(xy: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Ray casting with the viewer's exact rule (app/src/views/geometry.ts), vectorised over points."""
    x, y = xy[:, 0], xy[:, 1]
    inside = np.zeros(len(xy), dtype=bool)
    n = len(poly)
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[i - 1]
        cross = (yi > y) != (yj > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (xj - xi) * (y - yi) / (yj - yi) + xi
        inside ^= cross & (x < xint)
    return inside


def _bh(p: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg over the finite entries; NaN stays NaN."""
    q = np.full(len(p), np.nan)
    ok = np.isfinite(p)
    if not ok.any():
        return q
    ps = p[ok]
    m = len(ps)
    order = np.argsort(ps)
    adj = ps[order] * m / np.arange(1, m + 1)
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.minimum(adj, 1)
    q[ok] = out
    return q


def reference_level(
    bundle: Path, genes: list[str], sides: dict[str, tuple[np.ndarray, np.ndarray]], *, min_pct: float = DEFAULT_MIN_PCT
) -> dict[str, np.ndarray]:
    """The viewer's level test, from the row store: `sides` maps a sample id to (rows of side a, rows of side b),
    bundle row indices. Returns per-gene arrays over `genes` with the viewer's rules (sections that measured the
    gene, expm1 means with a pseudocount, MIN_CELLS, min_pct, BH over the tested genes), p from scipy."""
    from scipy.stats import mannwhitneyu

    manifest = json.loads((bundle / "manifest.json").read_text())
    by_id = {s["id"]: s for s in manifest["samples"]}
    gi = {g: i for i, g in enumerate(genes)}
    G = len(genes)
    sections = list(sides)
    n_sec = len(sections)
    measured = np.zeros((G, n_sec), dtype=bool)
    n_cells = np.zeros((n_sec, 2))
    sums = np.zeros((G, n_sec, 2))  # un-logged sums
    cnt = np.zeros((G, 2), dtype=np.int64)
    values: list[list[np.ndarray]] = [[], []]  # per side, per section: csc of dequantised values in gene space
    scale = "raw" if any(by_id[s]["expr"].get("normalized") == "raw" for s in sections) else "log"
    unlog = (lambda v: v) if scale == "raw" else np.expm1
    for k, sid in enumerate(sections):
        d = bundle / "samples" / sid
        local = _genes(d)
        _u8, gmin, gmax = _expr(d)
        col = np.array(
            [gi.get(g, -1) if gmin[j] >= 0 else -1 for j, g in enumerate(local)]
        )  # local -> level gene; signed features excluded
        for g in _zero_genes(d):
            if g in gi:
                measured[gi[g], k] = True
        measured[col[col >= 0], k] = True
        for side, rows in enumerate(sides[sid]):
            n_cells[k, side] += len(rows)
            if not len(rows):
                values[side].append(sp.csc_matrix((0, G), dtype=np.float32))
                continue
            R = read_rows(d, rows).tocoo()
            keep = col[R.col] >= 0
            v = (R.data[keep].astype(np.float32) * (gmax[R.col[keep]] / np.float32(255))).astype(
                np.float32
            )  # as the worker: code * gmax/255
            Mv = sp.csc_matrix((v, (R.row[keep], col[R.col[keep]])), shape=(len(rows), G))
            values[side].append(Mv)
            per_gene = np.diff(Mv.indptr)
            cnt[:, side] += per_gene
            sums[:, k, side] += np.bincount(
                np.repeat(np.arange(G), per_gene), weights=unlog(Mv.data.astype(np.float64)), minlength=G
            )
    cells = np.zeros((G, 2))
    for k in range(n_sec):
        cells[measured[:, k], 0] += n_cells[k, 0]
        cells[measured[:, k], 1] += n_cells[k, 1]
    nan = np.full(G, np.nan)
    pct_in, pct_out, effect, p, auc, agree = (nan.copy() for _ in range(6))
    sec_both = [k for k in range(n_sec) if n_cells[k, 0] >= MIN_CELLS and n_cells[k, 1] >= MIN_CELLS]
    lfc = lambda sa, na, sb, nb: np.log2((sa / na + 1) / (sb / nb + 1))  # noqa: E731
    A = sp.vstack(values[0]).tocsc() if values[0] else sp.csc_matrix((0, G))
    B = sp.vstack(values[1]).tocsc() if values[1] else sp.csc_matrix((0, G))
    for g in range(G):
        if not measured[g].any():
            continue
        na, nb = cells[g]
        pct_in[g] = cnt[g, 0] / na if na else np.nan
        pct_out[g] = cnt[g, 1] / nb if nb else np.nan
        if not na or not nb:
            continue
        e = lfc(sums[g, :, 0].sum(), na, sums[g, :, 1].sum(), nb)
        effect[g] = e
        own = [k for k in sec_both if measured[g, k]]
        if own:
            agree[g] = sum(
                1
                for k in own
                if (es := lfc(sums[g, k, 0], n_cells[k, 0], sums[g, k, 1], n_cells[k, 1])) != 0
                and np.sign(es) == np.sign(e)
            )
        if na < MIN_CELLS or nb < MIN_CELLS or max(pct_in[g], pct_out[g]) < min_pct:
            continue
        a = A.data[A.indptr[g] : A.indptr[g + 1]]
        b = B.data[B.indptr[g] : B.indptr[g + 1]]
        a_full = np.concatenate([a, np.zeros(int(na) - len(a), dtype=np.float32)])
        b_full = np.concatenate([b, np.zeros(int(nb) - len(b), dtype=np.float32)])
        r = mannwhitneyu(a_full, b_full, alternative="two-sided", method="asymptotic", use_continuity=True)
        auc[g] = float(r.statistic) / (na * nb)
        p[g] = float(r.pvalue)
    return {
        "effect": effect,
        "p": p,
        "padj": _bh(p),
        "pct_in": pct_in,
        "pct_out": pct_out,
        "auc": auc,
        "agree": agree,
        "n_sections": np.array(len(sec_both)),
    }


def compare_browser_de(dump: dict[str, Any], bundle: Path) -> dict[str, Any]:
    """A dump written by app/e2e/fidelity.spec.ts against the reference: per level, the largest disagreement in each
    statistic over the genes both report, and whether the set of tested genes is the same."""
    genes = dump["genes"]
    k = len(dump["levels"])
    out: dict[str, Any] = {"levels": []}
    codes = {sid: np.asarray(v, dtype=np.int64) for sid, v in dump["codes"].items()}
    manifest = json.loads((bundle / "manifest.json").read_text())
    platform = {s["id"]: s["platform"] for s in manifest["samples"]}
    for j, lv in enumerate(dump["levels"]):
        ci, plat = lv["id"].split(":", 1)
        ci = int(ci)
        sides = {}
        for sid, c in codes.items():
            if platform.get(sid) != plat:
                continue
            if dump["mode"] == "pair":
                a, b = np.flatnonzero(c == 0), np.flatnonzero(c == 1)
            else:  # one group against the rest: every other cell of the sections drawn on
                a, b = np.flatnonzero(c == ci), np.flatnonzero(c != ci)
            if len(a) or len(b):
                sides[sid] = (a.astype(np.int64), b.astype(np.int64))
        ref = reference_level(bundle, genes, sides)
        entry: dict[str, Any] = {"id": lv["id"], "cells": {s: [len(a), len(b)] for s, (a, b) in sides.items()}}
        for stat in ("effect", "p", "padj", "pct_in", "pct_out", "auc", "agree"):
            if stat not in dump["stats"]:
                continue
            got = np.asarray(dump["stats"][stat], dtype=np.float64).reshape(len(genes), k)[:, j]
            exp = ref[stat]
            both = np.isfinite(got) & np.isfinite(exp)
            entry[stat] = {
                "same_tested_set": bool(np.array_equal(np.isfinite(got), np.isfinite(exp))),
                "n": int(both.sum()),
                "max_abs_diff": float(np.abs(got[both] - exp[both]).max()) if both.any() else 0.0,
                "max_rel_diff": float((np.abs(got[both] - exp[both]) / np.maximum(np.abs(exp[both]), 1e-300)).max())
                if both.any()
                else 0.0,
            }
        if "p" in entry:
            gp = np.asarray(dump["stats"]["p"], dtype=np.float64).reshape(len(genes), k)[:, j]
            rp = ref["p"]
            both = np.isfinite(gp) & np.isfinite(rp)
            # the viewer stores p as float32: below ~1e-38 it underflows, so log10 is compared where both are above that
            tiny = 1e-30
            small = both & ((gp < tiny) | (rp < tiny))
            fine = both & ~small
            with np.errstate(divide="ignore"):
                entry["p"]["max_abs_log10_diff"] = (
                    float(np.abs(np.log10(gp[fine]) - np.log10(rp[fine])).max()) if fine.any() else 0.0
                )
            entry["p"]["underflow_agrees"] = bool(np.all((gp[small] < tiny) & (rp[small] < tiny)))
            entry["p"]["n_underflow"] = int(small.sum())
        entry["sections_with_both_sides"] = int(ref["n_sections"])
        out["levels"].append(entry)
    return out


def browser_de_problems(cmp: dict[str, Any]) -> list[str]:
    """Where the viewer's numbers leave the reference: float32 storage allows ~1e-6 relative on the statistics and
    a few 1e-4 in log10 p; anything larger, or a different set of tested genes, is a problem."""
    problems = []
    tol = {"effect": 2e-4, "pct_in": 1e-6, "pct_out": 1e-6, "auc": 1e-5, "agree": 0.0, "padj": 1e-4}
    for lv in cmp["levels"]:
        for stat, t in tol.items():
            e = lv.get(stat)
            if not e:
                continue
            if not e["same_tested_set"]:
                problems.append(f"{lv['id']}: {stat} is reported for a different set of genes than the reference")
            if not (e["max_abs_diff"] <= t):
                problems.append(f"{lv['id']}: {stat} differs by {e['max_abs_diff']:.2e} (tolerance {t:g})")
        p = lv.get("p")
        if p:
            if not p["same_tested_set"]:
                problems.append(f"{lv['id']}: p is reported for a different set of genes than the reference")
            if not (p["max_abs_log10_diff"] <= 1e-3):
                problems.append(f"{lv['id']}: p differs by {p['max_abs_log10_diff']:.2e} in log10 (tolerance 1e-3)")
            if not p["underflow_agrees"]:
                problems.append(f"{lv['id']}: a p-value under 1e-30 on one side is not under 1e-30 on the other")
    return problems


# --- command line --------------------------------------------------------------


def _summary(report: dict[str, Any]) -> str:
    lines = []
    for s in report["samples"]:
        e, r, p = s["expression"], s["rows"], s["positions"]
        lines.append(f"{s['sample']} ({s['platform']}, {s['normalized']}): {p['cells']:,} cells")
        lines.append(
            f"  expression: {e['genes_checked']} genes, max error {e['max_error_steps_unbumped']:.3f} code steps (bound 0.5), {e['bumped_values']} values rounded up to code 1, zeros exact: {e['zeros_preserved']}, min Pearson {e['min_pearson']:.6f}, min Spearman {e['min_spearman']:.6f}"
        )
        if r.get("present"):
            lines.append(
                f"  rows: {r['rows_checked']} cells, codes equal the gene-major store: {r['codes_match_gene_major']}, max error {r['max_error_steps_unbumped']:.3f} steps"
            )
        lines.append(
            f"  positions: max error {p['max_error_um']:.2e} um, order = build permutation: {p['order_is_build_permutation']}, ids match: {p['ids_match']}"
        )
        sh = s.get("shapes", {})
        if sh.get("present") and sh.get("source") is not False:
            lines.append(
                f"  shapes: {sh['stored_rings']:,} rings stored of {sh['source_rings']:,} in the source, {sh['missing']} missing, max vertex error {sh['max_vertex_error_um']:.4f} um (grid {sh['grid_um']})"
            )
        m = s.get("molecules", {})
        if m.get("present") and m.get("source") is not False:
            lines.append(
                f"  molecules: {m['genes_checked']} genes, counts match: {m['counts_match']}, max position error {m['max_nn_distance_um']:.5f} um (grid {m['grid_um']:.4g})"
            )
        z = s["zero_genes"]
        lines.append(f"  zero genes listed: {z['listed']} (source has {z['expected']})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m spatialscape.fidelity", description="Fidelity of a built bundle against its source."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser(
        "bundle", help="dequantised expression, rows, positions, shapes and molecules against the source"
    )
    b.add_argument("config", type=Path)
    b.add_argument("bundle", type=Path)
    b.add_argument("--sample", action="append", help="only these sample ids (repeatable)")
    b.add_argument("--genes", type=int, default=200)
    b.add_argument("--rows", type=int, default=500)
    b.add_argument("--molecule-genes", type=int, default=20)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--out", type=Path, help="write the full report as JSON")
    d = sub.add_parser("browser-de", help="a region-test dump from the viewer against the reference")
    d.add_argument("dump", type=Path)
    d.add_argument("bundle", type=Path)
    d.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "bundle":
        report = check_bundle(
            args.config,
            args.bundle,
            samples=args.sample,
            n_genes=args.genes,
            n_rows=args.rows,
            molecule_genes=args.molecule_genes,
            seed=args.seed,
        )
        print(_summary(report))
        problems = verdict(report)
    else:
        report = compare_browser_de(json.loads(args.dump.read_text()), args.bundle)
        for lv in report["levels"]:
            cells = ", ".join(f"{s} {a:,}/{b:,}" for s, (a, b) in lv["cells"].items())
            print(
                f"{lv['id']}: {cells}; p max |dlog10| {lv['p']['max_abs_log10_diff']:.2e} over {lv['p']['n']} genes; effect max diff {lv['effect']['max_abs_diff']:.2e}; auc {lv['auc']['max_abs_diff']:.2e}; padj {lv['padj']['max_abs_diff']:.2e}"
            )
        problems = browser_de_problems(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
        )
    for pr in problems:
        print("PROBLEM:", pr)
    print("ok" if not problems else f"{len(problems)} problem{'s' if len(problems) != 1 else ''}")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
