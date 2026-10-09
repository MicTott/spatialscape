#!/usr/bin/env Rscript
# Export a SpatialExperiment (Visium / Visium HD) to spatialscape inputs, one folder per sample:
#
#   <out>/<sample>/adata.h5ad                     X = chosen assay, obs = chosen colData, obsm/spatial = spatialCoords
#   <out>/<sample>/spatial/tissue_hires_image.png  (and lowres if present)
#   <out>/<sample>/spatial/scalefactors_json.json  tissue_*_scalef from imgData + spot_diameter_fullres
#
# which is the SpaceRanger layout, so `spatialscape init "<out>/*/adata.h5ad" --platform visium` needs no
# hand-written image or scale settings. Use from R:
#
#   source("spe_to_spatialscape.R")
#   spe_to_spatialscape(spe, "exports/visium", assay = "logcounts", cols = c("BS_k16_Semisupervised_wAI", "group", "sum_umi"))
#
# or from the shell:
#
#   Rscript spe_to_spatialscape.R spe.rds exports/visium logcounts BS_k16_Semisupervised_wAI,group,sum_umi
#
# Requires: SpatialExperiment, zellkonverter, png, RANN, jsonlite.
suppressPackageStartupMessages({
  library(SpatialExperiment); library(SingleCellExperiment); library(zellkonverter); library(png); library(RANN); library(jsonlite)
})

spe_to_spatialscape <- function(spe, out, assay = "logcounts", cols = NULL, sample_col = "sample_id",
                                image_ids = c("hires", "lowres"), spot_um = 55, spacing_um = 100, gene_name_col = NULL) {
  stopifnot(is(spe, "SpatialExperiment"), assay %in% assayNames(spe))
  dir.create(out, recursive = TRUE, showWarnings = FALSE)
  if (is.null(cols)) cols <- colnames(colData(spe))
  cols <- intersect(cols, colnames(colData(spe)))
  if (is.null(gene_name_col)) gene_name_col <- intersect(c("gene_name", "symbol", "Symbol", "gene_symbol"), colnames(rowData(spe)))[1]
  rd <- DataFrame(row.names = rownames(spe))
  if (!is.na(gene_name_col)) rd$gene_name <- as.character(rowData(spe)[[gene_name_col]])
  for (s in unique(spe[[sample_col]])) {
    sub <- spe[, spe[[sample_col]] == s]
    d <- file.path(out, s); dir.create(file.path(d, "spatial"), recursive = TRUE, showWarnings = FALSE)
    coords <- as.matrix(spatialCoords(sub))
    cd <- colData(sub)[, cols, drop = FALSE]
    for (n in colnames(cd)) if (is.character(cd[[n]]) || is.logical(cd[[n]])) cd[[n]] <- factor(cd[[n]])
    sce <- SingleCellExperiment(assays = list(X = assay(sub, assay)), colData = cd, rowData = rd)
    reducedDim(sce, "spatial") <- unname(coords)
    sf <- list()
    idat <- imgData(sub)
    for (img_id in image_ids) {
      row <- idat[idat$sample_id == s & idat$image_id == img_id, ]
      if (nrow(row) == 0) next
      r <- as.matrix(imgRaster(sub, sample_id = s, image_id = img_id))
      rgb <- col2rgb(r)
      a <- array(0, c(nrow(r), ncol(r), 3)); for (k in 1:3) a[, , k] <- matrix(rgb[k, ], nrow(r), ncol(r)) / 255
      writePNG(a, file.path(d, "spatial", sprintf("tissue_%s_image.png", img_id)))
      sf[[sprintf("tissue_%s_scalef", img_id)]] <- row$scaleFactor
    }
    nn <- RANN::nn2(coords, k = 2)$nn.dists[, 2]
    sf$spot_diameter_fullres <- median(nn) * spot_um / spacing_um  # Visium: 100 um centre-to-centre, 55 um spots
    write_json(sf, file.path(d, "spatial", "scalefactors_json.json"), auto_unbox = TRUE, digits = 10)
    writeH5AD(sce, file.path(d, "adata.h5ad"), X_name = "X")
    message(sprintf("  %s: %d spots, %d genes, images: %s", s, ncol(sce), nrow(sce), paste(setdiff(names(sf), "spot_diameter_fullres"), collapse = ",")))
  }
  invisible(out)
}

if (sys.nframe() == 0) {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) < 2) stop("usage: Rscript spe_to_spatialscape.R <spe.rds> <out_dir> [assay] [col1,col2,...]")
  spe <- readRDS(args[1])
  cols <- if (length(args) >= 4) strsplit(args[4], ",")[[1]] else NULL
  spe_to_spatialscape(spe, args[2], assay = if (length(args) >= 3) args[3] else "logcounts", cols = cols)
}
