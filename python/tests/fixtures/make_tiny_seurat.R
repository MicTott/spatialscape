# Writes tiny_seurat.rds: a Seurat v5 object with a split-layer RNA Assay5 (two runs, colliding barcodes), a v3-style
# "ATAC" Assay whose features are peak coordinates, meta.data columns of several types, an ident, and two reductions.
suppressPackageStartupMessages(library(Seurat))
set.seed(1)
n_per <- 12
cells <- c(paste0("run1#", sprintf("BC%02d-1", 1:n_per)), paste0("run2#", sprintf("BC%02d-1", 1:n_per)))
genes <- paste0("G", 1:8)
counts <- matrix(rpois(length(genes) * length(cells), 2), nrow = length(genes), dimnames = list(genes, cells))
counts[1, 1:n_per] <- counts[1, 1:n_per] + 20  # G1 marks run1
meta <- data.frame(
  row.names = cells,
  sample = rep(c("run1", "run2"), each = n_per),
  cell_type = factor(rep(c("Astro", "Micro", "Oligo"), length.out = length(cells))),
  score = round(runif(length(cells)), 3),
  flag = rep(c(TRUE, FALSE), length.out = length(cells)),
  stringsAsFactors = FALSE
)
options(Seurat.object.assay.version = "v5")
obj <- CreateSeuratObject(counts = counts, meta.data = meta, project = "tiny")
obj <- NormalizeData(obj, verbose = FALSE)
obj[["RNA"]] <- split(obj[["RNA"]], f = obj$sample)  # counts.run1 / counts.run2 / data.run1 / data.run2
peaks <- c("chr1-100-200", "chr1-500-650", "chr2-10-90")
pk <- matrix(rpois(length(peaks) * length(cells), 1), nrow = length(peaks), dimnames = list(peaks, cells))
options(Seurat.object.assay.version = "v3")
obj[["ATAC"]] <- CreateAssayObject(counts = pk)
obj[["ATAC"]]@data <- as(log1p(pk), "dgCMatrix")
Idents(obj) <- "cell_type"
umap <- matrix(rnorm(length(cells) * 2), ncol = 2, dimnames = list(cells, c("umap_1", "umap_2")))
obj[["umap"]] <- CreateDimReducObject(embeddings = umap, key = "UMAP_", assay = "RNA")
pca <- matrix(rnorm(length(cells) * 3), ncol = 3, dimnames = list(cells, paste0("PC_", 1:3)))
obj[["pca"]] <- CreateDimReducObject(embeddings = pca, key = "PC_", assay = "RNA")
# what real objects carry that a plain S4 walker trips over: a function among the recorded command parameters
# (a closure with its environment and bytecode) and a compact integer sequence (ALTREP) in meta.data
obj@commands[["Fake.RNA"]] <- new("SeuratCommand", name = "Fake", time.stamp = Sys.time(), assay.used = "RNA",
                                  call.string = "Fake(obj)", params = list(fn = function(x) x + 1, k = 2L))
obj$idx <- seq_len(ncol(obj))
out <- file.path(dirname(sub("--file=", "", grep("--file=", commandArgs(), value = TRUE))), "tiny_seurat.rds")
saveRDS(obj, out)
cat("wrote", out, "\n")
