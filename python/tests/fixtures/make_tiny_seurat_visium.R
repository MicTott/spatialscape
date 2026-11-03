# Writes tiny_seurat_visium.rds: a Seurat v5 object with two Visium slices, one a VisiumV1 image (Seurat 4 style:
# coordinates data.frame in full-resolution pixels, a low-resolution H&E array, scale factors) and one a VisiumV2
# image (Seurat 5 style: a Centroids boundary with a spot radius, the same array and scale factors).
suppressPackageStartupMessages(library(Seurat))
set.seed(2)
n_per <- 12
cells <- c(paste0("A_", sprintf("BC%02d-1", 1:n_per)), paste0("B_", sprintf("BC%02d-1", 1:n_per)))
genes <- paste0("G", 1:8)
counts <- matrix(rpois(length(genes) * length(cells), 2), nrow = length(genes), dimnames = list(genes, cells))
meta <- data.frame(row.names = cells, slice = rep(c("A", "B"), each = n_per), domain = factor(rep(c("L1", "L2", "WM"), length.out = length(cells))))
options(Seurat.object.assay.version = "v5")
obj <- CreateSeuratObject(counts = counts, meta.data = meta, assay = "Spatial", project = "tinyvis")
obj <- NormalizeData(obj, verbose = FALSE)
# a 3 x 4 grid of spots, 100 um apart, in full-resolution pixels at 0.5 um/px (spot diameter 55 um = 110 px)
grid <- expand.grid(col = 0:3, row = 0:2)
px <- data.frame(imagecol = 400 + grid$col * 200, imagerow = 300 + grid$row * 200, row = grid$row, col = grid$col, tissue = 1L)
sf <- scalefactors(spot = 110, fiducial = 160, hires = 0.1, lowres = 0.05)
img <- array(runif(30 * 40 * 3), dim = c(30, 40, 3))   # a 40 x 30 px lowres image (rows = y)
# slice A: VisiumV1
coordsA <- px[, c("tissue", "row", "col", "imagerow", "imagecol")]
rownames(coordsA) <- cells[1:n_per]
sliceA <- new("VisiumV1", image = img, scale.factors = sf, coordinates = coordsA, spot.radius = 0.02, assay = "Spatial", key = "a_")
obj[["A"]] <- sliceA
# slice B: VisiumV2 with a Centroids boundary (x = imagecol, y = imagerow)
cent <- CreateCentroids(data.frame(x = px$imagecol + 3000, y = px$imagerow, cell = cells[(n_per + 1):(2 * n_per)]), nsides = Inf, radius = 55)
sliceB <- new("VisiumV2", image = img, scale.factors = sf, boundaries = list(centroids = cent), molecules = list(), assay = "Spatial", key = "b_")
obj[["B"]] <- sliceB
out <- file.path(dirname(sub("--file=", "", grep("--file=", commandArgs(), value = TRUE))), "tiny_seurat_visium.rds")
saveRDS(obj, out)
cat("wrote", out, "\n")
print(obj)
print(class(obj[["A"]])); print(class(obj[["B"]]))
print(head(GetTissueCoordinates(obj, image = "B"), 2))
