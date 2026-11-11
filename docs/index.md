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
      link: https://mictott.github.io/spatialscape/
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

[![The Allen whole mouse brain atlas: the UMAP of 4.0 million nuclei beside 59 MERFISH sections, colored by subclass](/screenshots/abc-atlas.jpg)](https://mictott.github.io/spatialscape/?d=abc-atlas&ps=0.25&pse=0.25&cl=0)

**Scale.** The Allen Brain Cell Atlas of the whole mouse brain in one app: 4.0 million nuclei on their UMAP beside 59 MERFISH sections holding another 4.0 million cells, one legend for both. The picture opens the app.

<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); gap: 20px; margin-top: 24px;">
<div>

[![10x PBMC multiome: the RNA and ATAC UMAPs of the same nuclei over the accessibility tracks at MS4A1](/screenshots/pbmc-multiome.jpg)](https://mictott.github.io/spatialscape/?d=pbmc-multiome)

**Breadth.** A 10x multiome: the RNA and ATAC UMAPs of the same nuclei with one cell type legend, over accessibility tracks per cell type at MS4A1.

</div>
<div>

[![Atera breast cancer section zoomed to single cells: transcripts of five genes over the morphology image and the cell outlines](/screenshots/atera-transcripts.jpg)](https://mictott.github.io/spatialscape/?d=atera&v=5039,4729,2.8&c=g:EPCAM&mol=1&mg=PTPRC%7CCOL1A1%7CACTA2%7CKRT8&cs=outlined&msz=2.00)

**New technology.** A whole-transcriptome Atera section of breast cancer, zoomed until single transcripts draw over the morphology image and the cell outlines.

</div>
</div>

These three are among the eleven in the **[examples gallery](https://mictott.github.io/spatialscape/)**, one public dataset per technology: Visium, Visium CytAssist, Visium HD, Xenium, MERSCOPE, CosMx, Atera, PhenoCycler spatial proteomics, spatial ATAC + RNA, a 10x multiome, and the Allen whole mouse brain. Nothing to install, and each rebuilds from the published files with the scripts in [Reproduce the examples](/guide/examples).

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
