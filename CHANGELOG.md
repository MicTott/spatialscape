# Changelog

## Unreleased

- **The viewer ships in the Python package.** `spatialscape serve` serves the viewer, a gallery generated from every bundle in the folder, and the data from one local address; `--open` launches the browser. New `spatialscape site build` writes a deployable folder (viewer + `datasets.json` + bundles, or `--data-url` for bundles on object storage) and preserves hand edits to the registry.
- `spatialscape convert` reads SpatialExperiment / SingleCellExperiment objects straight from `.rds` / `.rda` (parsed in Python with rds2py, no R needed) and writes build inputs: one SpaceRanger-like folder per sample with the H&E and scale factors, or one h5ad with the UMAP for snRNA-seq references. `inspect` reads R objects too.
- CLI: readable one-line errors (traceback behind `SPATIALSCAPE_DEBUG=1`), `--version`, `init` picks the right template for file-per-sample and folder-per-sample layouts, `inspect` no longer crashes on files without layers, `validate <url>` sends an `Origin` header and requires Range support only for sharded bundles. Config paths expand `${ENV_VAR}`.
- Build: polygons from `obsm` arrays (auto-detected) or long-format parquet with an `affine` frame mapping and a centroid sanity check; long-form field maps `{column, scale}`; `refresh` re-applies palette colors; per-crop micron scales for Visium HD.
- Viewer: shared gene color scale across samples (per-sample as an option), blend = mean log-normalized expression, per-view point size, PNG export with legend and scale bar, copy-link button, recent genes, `?` shortcut overlay, legends sorted by count with a "not measured" note, label de-collision, grid cells that include image frames, collapsed sample list, telemetry behind `?debug=1`.
- Docs: VitePress site with a generated per-command CLI reference; "Publish your own site" guide.
- Registry: public `datasets.json` plus a gitignored `datasets.local.json` overlay for development.


## 0.1.0 (2026-10-06)

First public version.

- Viewer: one-canvas mosaic/strip of all samples with focus and keyboard stepping; gene, annotation and feature-group coloring; legend filtering; independent filter channel (gene, continuous, categorical); hover with all annotations; lasso selection with composition, gene statistics and CSV export; expression-by-annotation dot plot; domain outlines; cell polygons at high zoom; H&E / fluorescence images via Viv; platform bar; linked snRNA-seq embedding split view; full URL state.
- CLI (`spatialscape`, alias `sscape`): `inspect`, `build`, `add-sample`, `refresh`, `outlines`, `validate`, `serve`, `synth`. Sharded Zarr v3 uint8 expression, dataset-level vocabularies, OME-Zarr images, outline tracing, polygon packing.
