"""Public 10x PBMC multiome (Cell Ranger ARC 2.0.0, "10k PBMCs, granulocytes removed") -> one h5ad for spatialscape.

    python examples/scripts/pbmc_multiome.py <folder with the 10x files> examples/multiome-src/pbmc.h5ad
    python examples/scripts/pbmc_multiome.py genes <folder with the 10x files> examples/multiome-src/genes.bed

Needs scanpy, leidenalg, igraph and scikit-learn (any environment; the spatialscape venv does not carry them).
Inputs: filtered_feature_bc_matrix.h5 (RNA + peaks), atac_peak_annotation.tsv, per_barcode_metrics.csv.

The matrix X stacks four kinds of feature; prefixes split them into tabs through `feature_groups` in the yaml:
  <gene>            log1p CP10k RNA expression
  activity: <gene>  log1p CP10k of ATAC fragments in the gene's promoter peaks and peaks within 2 kb (gene activity)
  score: <type>     marker-set scores (scanpy score_genes): signed, so they exercise the diverging colormap
  peak: chr:s-e     log1p CP10k accessibility of the 20,000 most variable peaks
obs: cell_type (marker-set score per Leiden cluster), leiden, RNA and ATAC QC; obsm: X_umap_rna, X_umap_atac.
"""
from __future__ import annotations

import sys
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import scanpy as sc
import scipy.sparse as sp

MARKERS = {
    "CD4 T": ["IL7R", "CD4", "CCR7", "LTB", "MAL", "TCF7"],
    "CD8 T": ["CD8A", "CD8B", "GZMK", "CCL5", "GZMH"],
    "NK": ["NKG7", "GNLY", "KLRD1", "KLRF1", "PRF1"],
    "B": ["MS4A1", "CD79A", "BANK1", "CD19"],
    "CD14 Mono": ["CD14", "LYZ", "S100A8", "S100A9", "VCAN"],
    "CD16 Mono": ["FCGR3A", "MS4A7", "LST1", "CDKN1C"],
    "DC": ["FCER1A", "CST3", "CLEC10A", "CD1C"],
    "pDC": ["LILRA4", "IRF7", "CLEC4C", "TCF4"],
    "Plasma": ["MZB1", "JCHAIN", "IGHG1", "XBP1"],
    "Platelet": ["PPBP", "PF4", "GP9"],
}
N_PEAKS = 20_000


def log(msg: str) -> None:
    print(msg, flush=True)


def main(data: Path, out: Path) -> None:
    sc.settings.n_jobs = 4
    a = sc.read_10x_h5(data / "filtered_feature_bc_matrix.h5", gex_only=False)
    a.var_names_make_unique()
    rna = a[:, a.var["feature_types"] == "Gene Expression"].copy()
    atac = a[:, a.var["feature_types"] == "Peaks"].copy()
    log(f"read {a.n_obs} cells: {rna.n_vars} genes, {atac.n_vars} peaks")

    # ---- RNA: QC, normalization, clustering, embedding
    rna.var["mt"] = rna.var_names.str.startswith("MT-")
    sc.pp.calculate_qc_metrics(rna, qc_vars=["mt"], inplace=True, percent_top=None)
    sc.pp.filter_cells(rna, min_genes=500)
    rna = rna[rna.obs["pct_counts_mt"] < 20].copy()
    atac = atac[rna.obs_names].copy()
    log(f"after QC: {rna.n_obs} cells")
    rna.layers["counts"] = rna.X.copy()
    sc.pp.normalize_total(rna, target_sum=1e4)
    sc.pp.log1p(rna)
    sc.pp.highly_variable_genes(rna, n_top_genes=2000)
    sc.pp.pca(rna, n_comps=50, mask_var="highly_variable")
    sc.pp.neighbors(rna, n_pcs=30, n_neighbors=15)
    sc.tl.leiden(rna, resolution=1.0, key_added="leiden", flavor="igraph", n_iterations=2, directed=False)
    sc.tl.umap(rna, random_state=0)
    rna.obsm["X_umap_rna"] = rna.obsm["X_umap"].copy()
    for k, genes in MARKERS.items():
        sc.tl.score_genes(rna, [g for g in genes if g in rna.var_names], score_name=f"score: {k}")
    score_cols = [f"score: {k}" for k in MARKERS]
    cluster_means = rna.obs.groupby("leiden", observed=True)[score_cols].mean()
    label = cluster_means.idxmax(axis=1).str.replace("score: ", "", regex=False)
    rna.obs["cell_type"] = rna.obs["leiden"].map(label).astype("category")
    log("cell types: " + ", ".join(f"{k} {v}" for k, v in rna.obs["cell_type"].value_counts().items()))

    # ---- ATAC: TF-IDF + LSI (first component dropped), embedding
    X = atac.X.tocsr().astype(np.float32)
    counts = X.copy()
    X.data[:] = 1
    tf = sp.diags(1.0 / np.maximum(np.asarray(X.sum(axis=1)).ravel(), 1)) @ X
    idf = np.log1p(X.shape[0] / np.maximum(np.asarray(X.sum(axis=0)).ravel(), 1))
    tfidf = (tf @ sp.diags(idf)).tocsr()
    tfidf.data = np.log1p(tfidf.data * 1e4).astype(np.float32)
    from sklearn.decomposition import TruncatedSVD

    lsi = TruncatedSVD(n_components=50, random_state=0).fit_transform(tfidf)[:, 1:]
    lsi /= np.linalg.norm(lsi, axis=1, keepdims=True) + 1e-9
    atac.obsm["X_lsi"] = lsi
    sc.pp.neighbors(atac, use_rep="X_lsi", n_neighbors=20)
    sc.tl.umap(atac, random_state=0)
    rna.obsm["X_umap_atac"] = atac.obsm["X_umap"].copy()
    log("ATAC embedding done")

    # ---- gene activity from the peak annotation: promoter peaks and peaks within 2 kb of the gene
    ann = pd.read_csv(data / "atac_peak_annotation.tsv", sep="\t")
    ann["peak"] = ann["chrom"] + ":" + ann["start"].astype(str) + "-" + ann["end"].astype(str)
    ann = ann.dropna(subset=["gene"])
    sel = ann[(ann["peak_type"] == "promoter") | (ann["distance"].abs() <= 2000)]
    sel = sel[sel["peak"].isin(atac.var_names) & sel["gene"].isin(rna.var_names)].drop_duplicates(["peak", "gene"])
    peak_idx = pd.Index(atac.var_names).get_indexer(sel["peak"])
    gene_cat = pd.Categorical(sel["gene"])
    link = sp.csr_matrix((np.ones(len(sel), dtype=np.float32), (peak_idx, gene_cat.codes)), shape=(atac.n_vars, len(gene_cat.categories)))
    act = ad.AnnData(X=(counts @ link).tocsr(), obs=rna.obs[[]].copy(), var=pd.DataFrame(index=[f"activity: {g}" for g in gene_cat.categories]))
    sc.pp.normalize_total(act, target_sum=1e4)
    sc.pp.log1p(act)
    log(f"gene activity for {act.n_vars} genes from {len(sel)} peak-gene links")

    # ---- the most variable peaks, log-normalized
    mean = np.asarray(tfidf.mean(axis=0)).ravel()
    var = np.asarray(tfidf.power(2).mean(axis=0)).ravel() - mean**2
    top = np.sort(np.argsort(var)[::-1][:N_PEAKS])
    peaks = ad.AnnData(X=counts[:, top].tocsr(), obs=rna.obs[[]].copy(), var=pd.DataFrame(index=[f"peak: {p}" for p in atac.var_names[top]]))
    sc.pp.normalize_total(peaks, target_sum=1e4)
    sc.pp.log1p(peaks)

    # ---- QC from Cell Ranger ARC
    metrics = pd.read_csv(data / "per_barcode_metrics.csv", index_col="barcode").reindex(rna.obs_names)
    obs = pd.DataFrame(index=rna.obs_names)
    obs["cell_type"] = rna.obs["cell_type"].values
    obs["leiden"] = rna.obs["leiden"].astype(str).values
    obs["total_counts"] = rna.obs["total_counts"].values
    obs["n_genes"] = rna.obs["n_genes_by_counts"].values
    obs["pct_mito"] = rna.obs["pct_counts_mt"].values
    if "atac_fragments" in metrics:
        obs["atac_fragments"] = metrics["atac_fragments"].to_numpy(dtype=float)
    if {"atac_TSS_fragments", "atac_fragments"} <= set(metrics.columns):
        obs["tss_fraction"] = (metrics["atac_TSS_fragments"] / metrics["atac_fragments"].clip(lower=1)).to_numpy(dtype=float)
    if {"atac_peak_region_fragments", "atac_fragments"} <= set(metrics.columns):
        obs["frip"] = (metrics["atac_peak_region_fragments"] / metrics["atac_fragments"].clip(lower=1)).to_numpy(dtype=float)

    # ---- one matrix, four kinds of feature
    scores = sp.csr_matrix(rna.obs[score_cols].to_numpy(dtype=np.float32))
    X_all = sp.hstack([rna.X.tocsr().astype(np.float32), act.X, scores, peaks.X]).tocsr()
    var_names = list(rna.var_names) + list(act.var_names) + score_cols + list(peaks.var_names)
    final = ad.AnnData(X=X_all, obs=obs, var=pd.DataFrame(index=var_names))
    final.obsm["X_umap_rna"] = rna.obsm["X_umap_rna"].astype(np.float32)
    final.obsm["X_umap_atac"] = rna.obsm["X_umap_atac"].astype(np.float32)
    out.parent.mkdir(parents=True, exist_ok=True)
    final.write_h5ad(out)
    log(f"wrote {out}: {final.n_obs} cells x {final.n_vars} features ({rna.n_vars} genes, {act.n_vars} activities, {len(score_cols)} scores, {peaks.n_vars} peaks)")


def write_gene_bed(data: Path, out: Path) -> None:
    """Gene spans from the matrix's `interval` column (Cell Ranger ARC), as a BED for the genome panel's gene track."""
    import h5py

    with h5py.File(data / "filtered_feature_bc_matrix.h5") as f:
        feats = f["matrix/features"]
        ft = feats["feature_type"][:].astype(str)
        names = feats["name"][:].astype(str)[ft == "Gene Expression"]
        iv = feats["interval"][:].astype(str)[ft == "Gene Expression"]
    rows = []
    for name, span in zip(names, iv, strict=False):
        if ":" not in span:
            continue
        chrom, rng = span.split(":")
        start, end = rng.split("-")
        rows.append((chrom, int(start), int(end), name))
    rows.sort(key=lambda r: (r[0], r[1]))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as fh:
        fh.writelines(f"{c}\t{s}\t{e}\t{n}\n" for c, s, e, n in rows)
    log(f"wrote {out}: {len(rows)} gene spans")


if __name__ == "__main__":
    if sys.argv[1] == "genes":
        write_gene_bed(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        main(Path(sys.argv[1]), Path(sys.argv[2]))
