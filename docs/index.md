---
layout: home
title: spatialscape
hero:
  name: spatialscape
  text: One fast map for every section.
  tagline: A static, reactive browser for spatial transcriptomics and snRNA-seq. One pip install turns AnnData or SpatialExperiment into a dataset you can open locally or publish as a site.
  image:
    src: /hero.png
    alt: spatialscape showing a Visium mosaic beside an snRNA-seq UMAP
  actions:
    - theme: brand
      text: Get started
      link: /guide/getting-started
    - theme: alt
      text: Open the demo
      link: https://mictott.github.io/spatialscape/
    - theme: alt
      text: GitHub
      link: https://github.com/MicTott/spatialscape
features:
  - icon: 🗺️
    title: Every sample on one canvas
    details: All sections of a study side by side under identical settings. Double-click to focus, step through donors with the arrow keys, switch platforms with one click.
  - icon: ⚡
    title: Instant gene switching
    details: Expression is stored one byte per cell per gene in sharded Zarr, so a gene is a single range request and a cached switch is a GPU upload.
  - icon: 🎨
    title: Color, filter, outline
    details: Color by gene, two blended gene sets, or any annotation. Filter independently. Keep spatial-domain outlines on top of anything.
  - icon: 🔬
    title: Hover, lasso, compare
    details: Hover reads domain, cell type and expression. Lasso a region for composition, gene statistics and a CSV of cell IDs. A dot plot per annotation doubles as a filter.
  - icon: 🧬
    title: Linked snRNA-seq
    details: Paired references render as embeddings beside the tissue with one shared cell type vocabulary, so a color means the same thing everywhere.
  - icon: 📦
    title: Static everywhere
    details: No server. The app is files, the data is files. GitHub Pages, S3, Cloudflare R2, or a folder on a lab server with CORS and Range.
---

## In three commands

```bash
pip install spatialscape
spatialscape init "data/xenium/*/adata.zarr" --platform xenium --id my_atlas -o dataset.yaml
spatialscape build dataset.yaml -o bundles/my_atlas
```

Then open it, viewer included:

```bash
spatialscape serve bundles --open
```

And when it is ready for others, `spatialscape site build bundles -o site` writes a folder to upload anywhere.

## Who it is for

**Labs publishing spatial data.** Put a dataset online alongside a paper without running a server, and give readers a link that opens the exact view you want them to see.

**Analysts.** Browse a million cells at 60 fps, check a marker across every donor at once, and lasso a region to see what is in it.

**Institutes.** A registry turns the viewer into a data portal, and an optional site bar lets it sit inside an institutional website.
