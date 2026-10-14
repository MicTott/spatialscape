# spatialscape (Python)

The command-line tool behind **spatialscape**, a static, reactive browser for spatial transcriptomics and
snRNA-seq. It turns a saved R object (`SpatialExperiment` / `SingleCellExperiment` as `.rds` or `.rda`, parsed in
Python) or AnnData / SpatialData files into viewer bundles (sharded Zarr v3 expression, observation arrays in
microns, OME-Zarr images, domain outlines, cell polygons), and ships the viewer itself so you can open them locally
or publish them as a website.

```bash
pip install spatialscape
spatialscape init analysis/spe_dlpfc.rds --id dlpfc    # writes dlpfc.yaml, a menu of what the data contains
# edit dlpfc.yaml: keep the annotations you want, name them, pick colors and the opening gene
spatialscape build dlpfc.yaml                          # -> bundles/dlpfc; rerun after any edit
spatialscape serve bundles --open                      # viewer + data at http://127.0.0.1:8787/
spatialscape site build bundles -o site                # folder to upload to any static host
```

`sscape` is a short alias for the same command. Documentation: https://mictott.github.io/spatialscape/docs/
Source and issues: https://github.com/MicTott/spatialscape
