# Changelog

## 0.2.0 (2026-10-14)

**One yaml per dataset, one command.** `init` reads an R object (`.rds` / `.rda`) or AnnData files and writes a dataset yaml that is a menu of the data; `build` converts R objects once, rebuilds only what changed and applies every edit; `site.yaml` describes the gallery (`site init`, `site build`). Removed `convert`, `plan`, `refresh` and `add-sample`. Per-sample `subset`, fixed grid `columns`, cluster names on embeddings, a shared gene color scale, per-view point sizes, the viewer shipped inside the package (`serve`, `site build`), and the S3 + CloudFront hosting recipe.

## 0.1.0 (2026-10-06)

First public version.

**Viewer.** One-canvas mosaic or strip of all samples with focus and keyboard stepping; gene, annotation, feature-group and two-set blend coloring; legend filtering; independent filter channel (gene, continuous, categorical); hover with all annotations; lasso selection with composition, gene statistics and CSV export; expression-by-annotation dot plot; domain outlines; cell polygons at high zoom; H&E and fluorescence images; platform bar; linked snRNA-seq embedding split view; scale bar; registry gallery with real thumbnails and an optional site bar; full URL state.

**CLI.** `init`, `plan`, `inspect`, `build`, `add-sample`, `refresh`, `outlines`, `thumbnails`, `validate`, `serve`, `synth`. Globs and templates, per-platform defaults, automatic field and image discovery, sharded Zarr v3 uint8 expression, dataset-level vocabularies, OME-Zarr images, outline tracing, polygon packing, thumbnails.

The repository's [CHANGELOG.md](https://github.com/MicTott/spatialscape/blob/main/CHANGELOG.md) is the authoritative list.
