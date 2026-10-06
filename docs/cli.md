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

```yaml
id: amygdala
name: Human amygdala
default_gene: PENK
default_color: { field: domain }          # or { gene: PENK }
palette: palette.json                     # optional {vocabId: {label: "#hex"}}; labels not found get a stable fallback colour
layout: { mode: grid, order: [...] }      # grid | strip
shard_genes: 512
feature_groups:                           # var names matching `pattern` get their own tab (not in the gene search)
  - { id: rctd, name: Cell type weights (RCTD), pattern: "^RCTD: ", units: weight }
fields:
  - { id: domain, name: Spatial domain, type: categorical, aliases: { AI: IA }, palette_key: "visium_domain,xenium_domain" }
  - { id: celltype, name: Cell type, type: categorical }
  - { id: total_counts, name: Total UMI, type: continuous }
samples:
  - id: Br2743
    name: Br2743 (Visium)
    platform: visium                      # visium | visium_hd | xenium | merfish | snrnaseq | other
    group: Br2743
    path: visium/Br2743.h5ad              # h5ad, AnnData zarr (v2/v3), or SpatialData zarr (+ table:)
    coords: obsm/spatial                  # or "obs/x,obs/y"
    expression: { layer: X, normalized: auto }   # auto detects log-normalised vs counts (-> log1p CP10k)
    microns: { spot_diameter_fullres: 89.4 }     # or already_microns | microns_per_unit | spot_spacing | scalefactors_json
    transform: { flip: none, rotate: 0 }  # applied to coordinates AND images together
    fields: { domain: BS_k16, total_counts: sum_umi }
    images:
      - { id: he, name: H&E, path: visium/Br2743_hires.png, pixel_size: auto, pixels_per_unit: 0.0709 }
    polygons: { path: xenium/cell_boundaries.parquet, id_column: cell_id, x_column: vertex_x, y_column: vertex_y, max_vertices: 24 }  # optional; same frame as coords
  - id: sn
    name: snRNA-seq
    platform: snrnaseq
    kind: embedding
    path: sce.h5ad
    coords: obsm/X_umap
    extent: 5000
    fields: { celltype: fine_type }
```

Micron inference when `microns:` is omitted: Xenium/MERFISH coordinates are already µm; Visium uses `uns["spot_nn_spacing_level0_px"]` (100 µm centre-to-centre) or SpaceRanger scalefactors found under `uns["spatial"]`; embeddings are rescaled so the longest side equals `extent`.

Images with `pixel_size: auto` share the coordinate frame of `coords` (`pixels_per_unit` image pixels per coordinate unit, 1.0 when the coordinates are in level-0 pixels of that image). Otherwise give `pixel_size` in µm per pixel and, if needed, `translate` in µm.

## From R

```r
# SpatialExperiment / SingleCellExperiment -> h5ad, then spatialscape build
zellkonverter::writeH5AD(spe, "sample.h5ad", X_name = "logcounts")
# or anndataR::write_h5ad(anndataR::as_AnnData(spe), "sample.h5ad")
```

Keep `spatialCoords(spe)` in `obsm/spatial` (zellkonverter does this for SPE) and pass the H&E as a PNG/TIFF plus the matching scale factor.
