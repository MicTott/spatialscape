"""Boundary polylines for categorical fields (e.g. spatial domains), computed from a bundle's obs arrays.

Approach: rasterize labels onto a grid (nearest point within ~0.75 x spacing), majority-smooth,
trace each category with marching squares, simplify (RDP), and store as µm polylines.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

MAX_GRID_CELLS = 2_000_000
BACKGROUND = -1


def _median_nn(xy: np.ndarray, sample: int = 3000, seed: int = 0) -> float:
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(xy), size=min(sample, len(xy)), replace=False)
    d, _ = cKDTree(xy).query(xy[idx], k=2)
    return float(np.median(d[:, 1]))


def _rdp(points: np.ndarray, tol: float) -> np.ndarray:
    """Iterative Ramer-Douglas-Peucker for an (n, 2) polyline."""
    n = len(points)
    if n < 3:
        return points
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        seg = points[b] - points[a]
        L = np.hypot(*seg)
        pts = points[a + 1 : b]
        if L == 0:
            d = np.hypot(*(pts - points[a]).T)
        else:
            d = np.abs(seg[0] * (points[a][1] - pts[:, 1]) - (points[a][0] - pts[:, 0]) * seg[1]) / L
        i = int(np.argmax(d))
        if d[i] > tol:
            k = a + 1 + i
            keep[k] = True
            stack.append((a, k))
            stack.append((k, b))
    return points[keep]


def compute_outlines(
    xy: np.ndarray,
    codes: np.ndarray,
    n_categories: int,
    *,
    skip_codes: set[int] | None = None,
    bin_um: float | None = None,
    min_cells: int = 25,
    smooth_um: float = 150.0,
    min_feature_um: float = 300.0,
) -> dict:
    """Return {"bin": bin_um, "paths": [{"c": code, "p": [[x, y], ...]}, ...]} in the xy units (µm)."""
    from skimage.measure import find_contours

    skip_codes = skip_codes or set()
    xy = np.asarray(xy, dtype=np.float64)
    codes = np.asarray(codes).astype(np.int64)
    nn = _median_nn(xy)
    # unlabeled cells (e.g. "NA") are treated as unknown: dropped so neighbours fill their space
    if skip_codes:
        keep = ~np.isin(codes, list(skip_codes))
        if keep.sum() >= min_cells:
            xy, codes = xy[keep], codes[keep]
    b = float(bin_um) if bin_um else max(0.5, 0.5 * nn)
    x0, y0 = xy.min(axis=0)
    x1, y1 = xy.max(axis=0)
    while ((x1 - x0) / b + 3) * ((y1 - y0) / b + 3) > MAX_GRID_CELLS:
        b *= 1.5
    w = int(np.ceil((x1 - x0) / b)) + 3
    h = int(np.ceil((y1 - y0) / b)) + 3
    gx = x0 - b + (np.arange(w) + 0.5) * b
    gy = y0 - b + (np.arange(h) + 0.5) * b
    GX, GY = np.meshgrid(gx, gy)
    tree = cKDTree(xy)
    # fill radius: 2x the median spacing closes gaps inside tissue but keeps real holes/edges as background
    r = max(2.0 * nn, 0.75 * b * np.sqrt(2))
    d, i = tree.query(np.column_stack([GX.ravel(), GY.ravel()]), k=1, distance_upper_bound=r)
    lab = np.full(GX.size, BACKGROUND, dtype=np.int64)
    ok = np.isfinite(d)
    lab[ok] = codes[i[ok]]
    lab = lab.reshape(h, w)

    # majority smoothing over a (smooth_um)^2 window (one-hot sums, argmax); background competes too
    counts = np.bincount(codes, minlength=n_categories)
    cats = [c for c in range(n_categories) if counts[c] >= min_cells and c not in skip_codes]
    smooth = int(max(3, round(smooth_um / b)) | 1)  # odd window size in bins
    if smooth > 1:
        best = np.zeros((h, w), dtype=np.float32)
        best_lab = np.full((h, w), BACKGROUND, dtype=np.int64)
        for c in [BACKGROUND, *cats]:
            s = ndimage.uniform_filter((lab == c).astype(np.float32), size=smooth, mode="constant")
            upd = s > best
            best[upd] = s[upd]
            best_lab[upd] = c
        lab = best_lab

    import warnings

    from skimage.morphology import remove_small_holes, remove_small_objects

    # drop islands/holes smaller than (min_feature_um)^2 so outlines follow regions, not single cells
    min_px = int(max(16, (min_feature_um / b) ** 2))
    paths = []
    tol = 0.35 * b
    for c in cats:
        m = lab == c
        with warnings.catch_warnings():  # skimage 0.26 renamed these parameters; both spellings still work
            warnings.simplefilter("ignore", FutureWarning)
            m = remove_small_objects(m, min_size=min_px)
            m = remove_small_holes(m, area_threshold=min_px)
        mask = np.pad(m.astype(np.float32), 1)
        for cont in find_contours(mask, 0.5):
            if len(cont) < 6:
                continue
            pts = np.column_stack([x0 - b + (cont[:, 1] - 1 + 0.5) * b, y0 - b + (cont[:, 0] - 1 + 0.5) * b])
            pts = _rdp(pts, tol)
            if len(pts) < 4:
                continue
            per = np.hypot(*np.diff(pts, axis=0).T).sum()
            if per < 10 * b:
                continue
            paths.append({"c": int(c), "p": np.round(pts, 1).tolist()})
    return {"bin": round(b, 3), "paths": paths}


def write_outlines(out_dir: Path, field: str, data: dict) -> Path:
    d = Path(out_dir) / "outlines"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{field}.json"
    with open(p, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    return p
