# Changelog

## 0.5.0 (2026-10-29)

**Compare, by matrix.** Differential expression tables of every common shape go in as they are: marker tables (Seurat `FindAllMarkers`, scanpy `rank_genes_groups`, presto, scran, or a bare cluster-and-gene list from a paper) become one level per cluster against the rest, and a case/control result fit per cell type is one comparison with a facet; levels link to an annotation's categories, aliases included. The Compare panel is a genes-by-levels matrix with the effect in tinted chips and the level's legend colour in its column head, beside violins of the gene per category (from the per-cell values the maps draw) or the per-replicate dots. A Comparisons group in the side panel, a *markers* button on every legend row, `show().add_markers(adata)`. **Docs by platform family** (sequencing-based, imaging-based, single-cell), boundary and molecule tables from CSV as well as Parquet with NanoString and Vizgen conventions recognised, `init` proposing a Xenium folder's boundaries and transcripts, a segmentation overlay for comparing boundary sets, plainer names in the panel.

## 0.4.0 (2026-10-23)

**Xenium at every scale.** Cell boundaries are cut into spatial tiles, coloured like the cells (gene, annotation, blend, filter) and drawn filled or as edges once zoomed in, at about 1 ms per frame where whole-section outlines took 30. Transcripts (`molecules:` from `transcripts.parquet`) are tiled at 3.5 bytes each and drawn once a view holds about one per screen pixel, following the gene on screen, with pinned genes in fixed colours or every gene in its own hue, and a size slider. Fluorescence images get channel names, colours and fitted windows from the file, a channel list to switch and solo, and a bounded read (`max_size` holds for files without pyramids; Xenium morphology at 0.85 µm per pixel), and the viewer fetches each image tile once. **The side panel is five groups**: Image, Cells, Transcripts, Selections, Samples. **Comparisons**: differential expression results in the bundle, a Compare panel, and the canvas split into one pane per group with per-pane point size.

## 0.3.0 (2026-10-21)

**ATAC, multiome and notebooks.** Genome tracks from fragment files or existing bigWigs with a genome panel under the maps; `spatialscape.show(adata)` views an object from the session it is in, with lasso selections and regions flowing back; regions drawn in the viewer as groups of lassos; Seurat objects read directly; a faster, lighter expression writer; review fixes across the build, the viewer and the docs.

## 0.2.0 (2026-10-14)

**One yaml per dataset, one command.** `init` reads an R object (`.rds` / `.rda`) or AnnData files and writes a dataset yaml that is a menu of the data; `build` converts R objects once, rebuilds only what changed and applies every edit; `site.yaml` describes the gallery (`site init`, `site build`). Removed `convert`, `plan`, `refresh` and `add-sample`. Per-sample `subset`, fixed grid `columns`, cluster names on embeddings, a shared gene color scale, per-view point sizes, the viewer shipped inside the package (`serve`, `site build`), and the S3 + CloudFront hosting recipe.

## 0.1.0 (2026-10-06)

First public version.

**Viewer.** One-canvas mosaic or strip of all samples with focus and keyboard stepping; gene, annotation, feature-group and two-set blend coloring; legend filtering; independent filter channel (gene, continuous, categorical); hover with all annotations; lasso selection with composition, gene statistics and CSV export; expression-by-annotation dot plot; domain outlines; cell polygons at high zoom; H&E and fluorescence images; platform bar; linked snRNA-seq embedding split view; scale bar; registry gallery with real thumbnails and an optional site bar; full URL state.

**CLI.** `init`, `plan`, `inspect`, `build`, `add-sample`, `refresh`, `outlines`, `thumbnails`, `validate`, `serve`, `synth`. Globs and templates, per-platform defaults, automatic field and image discovery, sharded Zarr v3 uint8 expression, dataset-level vocabularies, OME-Zarr images, outline tracing, polygon packing, thumbnails.

The repository's [CHANGELOG.md](https://github.com/MicTott/spatialscape/blob/main/CHANGELOG.md) is the authoritative list.
