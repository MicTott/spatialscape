# Try spatialscape.show() from R: one saveRDS, then the viewer, then the lasso back as colnames.
#
# Until the release that carries show() is on PyPI, point reticulate at a checkout's venv:
#   reticulate::use_python("~/Documents/Web/spatialscape/python/.venv/bin/python", required = TRUE)
# Afterwards:  reticulate::py_require("spatialscape")

library(reticulate)
ss <- import("spatialscape")

spe <- readRDS("~/Documents/R/spatialAmygdala/Vitessce_app/spe_amy_shinyapp.rds")   # or any SPE / SCE you have open
f <- tempfile(fileext = ".rds")
saveRDS(spe, f)                       # show() reads the file; the first call builds it (minutes for a big object), later calls are instant

s <- ss$show(f, open_browser = TRUE)  # in RStudio: rstudioapi::viewer(s$url) shows it in the Viewer pane
cat(s$url, "\n")

readline("Draw a lasso in the viewer, then press Enter here: ")
cells <- unlist(s$selection())        # cell / spot ids inside the lasso
length(cells)
sub <- spe[, colnames(spe) %in% cells]
table(sub$BS_k16_Semisupervised_wAI)  # e.g. the domains the lasso crossed
