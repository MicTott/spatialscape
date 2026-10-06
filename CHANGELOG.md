# Changelog

## 0.1.0 (2026-10-06)

First public version.

- Viewer: one-canvas mosaic/strip of all samples with focus and keyboard stepping; gene, annotation and feature-group coloring; legend filtering; independent filter channel (gene, continuous, categorical); hover with all annotations; lasso selection with composition, gene statistics and CSV export; expression-by-annotation dot plot; domain outlines; cell polygons at high zoom; H&E / fluorescence images via Viv; platform bar; linked snRNA-seq embedding split view; full URL state.
- CLI (`spatialscape`, alias `sscape`): `inspect`, `build`, `add-sample`, `refresh`, `outlines`, `validate`, `serve`, `synth`. Sharded Zarr v3 uint8 expression, dataset-level vocabularies, OME-Zarr images, outline tracing, polygon packing.
