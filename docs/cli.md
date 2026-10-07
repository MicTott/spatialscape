# spatialscape CLI

```
spatialscape inspect <h5ad|zarr|spatialdata.zarr> [--table KEY]   print obs columns, obsm keys, scale hints
spatialscape build dataset.yaml -o <bundle> [--no-shard]           build the whole bundle (then validates it)
spatialscape add-sample dataset.yaml -o <bundle> --sample <id>     rebuild one sample; vocabularies are append-only
spatialscape validate <bundle | https://host/bundle>               schema, shapes, codes; for URLs also CORS + Range
spatialscape refresh dataset.yaml -o <bundle>                     rewrite manifest/genes/features without rebuilding samples
spatialscape outlines dataset.yaml -o <bundle> [--sample id] [--field id] [--smooth-um 150] [--min-feature-um 300]
                                                             trace categorical boundaries from the bundle's own arrays
spatialscape serve <dir> [--port 8787]                             dev server with CORS and HTTP Range
spatialscape synth <dir>                                           tiny synthetic inputs + dataset.yaml
```

## dataset.yaml

The quickest start is `spatialscape init`, which writes a draft from one or more globs:

```bash
spatialscape init "data/xenium/*/adata.zarr" --platform xenium --id amygdala --name "Human amygdala" -o dataset.yaml
spatialscape plan dataset.yaml       # shows the expanded sample list without building
spatialscape build dataset.yaml -o bundle
```

A complete config for several platforms stays short because of three mechanisms:

- **Globs with templates.** A `glob:` entry expands to one sample per match; `{name}` (matched folder), `{stem}` (file name without extension), `{dir}` and `{i}` fill in `id`, `name`, `group`.
- **`platforms` and `defaults` blocks.** Keys every sample of a platform shares (field mappings, image settings, normalization) are written once; a sample can still override any of them.
- **Automatic discovery.** `fields: auto` exposes every categorical column with 2 to 200 levels plus QC-like numeric columns (counts, detected, percent, area, score ...). `images: auto` (the default) picks up `image.ome.zarr` / `*.ome.zarr` next to the data, or a SpaceRanger `spatial/tissue_hires_image.png` with its `scalefactors_json.json`, or a Xenium `morphology_focus.ome.tif`. Fields that samples reference without a declaration are declared automatically, with the type inferred from the data; declare a field only to give it a display name, palette key, alias or explicit category order.

```yaml
id: amygdala
name: Human amygdala
default_gene: PENK
default_color: { field: domain }          # or { gene: PENK }
palette: palette.json                     # optional {vocabId: {label: "#hex"}}
layout: { mode: grid }                    # grid | strip
feature_groups:                           # var names matching `pattern` get their own tab (not in the gene search)
  - { id: rctd, name: Cell type weights (RCTD), pattern: "^RCTD: ", units: weight }
fields:                                   # only what needs a name / palette / alias
  - { id: domain, name: Spatial domain, type: categorical, aliases: { AI: IA }, palette_key: "visium_domain,xenium_domain" }
platforms:
  xenium:
    fields: { domain: Banksy_domains, celltype: first_type, total_counts: total_counts }
  visium:
    fields: { domain: BS_k16, total_umi: sum_umi }
    microns: { spot_diameter_fullres: 89.4 }   # or already_microns | microns_per_unit | spot_spacing | scalefactors_json (auto for SpaceRanger folders)
samples:
  - glob: xenium/*/adata.zarr
    platform: xenium
    id: "xen_{name}"
    name: "{name} (Xenium)"
    group: "{name}"
  - glob: visium/*/outs
    platform: visium
    id: "vis_{name}"
    transform: { flip: none, rotate: 0 }  # applied to coordinates AND images together
  - id: sn
    name: snRNA-seq
    platform: snrnaseq
    kind: embedding
    path: sce.h5ad
    coords: obsm/X_umap
    extent: 5000
    fields: auto
```

Per-sample keys: `path` (h5ad, AnnData zarr v2/v3, or SpatialData zarr with `table:`), `coords` (`obsm/<key>` or `obs/x,obs/y`), `expression{layer, normalized: auto|lognorm|counts}`, `microns`, `transform`, `fields`, `images[]{id, name, path, kind, pixel_size, pixels_per_unit, translate, channels}`, `polygons{path, id_column, x_column, y_column, max_vertices}`, `extent` (embeddings), `point_radius`, `seed`.

Micron inference when `microns:` is omitted: Xenium/MERFISH coordinates are already µm; Visium uses `uns["spot_nn_spacing_level0_px"]` (100 µm centre-to-centre), SpaceRanger scalefactors found under `uns["spatial"]`, or the `spatial/scalefactors_json.json` that `images: auto` discovers; embeddings are rescaled so the longest side equals `extent`.

## From R

```r
# SpatialExperiment / SingleCellExperiment -> h5ad, then spatialscape build
zellkonverter::writeH5AD(spe, "sample.h5ad", X_name = "logcounts")
# or anndataR::write_h5ad(anndataR::as_AnnData(spe), "sample.h5ad")
```

Keep `spatialCoords(spe)` in `obsm/spatial` (zellkonverter does this for SPE) and pass the H&E as a PNG/TIFF plus the matching scale factor.
