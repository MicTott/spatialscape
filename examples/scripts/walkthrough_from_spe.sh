#!/usr/bin/env bash
# From the original Visium SpatialExperiment to a local site. Run from ~/Documents/R/spatialAmygdala.
set -e

python3 -m venv .venv-spatialscape && source .venv-spatialscape/bin/activate
pip install /Users/michael.totty/Documents/Web/spatialscape/python
spatialscape --version

mkdir -p spatialscape && cd spatialscape

spatialscape init ../Vitessce_app/spe_amy_shinyapp.rds --id amygdala_visium --name "Human amygdala Visium"
# edit amygdala_visium.yaml: keep the annotations you want, name them, pick colors and the opening gene

spatialscape build amygdala_visium.yaml --dry-run
spatialscape build amygdala_visium.yaml

spatialscape site init amygdala_visium.yaml --title "Human amygdala"
spatialscape site build site.yaml

spatialscape serve site --open
