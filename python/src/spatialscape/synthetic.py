"""Generate a tiny synthetic dataset (AnnData + PNG image + dataset.yaml) for tests and demos."""

from __future__ import annotations

from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sp
import yaml

CLUSTERS = ["Astro", "Excit_L2", "Excit_L5", "Inhib_PV", "Oligo", "Micro"]


def _tissue(n: int, rng: np.random.Generator, w: float, h: float) -> np.ndarray:
    # points inside an ellipse with a notch, in pixel units of a (h, w) image
    pts = []
    while len(pts) < n:
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        nx, ny = (x - w / 2) / (w / 2), (y - h / 2) / (h / 2)
        inside = nx * nx + ny * ny < 0.85 and not (nx > 0.3 and abs(ny) < 0.15)
        if inside:
            pts.append((x, y))
    return np.array(pts)


def make_sample(path: Path, n: int, n_genes: int, seed: int, w: int = 512, h: int = 384, counts: bool = False):
    rng = np.random.default_rng(seed)
    xy = _tissue(n, rng, w, h)
    ang = np.arctan2(xy[:, 1] - h / 2, xy[:, 0] - w / 2)
    cl = ((ang + np.pi) / (2 * np.pi) * len(CLUSTERS)).astype(int) % len(CLUSTERS)
    genes = [f"G{i:03d}" for i in range(n_genes)]
    centers = rng.uniform([0, 0], [w, h], size=(n_genes, 2))
    X = np.zeros((n, n_genes), dtype=np.float32)
    for g in range(n_genes):
        d2 = ((xy - centers[g]) ** 2).sum(1)
        X[:, g] = np.exp(-d2 / (2 * (0.2 * w) ** 2)) * rng.uniform(1, 4)
    X += (cl[:, None] == (np.arange(n_genes)[None, :] % len(CLUSTERS))) * 1.5
    X *= rng.random(X.shape) > 0.35  # sparsity
    if counts:
        X = rng.poisson(X * 3).astype(np.float32)
    obs = pd.DataFrame(
        {
            "cluster": pd.Categorical([CLUSTERS[i] for i in cl]),
            "total_counts": X.sum(1) * 100 + rng.normal(0, 5, n),
            "sample_id": path.stem,
        },
        index=[f"cell_{i}" for i in range(n)],
    )
    obs.loc[obs.index[:7], "cluster"] = np.nan  # a few missing labels
    a = ad.AnnData(X=sp.csr_matrix(X), obs=obs, var=pd.DataFrame(index=genes))
    a.obsm["spatial"] = xy
    a.obsm["X_umap"] = np.stack([np.cos(ang) * 3 + rng.normal(0, 0.3, n), np.sin(ang) * 3 + rng.normal(0, 0.3, n)], 1)
    a.uns["spot_nn_spacing_level0_px"] = 10.0  # => 10 um per px
    # fake cell polygons: wobbly hexagons around each point (pixel units, same frame as coords),
    # stored both as obsm/segmentations (n, 6, 2) and as a long-format parquet file
    ang_v = np.linspace(0, 2 * np.pi, 7)[:-1]
    r = rng.uniform(2.5, 4.0, size=(n, 1)) * (1 + 0.15 * rng.standard_normal((n, 6)))
    vx = xy[:, 0:1] + r * np.cos(ang_v)
    vy = xy[:, 1:2] + r * np.sin(ang_v)
    a.obsm["segmentations"] = np.stack([vx, vy], -1)
    a.write_h5ad(path)
    # image: gradient background + darker tissue ellipse, (h, w, 3) uint8
    yy, xx = np.mgrid[0:h, 0:w]
    nx, ny = (xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)
    tissue = (nx * nx + ny * ny < 0.85).astype(np.float32)
    img = np.stack(
        [
            235 - 90 * tissue + 10 * nx,
            225 - 120 * tissue,
            230 - 80 * tissue + 10 * ny,
        ],
        -1,
    )
    img = np.clip(img + rng.normal(0, 4, img.shape), 0, 255).astype(np.uint8)
    import imageio.v3 as iio

    iio.imwrite(path.with_suffix(".png"), img)
    import pyarrow as pa
    import pyarrow.parquet as pq

    cid = np.repeat(np.asarray(obs.index), 6)
    pq.write_table(
        pa.table({"cell_id": cid, "vertex_x": vx.ravel(), "vertex_y": vy.ravel()}),
        path.with_suffix(".polygons.parquet"),
    )


def make_synthetic(out: Path, n_cells: int = 2000, n_genes: int = 50) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    make_sample(out / "sampleA.h5ad", n_cells, n_genes, seed=1)
    make_sample(out / "sampleB.h5ad", int(n_cells * 1.4), n_genes, seed=2, counts=True)
    cfg = {
        "id": "synthetic",
        "name": "Synthetic demo",
        "description": "Two fake tissue sections plus an embedding, for tests and the hosted demo.",
        "default_gene": "G001",
        "default_color": {"field": "cluster"},
        "layout": {"mode": "grid"},
        "fields": [
            {"id": "cluster", "name": "Cluster", "type": "categorical", "categories": CLUSTERS},
            {"id": "total_counts", "name": "Total counts", "type": "continuous"},
        ],
        "samples": [
            {
                "id": "sampleA",
                "name": "Sample A (lognorm)",
                "platform": "visium",
                "group": "donor1",
                "path": "sampleA.h5ad",
                "fields": {"cluster": "cluster", "total_counts": "total_counts"},
                "images": [{"id": "he", "name": "H&E", "path": "sampleA.png"}],
                "polygons": {"path": "sampleA.polygons.parquet"},
            },
            {
                "id": "sampleB",
                "name": "Sample B (counts, flipped)",
                "platform": "visium",
                "group": "donor2",
                "path": "sampleB.h5ad",
                "transform": {"flip": "x", "rotate": 90},
                "fields": {"cluster": "cluster", "total_counts": "total_counts"},
                "images": [{"id": "he", "name": "H&E", "path": "sampleB.png"}],
                "polygons": {"path": "sampleB.polygons.parquet"},
            },
            {
                "id": "umapA",
                "name": "Sample A UMAP",
                "platform": "snrnaseq",
                "kind": "embedding",
                "group": "donor1",
                "path": "sampleA.h5ad",
                "coords": "obsm/X_umap",
                "fields": {"cluster": "cluster", "total_counts": "total_counts"},
            },
        ],
    }
    with open(out / "dataset.yaml", "w") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)
    return out / "dataset.yaml"
