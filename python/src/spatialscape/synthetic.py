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


def make_sample(path: Path, n: int, n_genes: int, seed: int, w: int = 512, h: int = 384, counts: bool = False, extra_obs: dict[str, str] | None = None):
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
    if (extra_obs or {}).get("condition") == "stress":
        X[:, :3] *= 3.0  # planted effect: the first three genes are higher in the stress group
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
    for k, v in (extra_obs or {}).items():
        obs[k] = pd.Categorical([v] * n)  # a sample-level property stored per cell, the way most objects carry condition or sex
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
    # fake molecules, 10x transcripts.parquet style: a few per cell per expressed gene, scattered around the cell
    # (pixel units, the coordinate frame), 40% not assigned to a cell, some below Q20 and a few control probes
    per = np.rint(np.minimum(X, 6)).astype(int)  # molecules of each gene in each cell
    cell_i = np.repeat(np.arange(n), per.sum(1))
    gene_i = np.concatenate([np.repeat(np.arange(n_genes), per[i]) for i in range(n)]) if per.sum() else np.zeros(0, dtype=int)
    m = len(cell_i)
    mxy = xy[cell_i] + rng.normal(0, 2.0, size=(m, 2))
    assigned = rng.random(m) < 0.6
    rows = {
        "transcript_id": np.arange(m, dtype=np.uint64),
        "cell_id": np.where(assigned, np.asarray(obs.index)[cell_i], "UNASSIGNED"),
        "overlaps_nucleus": (assigned & (rng.random(m) < 0.5)).astype(np.uint8),
        "feature_name": np.asarray(genes)[gene_i],
        "x_location": mxy[:, 0].astype(np.float32),
        "y_location": mxy[:, 1].astype(np.float32),
        "qv": np.where(rng.random(m) < 0.15, 12.0, 32.5).astype(np.float32),
    }
    ctrl = 40
    for k, v in rows.items():
        extra = {"feature_name": np.array([f"NegControlProbe_{i % 4:05d}" for i in range(ctrl)]), "cell_id": np.array(["UNASSIGNED"] * ctrl), "qv": np.full(ctrl, 32.5, np.float32)}
        rows[k] = np.concatenate([v, extra.get(k, np.resize(v[:1], ctrl) if len(v) else np.zeros(ctrl, v.dtype))])
    order = rng.permutation(len(rows["qv"]))  # like 10x, not sorted by gene
    pq.write_table(pa.table({k: v[order] for k, v in rows.items()}), path.with_suffix(".transcripts.parquet"), row_group_size=5000)


def _write_de_tables(out: Path, groups: dict[str, tuple[str, str]], n_genes: int) -> None:
    """A results table, the per-mouse pseudobulk and a replicate sheet, computed from the sections just written
    (a t-test on two vs two: an example of the file shapes, not of statistics)."""
    from scipy import stats

    genes = [f"G{i:03d}" for i in range(n_genes)]
    pb: dict[str, np.ndarray] = {}
    cond: dict[str, str] = {}
    for sid, (condition, mouse) in groups.items():
        a = ad.read_h5ad(out / f"{sid}.h5ad")
        X = a.X.toarray() if sp.issparse(a.X) else np.asarray(a.X)
        if X.max() > 30 or np.all(np.rint(X) == X):  # a counts section: bring it onto the log scale the others use
            X = np.log1p(X / np.maximum(X.sum(1, keepdims=True), 1) * 1e4)
        pb[mouse] = np.log2(np.expm1(X).mean(0) + 1)  # mean expression per gene, as log2(mean + 1)
        cond[mouse] = condition
    mice = list(pb)
    mat = np.stack([pb[m] for m in mice], 1)
    ctl = mat[:, [i for i, m in enumerate(mice) if cond[m] == "control"]]
    strs = mat[:, [i for i, m in enumerate(mice) if cond[m] == "stress"]]
    effect = strs.mean(1) - ctl.mean(1)
    p = stats.ttest_ind(strs, ctl, axis=1, equal_var=False).pvalue
    p = np.where(np.isfinite(p), p, 1.0)
    order = np.argsort(p)
    ranked = p[order] * len(p) / (np.arange(len(p)) + 1)
    padj = np.empty_like(p)
    padj[order] = np.minimum.accumulate(ranked[::-1])[::-1].clip(max=1.0)  # Benjamini-Hochberg
    de = out / "de"
    de.mkdir(exist_ok=True)
    pd.DataFrame({"gene": genes, "baseMean": mat.mean(1), "log2FoldChange": effect, "pvalue": p, "padj": padj}).to_csv(de / "stress_vs_control.csv", index=False)
    pd.DataFrame(mat, index=pd.Index(genes, name="gene"), columns=mice).to_csv(de / "pseudobulk.csv")
    pd.DataFrame({"mouse": mice, "condition": [cond[m] for m in mice]}).to_csv(de / "mice.csv", index=False)


def make_synthetic(out: Path, n_cells: int = 2000, n_genes: int = 50, comparisons: bool = False) -> Path:
    """Two fake sections and an embedding. With `comparisons`, two more sections and sample metadata: a control
    and a stress group of two mice each, the condition stored per cell (as objects usually carry it) and the
    mouse given in the yaml, so both ways of declaring `meta` are exercised."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    groups = {"sampleA": ("control", "m1"), "sampleB": ("control", "m2"), "sampleC": ("stress", "m3"), "sampleD": ("stress", "m4")} if comparisons else {}
    extra = lambda sid: ({"condition": groups[sid][0]} if sid in groups else None)  # noqa: E731
    make_sample(out / "sampleA.h5ad", n_cells, n_genes, seed=1, extra_obs=extra("sampleA"))
    make_sample(out / "sampleB.h5ad", int(n_cells * 1.4), n_genes, seed=2, counts=True, extra_obs=extra("sampleB"))
    if comparisons:
        make_sample(out / "sampleC.h5ad", int(n_cells * 1.1), n_genes, seed=3, extra_obs=extra("sampleC"))
        make_sample(out / "sampleD.h5ad", int(n_cells * 0.9), n_genes, seed=4, counts=True, extra_obs=extra("sampleD"))
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
                "molecules": {"path": "sampleA.transcripts.parquet"},
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
                "molecules": {"path": "sampleB.transcripts.parquet"},
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
    if comparisons:
        _write_de_tables(out, groups, n_genes)
        cfg["comparisons"] = [
            {
                "id": "stress_vs_control",
                "name": "Stress vs control",
                "description": "Welch t-test on per-mouse pseudobulk (log2 of the mean expression + 1), two mice per group; G000-G002 are planted higher in stress. Positive effect = higher in stress.",
                "results": "de/stress_vs_control.csv",
                "pseudobulk": "de/pseudobulk.csv",
                "replicates": "de/mice.csv",
                "groups": ["control", "stress"],
                "units": "log2 mean+1",
                "split": "condition",
                "link": "mouse",
            }
        ]
        cfg["description"] = "Four fake tissue sections in two experimental groups (control, stress), two mice each, plus an embedding and a differential expression result."
        cfg["meta"] = [{"id": "condition", "name": "Condition", "levels": ["control", "stress"]}, {"id": "mouse", "name": "Mouse"}]
        for s in cfg["samples"]:
            if s["id"] in groups:
                s["meta"] = {"condition": {"column": "condition"}, "mouse": groups[s["id"]][1]}
        cfg["samples"][2:2] = [
            {
                "id": "sampleC",
                "name": "Sample C (stress)",
                "platform": "visium",
                "group": "donor3",
                "path": "sampleC.h5ad",
                "fields": {"cluster": "cluster", "total_counts": "total_counts"},
                "images": [{"id": "he", "name": "H&E", "path": "sampleC.png"}],
                "polygons": {"path": "sampleC.polygons.parquet"},
                "meta": {"condition": {"column": "condition"}, "mouse": "m3"},
            },
            {
                "id": "sampleD",
                "name": "Sample D (stress, counts)",
                "platform": "visium",
                "group": "donor4",
                "path": "sampleD.h5ad",
                "fields": {"cluster": "cluster", "total_counts": "total_counts"},
                "images": [{"id": "he", "name": "H&E", "path": "sampleD.png"}],
                "polygons": {"path": "sampleD.polygons.parquet"},
                "meta": {"condition": {"column": "condition"}, "mouse": "m4"},
            },
        ]
    with open(out / "dataset.yaml", "w") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)
    return out / "dataset.yaml"
