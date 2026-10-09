#!/usr/bin/env Rscript
# Export the spatialdACC objects (Visium SPE + snRNA-seq SCE) to spatialscape inputs.
# Visium: one SpaceRanger-like folder per capture area (adata.h5ad + spatial/tissue_hires_image.png +
# spatial/scalefactors_json.json) so `images: auto` and the micron scale need no hand configuration.
suppressPackageStartupMessages({ library(SpatialExperiment); library(SingleCellExperiment); library(zellkonverter); library(png); library(RANN); library(jsonlite) })
script_dir <- dirname(normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1])))
src <- file.path(dirname(script_dir), "dacc-src")  # examples/dacc-src, next to this script's folder
out <- file.path(src, "visium"); dir.create(out, showWarnings = FALSE)

nm <- load(file.path(src, "spe_nnSVG_PRECAST_9_labels.Rdata")); obj <- get(nm[1]); rm(list = nm); spe <- obj; rm(obj)
cat("spe", dim(spe), "\n")
keep_cols <- c("sample_id", "brnum", "slide", "array", "sex", "age", "layer", "nnSVG_PRECAST_captureArea_9", "sum_umi", "sum_gene", "expr_chrM_ratio", "array_row", "array_col")
for (s in unique(spe$sample_id)) {
  d <- file.path(out, s); dir.create(file.path(d, "spatial"), recursive = TRUE, showWarnings = FALSE)
  sub <- spe[, spe$sample_id == s]
  coords <- spatialCoords(sub)
  sce <- SingleCellExperiment(assays = list(X = assay(sub, "logcounts")), colData = colData(sub)[, intersect(keep_cols, colnames(colData(sub)))],
                              rowData = DataFrame(gene_id = rowData(sub)$gene_id, gene_name = rowData(sub)$gene_name, row.names = rownames(sub)))
  sce$precast_cluster <- factor(sce$nnSVG_PRECAST_captureArea_9); sce$nnSVG_PRECAST_captureArea_9 <- NULL
  sce$layer <- factor(sce$layer); sce$brnum <- factor(sce$brnum)
  reducedDim(sce, "spatial") <- unname(as.matrix(coords))
  # images + scale factors (SpaceRanger layout)
  idat <- imgData(sub)
  sf <- list()
  for (img_id in c("hires", "lowres")) {
    row <- idat[idat$sample_id == s & idat$image_id == img_id, ]
    if (nrow(row) == 0) next
    r <- as.matrix(imgRaster(sub, sample_id = s, image_id = img_id))
    rgb <- col2rgb(r)
    a <- array(0, c(nrow(r), ncol(r), 3)); for (k in 1:3) a[, , k] <- matrix(rgb[k, ], nrow(r), ncol(r)) / 255
    writePNG(a, file.path(d, "spatial", sprintf("tissue_%s_image.png", img_id)))
    sf[[sprintf("tissue_%s_scalef", img_id)]] <- row$scaleFactor
  }
  nn <- RANN::nn2(coords, k = 2)$nn.dists[, 2]
  sf$spot_diameter_fullres <- median(nn) * 0.55  # Visium: 100 um centre-to-centre, 55 um spots
  write_json(sf, file.path(d, "spatial", "scalefactors_json.json"), auto_unbox = TRUE, digits = 10)
  writeH5AD(sce, file.path(d, "adata.h5ad"), X_name = "X")
  cat(sprintf("  %s: %d spots, spacing %.1f px, scalef %s\n", s, ncol(sce), median(nn), paste(names(sf), collapse = ",")))
}
rm(spe); gc()

# ---- snRNA-seq
nm <- load(file.path(src, "sce_azimuth_logcounts.Rdata")); obj <- get(nm[1]); rm(list = nm); sce <- obj; rm(obj)
cat("sce", dim(sce), "\n")
keep <- c("Sample", "brain", "round", "sum", "detected", "subsets_Mito_percent", "cellType_azimuth")
o <- SingleCellExperiment(assays = list(X = assay(sce, "logcounts")), colData = colData(sce)[, keep],
                          rowData = DataFrame(gene_id = rowData(sce)$gene_id, gene_name = rowData(sce)$gene_name, row.names = rownames(sce)))
for (n in c("Sample", "brain", "cellType_azimuth")) o[[n]] <- factor(o[[n]])
reducedDim(o, "X_umap") <- unname(reducedDim(sce, "UMAP-HARMONY"))
writeH5AD(o, file.path(src, "sce_dacc_azimuth.h5ad"), X_name = "X")
cat("done\n")
