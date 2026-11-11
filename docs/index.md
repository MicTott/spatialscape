---
layout: home
title: spatialscape
hero:
  name: spatialscape
  text: Spatial and single-cell data visualization
  tagline: Spatialscape displays transcriptomics, chromatin accessibility, proteomics and tissue images across samples in a browser. The Python package builds datasets for local use or static web hosting.
  image:
    src: /hero.png
    alt: A mouse brain Visium HD section colored by cluster
  actions:
    - theme: brand
      text: Getting started
      link: /guide/getting-started
    - theme: alt
      text: Example datasets
      link: https://mictott.github.io/spatialscape/examples/
    - theme: alt
      text: GitHub
      link: https://github.com/MicTott/spatialscape
features:
  - title: Samples and embeddings
    details: Display tissue sections in a grid or strip, with single-cell embeddings in an adjacent pane. Share cell-type colors and filters across samples, or pin two sections for comparison.
  - title: Expression and annotations
    details: Color cells by a gene, gene-set score or annotation. Filter cells independently of their color, and inspect values by hovering over a cell.
  - title: Images and transcripts
    details: Display histology or fluorescence images beneath cells. Add cell boundaries and transcript positions when the dataset includes them; these layers load by spatial tile as you zoom in.
  - title: Regions of interest
    details: Draw regions across sections, inspect their composition and expression, and export cell IDs. In a notebook, return selected cells to the analysis object.
  - title: Comparisons and genome tracks
    details: Display imported differential expression results alongside tissue sections. Add accessibility tracks from fragment files or bigWigs for ATAC and multiome datasets.
  - title: Hosting
    details: The viewer and data bundles are static files. Preview them locally, or publish them on a web server or object storage with the required HTTP headers.
---

## Build and open a dataset

Install spatialscape, create a configuration from your data, then build and open the viewer:

```bash
pip install spatialscape
spatialscape init analysis/spe_dlpfc.rds --id dlpfc   # writes dlpfc.yaml
# Review dlpfc.yaml: samples, annotations, coordinates and display settings.
spatialscape build dlpfc.yaml                        # writes bundles/dlpfc
spatialscape serve bundles --open
```

The input above is a saved `SpatialExperiment`. AnnData, SingleCellExperiment, Seurat and SpatialData inputs
are also supported; see [Preparing data](/guide/preparing-data). The [getting started guide](/guide/getting-started)
includes installation requirements and a synthetic dataset to try first.

Edit `dlpfc.yaml` and rerun `build` to change annotations, colors or samples. To publish the result,
`spatialscape site build bundles -o site` creates a folder containing the viewer and datasets.
See [Making changes](/guide/changes) and [Publishing a site](/guide/publish) for the full steps.

## Example datasets

[![The Allen whole mouse brain atlas: the UMAP of 4.0 million nuclei beside 59 MERFISH sections, colored by subclass](/screenshots/abc-atlas.jpg)](https://mictott.github.io/spatialscape/examples/?d=abc-atlas&ps=0.25&pse=0.25&cl=0)

**Allen Brain Cell Atlas.** A UMAP of 4.0 million nuclei beside 59 MERFISH sections containing another
4.0 million cells. Both views use the same cell-type legend. Click the image to open the dataset.

<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); gap: 20px; margin-top: 24px;">
<div>

[![10x PBMC multiome: the RNA and ATAC UMAPs of the same nuclei over the accessibility tracks at MS4A1](/screenshots/pbmc-multiome.jpg)](https://mictott.github.io/spatialscape/examples/?d=pbmc-multiome)

**PBMC RNA and ATAC.** RNA and ATAC embeddings of the same nuclei, with shared cell-type annotations and
accessibility tracks at MS4A1.

</div>
<div>

[![Atera breast cancer section zoomed to single cells: transcripts of five genes over the morphology image and the cell outlines](/screenshots/atera-transcripts.jpg)](https://mictott.github.io/spatialscape/examples/?d=atera&v=5039,4729,2.8&c=g:EPCAM&mol=1&mg=PTPRC%7CCOL1A1%7CACTA2%7CKRT8&cs=outlined&msz=2.00)

**Atera breast cancer.** Transcript positions over a morphology image and cell boundaries in a
whole-transcriptome tissue section.

</div>
</div>

The [examples gallery](https://mictott.github.io/spatialscape/examples/) also includes Visium, Visium CytAssist,
Visium HD, Xenium, MERSCOPE, CosMx, PhenoCycler and spatial ATAC + RNA datasets.
[Reproduce the examples](/guide/examples) describes their source data, build scripts and requirements.

## Documentation

- [Notebook and R sessions](/guide/notebooks): open an object and retrieve selected cells.
- [Dataset configuration](/guide/dataset-yaml): set samples, annotations, palettes and display defaults.
- [Using the viewer](/guide/viewer): navigate, filter, compare and export data.
- [Publishing and hosting](/guide/publish): build a gallery and put it online.
- [CLI reference](/reference/cli/): command arguments, options and examples.
