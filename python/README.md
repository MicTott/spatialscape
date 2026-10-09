# spatialscape (Python)

Command-line tool that converts AnnData (h5ad / zarr) or SpatialData into static **spatialscape** viewer bundles
(sharded Zarr v3 expression, per-sample observation arrays, OME-Zarr images, domain outlines, cell polygons),
and ships the viewer itself so you can open them locally or assemble a site to upload.

```bash
pip install spatialscape
spatialscape inspect sample.h5ad                 # what the file contains
spatialscape build dataset.yaml -o bundles/my_atlas
spatialscape serve bundles --open                # viewer + data at http://127.0.0.1:8787/
spatialscape site build bundles -o site          # folder to upload to any static host
```

`sscape` is a short alias for the same command. Documentation: https://mictott.github.io/spatialscape/docs/
