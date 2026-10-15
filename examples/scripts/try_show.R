# Try spatialscape.show() from R: the viewer on an object, then the lasso back as colnames.
#
# Run this in a fresh R session: reticulate binds one Python per session, and it must be told which one BEFORE
# it initialises. Until the release that carries show() is on PyPI, that is a checkout's venv:
Sys.setenv(RETICULATE_PYTHON = path.expand("~/Documents/Web/spatialscape/python/.venv/bin/python"))
# (after the PyPI release: drop the line above and use reticulate::py_require("spatialscape") instead)

library(reticulate)
ss <- import("spatialscape")

# An object that already lives in a file: pass the path (no re-saving). The first call reads and builds it
# (about two minutes for this 2 GB SpatialExperiment); every later call on the same file is instant.
f <- "~/Documents/R/spatialAmygdala/Vitessce_app/spe_amy_shinyapp.rds"
# An object you only have in memory: saveRDS(obj, f <- tempfile(fileext = ".rds")) and pass that.

s <- ss$show(f, open_browser = TRUE)  # in RStudio: rstudioapi::viewer(s$url) shows it in the Viewer pane
cat(s$url, "\n")

readline("Draw a lasso in the viewer (the lasso tool top left, or press l), then press Enter here: ")
cells <- unlist(s$selection())        # spot ids inside the lasso

spe <- readRDS(f)
sub <- spe[, colnames(spe) %in% cells]
dim(sub)
table(sub$BS_k16_Semisupervised_wAI)  # the domains the lasso crossed
