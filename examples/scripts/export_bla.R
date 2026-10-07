#!/usr/bin/env Rscript
# Export the BLA cross-species snRNA-seq objects (public per-species SCEs) to h5ad, adding one joint
# donor-corrected UMAP per species: donor-blocked HVGs -> 50 PCs -> Harmony (subject) -> UMAP.
# The objects' own `umap` was computed separately per broad class and overlaid, so it is not used.
suppressPackageStartupMessages({ library(SingleCellExperiment); library(scran); library(scater); library(harmony); library(uwot); library(BiocSingular); library(zellkonverter) })
src <- "/Users/michael.totty/Documents/Web/spatialscape/examples/bla-src"
set.seed(20261007)
keep <- c("Sample", "subject", "species", "subregion", "dv_axis", "sex", "sum", "detected", "subsets_Mito_percent", "broad_celltype", "fine_celltype")
for (sp in c("human", "baboon", "macaque")) {
  sce <- readRDS(file.path(src, sprintf("sce_%s.rds", sp)))
  cat(sprintf("== %s: %d cells x %d genes, %d subjects\n", sp, ncol(sce), nrow(sce), length(unique(sce$subject))))
  dec <- modelGeneVar(sce, block = sce$subject)
  hvg <- getTopHVGs(dec, n = 2000)
  sce <- runPCA(sce, subset_row = hvg, ncomponents = 50, BSPARAM = IrlbaParam())
  hm <- harmony::RunHarmony(reducedDim(sce, "PCA"), meta_data = as.data.frame(colData(sce)), vars_use = "subject", verbose = FALSE)
  um <- uwot::umap(hm, n_neighbors = 30, min_dist = 0.3, metric = "cosine", n_threads = 4)
  cd <- colData(sce)[, intersect(keep, colnames(colData(sce)))]
  for (n in c("Sample", "subject", "species", "subregion", "dv_axis", "sex", "broad_celltype", "fine_celltype")) if (n %in% colnames(cd)) cd[[n]] <- factor(as.character(cd[[n]]))
  o <- SingleCellExperiment(assays = list(X = assay(sce, "logcounts")), colData = cd,
                            rowData = DataFrame(gene_name = rownames(sce), row.names = rownames(sce)))
  reducedDim(o, "X_umap") <- unname(um)
  writeH5AD(o, file.path(src, sprintf("sce_%s.h5ad", sp)), X_name = "X")
  cat(sprintf("   wrote sce_%s.h5ad\n", sp))
  rm(sce, o, hm, um); gc()
}
cat("done\n")
