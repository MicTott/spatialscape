# spatialscape (Python)

Command-line tool that converts AnnData (h5ad / zarr) or SpatialData into static **spatialscape** viewer bundles:
sharded Zarr v3 expression, per-sample observation arrays, OME-Zarr images, domain outlines and cell polygons.

```bash
pip install spatialscape
spatialscape inspect sample.h5ad
spatialscape build dataset.yaml -o bundle
spatialscape serve bundle --port 8787
```

`sscape` is a short alias for the same command. Full documentation and the web viewer live at
https://github.com/mictott/spatialscape.
