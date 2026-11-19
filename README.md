<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/MicTott/spatialscape/main/docs/public/brand/banner-dark.svg">
    <img src="https://raw.githubusercontent.com/MicTott/spatialscape/main/docs/public/brand/banner-light.svg" width="372" alt="spatialscape">
  </picture>
</p>

<p align="center">
  A static, reactive browser for spatial transcriptomics and snRNA-seq.<br>
  One <code>pip install</code> turns a SpatialExperiment or AnnData into a dataset you can open locally or publish as a website.
</p>

<p align="center">
  <a href="https://mictott.github.io/spatialscape/docs/"><b>Documentation</b></a>
  &nbsp;·&nbsp; <a href="https://mictott.github.io/spatialscape/docs/guide/getting-started">Getting started</a>
  &nbsp;·&nbsp; <a href="https://mictott.github.io/spatialscape/examples/">Live examples</a>
  &nbsp;·&nbsp; <a href="CHANGELOG.md">Changelog</a>
</p>

<p align="center">
  <a href="https://github.com/MicTott/spatialscape/actions/workflows/python.yml"><img src="https://github.com/MicTott/spatialscape/actions/workflows/python.yml/badge.svg" alt="python"></a>
  <a href="https://github.com/MicTott/spatialscape/actions/workflows/app.yml"><img src="https://github.com/MicTott/spatialscape/actions/workflows/app.yml/badge.svg" alt="app"></a>
  <a href="https://mictott.github.io/spatialscape/docs/"><img src="https://github.com/MicTott/spatialscape/actions/workflows/pages.yml/badge.svg" alt="docs"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-3776ab" alt="Python 3.11+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
  <a href="https://doi.org/10.5281/zenodo.24376035"><img src="https://zenodo.org/badge/DOI/10.5281/zenodo.24376035.svg" alt="DOI 10.5281/zenodo.24376035"></a>
</p>

## Why

Browsing a spatial transcriptomics dataset should feel seamless: every section of a study should be viewable in the same space, genes should load in milliseconds, linked views should be available between multiple data modalities (spatial, snRNA-seq, multiome, proteomics, etc), and there should be nothing to run but a static web host to keep costs low. spatialscape is a viewer built to do exactly this.

- **Every sample on one canvas.** All sections of a study sit side by side under identical settings. Double-click to focus, step through donors with the arrow keys, switch platforms with one click.
- **Instant.** Expression is stored one byte per cell per gene in sharded Zarr, so a gene is one HTTP range request and a cached switch is a GPU upload. Panning and zooming run at the display's refresh rate because the viewer draws a uniform subsample of the cells at overview zoom and every cell once zoomed in, so what is on screen, not what is in the dataset, sets the frame time; the scripts in `benchmarks/` measure this on any bundle.
- **Linked snRNA-seq and ATAC.** Paired references render as embeddings beside the tissue with one shared cell type vocabulary, including genomic ranges to visualize chromatin accessibility.

## Quick start

```bash
pip install spatialscape
spatialscape synth demo-src                      # two fake sections, an embedding and a dataset.yaml
spatialscape build demo-src/dataset.yaml         # -> demo-src/bundles/synthetic
spatialscape serve demo-src/bundles --open       # viewer + data at http://127.0.0.1:8787/
```

## Your own data

From a folder of your project: a saved R object (`SpatialExperiment` / `SingleCellExperiment` / Seurat with its Visium slices, as `.rds` or `.rda`, parsed in Python, no R needed), AnnData files, a SpatialData store (its shapes, labels, points and images included) or a spatialproteomics object:

```bash
mkdir -p spatialscape && cd spatialscape
spatialscape init ../analysis/spe_dlpfc.rds --id dlpfc --name "Human DLPFC"   # writes ./dlpfc.yaml, a menu of the data, and prints what it assumed
# edit dlpfc.yaml: keep the annotations you want, name them, pick colors and the opening gene
spatialscape build dlpfc.yaml                                                 # -> bundles/dlpfc; rerun after any edit
spatialscape serve bundles --open
spatialscape site build bundles -o site                                       # viewer + gallery + data, ready to upload
```

`init` maps the columns that look like spatial domains, cell types and QC metrics, lists every other column as a comment, and says which platform, coordinate units and layer it took for granted, so most edits are deleting or uncommenting a line. `build` is incremental: a rename or a new palette takes seconds, a re-exported file rebuilds that one sample. For a gallery of several datasets with a title, paper links and "coming soon" cards, `spatialscape site init` writes a `site.yaml` and `spatialscape site build site.yaml` builds it.

```
myproject/
  analysis/spe_dlpfc.rds        your object, never modified
  spatialscape/
    dlpfc.yaml                  yours to edit: samples, annotations, names, colors
    site.yaml                   yours to edit: title, cards, paper links (optional)
    bundles/dlpfc/              the built dataset: upload this to a data host
    bundles/.cache/             R objects converted to AnnData; local only
    site/                       the finished website: upload this
```

The [documentation](https://mictott.github.io/spatialscape/docs/) walks through every step:
[how it fits together](https://mictott.github.io/spatialscape/docs/guide/getting-started#how-it-fits-together),
[writing dataset.yaml](https://mictott.github.io/spatialscape/docs/guide/dataset-yaml),
[making changes](https://mictott.github.io/spatialscape/docs/guide/changes),
[publishing a site](https://mictott.github.io/spatialscape/docs/guide/publish) and the
[CLI reference](https://mictott.github.io/spatialscape/docs/reference/cli/).

## In a notebook or an R session

No yaml, no site: show the object you have in memory, lasso cells, take them back out.

```python
import spatialscape
s = spatialscape.show(adata, color="cell_type")   # builds once into a cache, opens under the cell
cells = s.selection()                              # obs names inside the last lasso
sub = adata[cells]                                 # straight into a DE test
```

From R, `reticulate::py_require("spatialscape")`, one `saveRDS`, and `ss$show("spe.rds")` does the same for a SpatialExperiment ([guide](https://mictott.github.io/spatialscape/docs/guide/notebooks)).

## What it looks like

<p align="center">
  <a href="https://mictott.github.io/spatialscape/examples/?d=abc-atlas&amp;ps=0.25&amp;pse=0.25&amp;cl=0"><img src="https://raw.githubusercontent.com/MicTott/spatialscape/main/docs/public/screenshots/abc-atlas.jpg" width="840" alt="The Allen whole mouse brain atlas: the UMAP of 4.0 million nuclei beside 59 MERFISH sections, colored by subclass"></a>
</p>
<p align="center"><sub>Scale: the Allen Brain Cell Atlas of the whole mouse brain, 4.0 million nuclei on their UMAP beside 59 MERFISH sections with another 4.0 million cells.</sub></p>

<p align="center">
  <a href="https://mictott.github.io/spatialscape/examples/?d=pbmc-multiome"><img src="https://raw.githubusercontent.com/MicTott/spatialscape/main/docs/public/clips/pbmc-multiome.gif" width="49%" alt="10x PBMC multiome, recorded in real time: genes typed in turn recolor the RNA and ATAC UMAPs and move the accessibility tracks to each gene"></a>
  <a href="https://mictott.github.io/spatialscape/examples/?d=atera&amp;v=5039,4729,2.8&amp;c=g:EPCAM&amp;mol=1&amp;mg=PTPRC%7CCOL1A1%7CACTA2%7CKRT8&amp;cs=outlined&amp;msz=2.00"><img src="https://raw.githubusercontent.com/MicTott/spatialscape/main/docs/public/clips/atera.gif" width="49%" alt="Atera breast cancer section, recorded in real time: a zoom from the whole section to single transcripts, genes typed in turn, then every gene at once"></a>
</p>
<p align="center"><sub>Left, breadth: a 10x multiome, RNA and ATAC UMAPs of the same nuclei over accessibility tracks per cell type. Right, new technology: a whole-transcriptome Atera section of breast cancer, single transcripts over the morphology image and the cell outlines. Both are real-time recordings of the public examples.</sub></p>

## How it works

`spatialscape build` writes a *bundle*: a folder of static files holding `manifest.json`, the gene lists and, per sample, a gene-major uint8 expression array (sharded Zarr v3), positions in microns, categorical codes, images, outlines and polygons. The viewer (React 19, deck.gl 9, Viv, zarrita) draws every sample in one WebGL context, decodes in a worker and recolors by uploading one byte per cell. The format is versioned (`formatVersion: 1`) and stable: changes within version 1 only add optional files, `spatialscape validate` is its conformance check, and any Zarr reader can open a bundle without spatialscape. Details: [bundle format](https://mictott.github.io/spatialscape/docs/reference/format), [architecture](https://mictott.github.io/spatialscape/docs/reference/architecture).

## License and citation

Spatialscape was developed at the Lieber Institute for Brain Development by Michael Totty, and meant for any one who wants to easily and openly view their (or others) datasets. As such, it freely available under the MIT license.

Please cite this package if you use it to share your data. To cite spatialscape, use its Zenodo DOI [10.5281/zenodo.24376035](https://doi.org/10.5281/zenodo.24376035) as shown below: 

**Totty, M. (2026). spatialscape: a static, reactive browser for spatial transcriptomics. Zenodo. https://doi.org/10.5281/zenodo.24376035**

### BibTex
```
@software{totty_spatialscape_2026,
  author    = {Totty, Michael},
  title     = {spatialscape: a static, reactive browser for spatial transcriptomics},
  year      = {2026},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.24376035},
  url       = {https://doi.org/10.5281/zenodo.24376035}
}
```
