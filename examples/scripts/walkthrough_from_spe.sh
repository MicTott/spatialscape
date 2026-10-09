#!/usr/bin/env bash
# From the original Visium SpatialExperiment to a local site. Run from ~/Documents/R/spatialAmygdala.
set -e

python3 -m venv .venv-spatialscape && source .venv-spatialscape/bin/activate
pip install /Users/michael.totty/Documents/Web/spatialscape/python/dist/spatialscape-0.1.1.dev1-py3-none-any.whl
spatialscape --version

spatialscape inspect Vitessce_app/spe_amy_shinyapp.rds

spatialscape convert Vitessce_app/spe_amy_shinyapp.rds -o spatialscape/data/visium --assay logcounts --cols BS_k16_Semisupervised_wAI,sum_umi,sum_gene,expr_chrM_ratio

spatialscape init "spatialscape/data/visium/*/adata.h5ad" --platform visium --id amygdala_visium --name "Human amygdala Visium" -o spatialscape/dataset.yaml
spatialscape plan spatialscape/dataset.yaml

spatialscape build spatialscape/dataset.yaml -o spatialscape/bundles/amygdala_visium

spatialscape site build spatialscape/bundles -o spatialscape/site --title "Human amygdala"

spatialscape serve spatialscape/bundles --open
