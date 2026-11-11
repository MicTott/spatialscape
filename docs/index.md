---
layout: home
title: spatialscape
hero:
  name: spatialscape
  text: One fast map for every section.
  tagline: A static, reactive browser for spatial transcriptomics and snRNA-seq. One pip install turns an AnnData, SpatialExperiment or Seurat object into a dataset you can open locally or publish as a site.
  image:
    src: /hero.png
    alt: a mouse brain Visium HD section colored by cluster
  actions:
    - theme: brand
      text: Get started
      link: /guide/getting-started
    - theme: alt
      text: Live examples
      link: https://d2lbhik7smmaaj.cloudfront.net
    - theme: alt
      text: GitHub
      link: https://github.com/MicTott/spatialscape
features:
  - icon: 🗺️
    title: Every sample on one canvas
    details: All sections of a study side by side under identical settings, with paired snRNA-seq embeddings beside the tissue in the same cell type colors. Double-click to focus, step through donors with the arrow keys.
  - icon: ⚡
    title: Instant gene switching
    details: Expression is stored one byte per cell per gene in sharded Zarr, so a gene is a single range request and a cached switch is a GPU upload.
  - icon: 🔬
    title: From a whole study to single transcripts
    details: Zoom in and dots become cell boundaries, then individual transcripts, over the H&E or the fluorescence channels. Only the tiles in view are fetched.
  - icon: 🎨
    title: Color, filter, lasso
    details: Color by a gene, two blended gene sets or any annotation, and filter independently of the colour. Hover reads every annotation of a cell; a lasso gives composition, gene statistics and a CSV of cell IDs.
  - icon: ⚖️
    title: Compare and test
    details: Pin two sections side by side or split the canvas by condition. Draw regions and test them against each other in the browser, or show the differential expression results you fitted next to the tissue.
  - icon: 📦
    title: Static everywhere
    details: No server. The app is files, the data is files. GitHub Pages, S3, Cloudflare R2, or a folder on a lab server with CORS and Range.
---

## See it on real data

[![Twelve Visium sections of human dorsolateral prefrontal cortex on one canvas, H&E under the manual layer annotation](/screenshots/dlpfc-layers.jpg)](https://d2lbhik7smmaaj.cloudfront.net/?d=visium-human-dlpfc)

Twelve Visium sections of human cortex on one canvas, the H&E under the layer annotation; the picture opens the app. It is one of nine in the **[examples gallery](https://d2lbhik7smmaaj.cloudfront.net)**, one public dataset per technology: Visium, Visium CytAssist, Visium HD, Xenium, MERSCOPE, CosMx, Atera, spatial ATAC + RNA, and the Allen whole mouse brain, 8 million cells and nuclei. Nothing to install, and each rebuilds from the published files with the scripts in [Reproduce the examples](/guide/examples).

## In three commands

```bash
pip install spatialscape
spatialscape init analysis/spe_dlpfc.rds --id dlpfc      # writes dlpfc.yaml, a menu of what the data contains
spatialscape build dlpfc.yaml                            # -> bundles/dlpfc; rerun after any edit
```

Then open it, viewer included:

```bash
spatialscape serve bundles --open
```

And when it is ready for others, `spatialscape site build bundles -o site` writes a folder to upload anywhere; a gallery of several datasets is described in a `site.yaml`. [How it fits together](/guide/getting-started#how-it-fits-together) shows which files you edit and which folders you upload.

## Who it is for

**Labs publishing spatial data.** Put a dataset online alongside a paper without running a server, and give readers a link that opens the exact view you want them to see.

**Analysts.** Browse a million cells at 60 fps, check a marker across every donor at once, and lasso a region to see what is in it.

**Institutes.** A gallery turns the viewer into a data portal, and an optional site bar lets it sit inside an institutional website.
