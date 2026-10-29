# dataset.yaml schema

Validated by pydantic models in `python/src/spatialscape/config.py`. Unknown keys are errors. Paths are resolved relative to the YAML file. `spatialscape init` writes a yaml with every optional key present as a comment; `spatialscape build <yaml>` writes the bundle to `bundles/<id>` next to the yaml unless `-o` says otherwise.

## Top level

| Key | Type | Default | Notes |
|---|---|---|---|
| `id` | string | required | dataset id |
| `name` | string | required | |
| `description` | string | | |
| `default_gene` | string | | must exist in the gene union |
| `default_color` | `{gene}` or `{field}` | first categorical field | |
| `palette` | path | | `{vocabulary: {label: "#hex"}}` JSON |
| `layout` | `{mode, order, gutter_fraction, columns}` | `grid`, build order, `0.1`, fitted | `columns` fixes the grid width, e.g. `3` for a 3 × 3 of species by cell class |
| `thumbnail_sample` | sample id | first spatial sample | |
| `shard_genes` | int | `512` | genes per shard (capped to ~128 MB) |
| `sharded` | bool | `true` | sharded Zarr (one range request per gene; needs HTTP Range support) or one file per gene (`false`, for GitHub Pages and other hosts without Range). `build --no-shard` sets it for one run; put it here so `site build` and later builds keep it |
| `feature_groups` | list of `{id, name, pattern, strip, units}` | `[]` | regex over var names |
| `fields` | list of field specs | `[]` | declarations; undeclared fields are inferred |
| `meta` | list of `{id, name, levels}` | `[]` | sample metadata keys: display name and level order; keys used only on samples need no entry. See [Sample metadata](../guide/comparisons#sample-metadata) |
| `comparisons` | list of `{id, kind, name, description, results, pseudobulk, replicates, groups, units, population, split, link, facet, columns}` | `[]` | differential expression results fit upstream: `results` (one row per gene), `pseudobulk` (genes × replicates), `replicates` (id, group, subject), `groups` in pane order, `population` `{field, value}`, `split` / `link` meta keys, `columns` `{results: {role: column}, replicates: {role: column}}`. See [Comparisons](../guide/comparisons#comparisons-results-of-a-test-next-to-the-sections) `kind: markers` for a marker table (every level of the facet column against the rest); `facet: {column, field}` splits a table into one contrast per level, and `{level}` in `results` / `pseudobulk` names one file per level |
| `defaults` | mapping | `{}` | merged into every sample |
| `platforms` | `{platform: mapping}` | `{}` | merged into samples of that platform |
| `samples` | list of sample entries | required | may contain `glob:` entries |

## Field spec

| Key | Type | Notes |
|---|---|---|
| `id` | string | field id used by samples and the viewer |
| `name` | string | display name; default `id` |
| `type` | `categorical` or `continuous` | |
| `vocabulary` | string | share one vocabulary across fields; default `id` |
| `categories` | list | explicit order; others append first-seen |
| `aliases` | `{source: canonical}` | merge labels at build time |
| `palette_key` | string | key(s) in the palette file, comma-separated fallbacks |
| `colormap`, `range` | | continuous fields only |

## Sample entry

| Key | Type | Default | Notes |
|---|---|---|---|
| `glob` | pattern | | expands to one sample per match; `{name}`, `{stem}`, `{dir}`, `{i}` templates |
| `overrides` | `{<sample>: {keys}}` | | with `glob` or an R object: settings for single samples, keyed by `{name}` (`{stem}` in flat layouts, or the rendered id); dicts merge, lists and scalars replace; an unknown sample name is an error. `{ Br9902_1: { images: [] } }` |
| `path` ending in `.rds` / `.rda` | path | | an R object: converted by `build` into `bundles/.cache/<id>/` and expanded into one sample per `sample_col` value, or one embedding sample; `{name}` is the sample id. See [R objects as samples](../guide/dataset-yaml#r-objects-as-samples) |
| `assay`, `sample_col`, `embedding`, `object` | string | `logcounts`, `sample_id`, UMAP, | R objects only: the assay drawn (for a Seurat object a layer of its gene assay, `data` or `counts`; its other assays become `peak: ` / `activity: ` / `motif: ` features), the column that splits samples, the reducedDims entry or Seurat reduction for objects without spatialCoords, the object to take from an `.rda` |
| `id` | string | sanitized `{name}` | unique |
| `name` | string | `id` | |
| `platform` | `visium`, `visium_hd`, `xenium`, `merfish`, `snrnaseq`, `other` | required | |
| `kind` | `spatial` or `embedding` | `spatial` | |
| `group` | string | | donor or batch label |
| `path` | path | required | h5ad, AnnData zarr, SpatialData zarr, or an R object (above) |
| `table` | string | | SpatialData table key |
| `coords` | string | `obsm/spatial` | or `obs/x,obs/y` |
| `expression` | `{layer, normalized, keep_f16}` | `X`, `auto`, `false` | `normalized`: `auto`, `lognorm`, `counts` |
| `microns` | one of `already_microns`, `microns_per_unit`, `spot_diameter_fullres`, `spot_spacing`, `scalefactors_json` | inferred | |
| `transform` | `{flip: none \| x \| y, rotate: 0 \| 90 \| 180 \| 270}` | none | applied to points and images |
| `fields` | `{field_id: obs_column}` or `{field_id: {column, scale}}` or `auto` | `{}` | `scale` multiplies a numeric column, e.g. `100` to show a ratio as a percent |
| `meta` | `{key: value \| {column}}` | `{}` | sample-level metadata (condition, subject, ...): a templated string, or an obs column that holds one value in the sample; the viewer splits the canvas by these keys |
| `images` | list of image specs or `auto` | `auto` | |
| `molecules` | `{path, feature_column, x_column, y_column, qv_column, min_qv, cell_column, nucleus_column, affine}` | | individual molecules from a long table, Parquet, CSV or TSV (10x `transcripts.parquet` names are the defaults; `min_qv` 20); vertices share the raw frame of `polygons`, whose `affine` is inherited |
| `segmentations` | list of `{id, name, path, id_column, x_column, y_column, max_vertices, affine}` or `auto` | `auto` | other boundary sets of the section, drawn over the cells for comparison; `auto` takes a Xenium `nucleus_boundaries.parquet` next to the polygons' `cell_boundaries.parquet`; `affine` defaults to the polygons' |
| `polygons` | `{path \| obsm, id_column, x_column, y_column, max_vertices, affine}` | auto from `obsm` | one of `path` (a long table: Parquet, CSV or TSV, one row per vertex) or `obsm` (n, v, 2); `affine` maps vertices into the coordinate frame |
| `subset` | `{column, values}` | all rows | keep only observations whose obs column takes one of the values; one file can then appear as several samples (one panel per cell class, per condition, ...) |
| `tracks` | `{fragments \| bigwigs, by, genome, bin, normalize, tss_window, chrom_sizes, sample_column, barcode_column, units, genes, links}` | | genome tracks for ATAC samples: `fragments` (a bgzipped fragment file, or `{run: file}` with `sample_column` naming each observation's run when the object pools several runs; a file may be `ssh://host/path`, streamed and never stored) or `bigwigs` (`{by: {field: "dir/{label}.bw" \| {label: path}}, all}` exported by another tool), `by` (categorical field ids, one bigWig per category), `genome` (`hg38`, `mm10` or `mm39` carry built-in chromosome sizes), `bin` (`25` bp for fragments; read from bigWigs), `normalize` (`nfrags` per million insertions, `tss` per million insertions within `tss_window` bp of a TSS, `cells` per nucleus), optional `chrom_sizes`, `barcode_column`, `units` (the panel's scale label), `genes` (a GTF, genePred or BED file, `refseq` to download UCSC's table once, `none`) and `links` BEDPE. See [Genome tracks](../guide/tracks) |
| `extent` | number | `5000` | embeddings: world size of the longest side |
| `point_radius` | µm | per platform | Visium 27.5, Xenium 5, HD from spacing |
| `seed` | int | `7` | row shuffle |
| `gene_column` | var column | `var_names` | feature names; when `var_names` are Ensembl ids and a `gene_name` / `symbol` column exists, that column is used by default (missing symbols keep their id, duplicates get `.1`, `.2`) |

## Image spec

| Key | Type | Default |
|---|---|---|
| `id`, `name` | string | `image`, `Image` |
| `path` | path | required |
| `kind` | `rgb` or `multichannel` | `rgb` |
| `pixel_size` | µm per level-0 pixel, or `auto` | `auto` |
| `pixels_per_unit` | image pixels per coordinate unit | `1.0` |
| `translate` | `[x, y]` µm | `[0, 0]` |
| `transpose`, `flip` | bool, `x`/`y`/`xy` | `false`, none | the image's own frame against the coordinates, before the sample's `transform`: for an object whose coordinates were transposed after the image was written. `polygons.affine` `[0, 1, 0, 1, 0, 0]` is `transpose: true`; `[0, -1, Y, -1, 0, X]` is `transpose: true, flip: xy` with `translate` taking up `Y - height`, `X - width` |
| `channels` | list of `{name, color, window}` | |
| `default_opacity` | 0..1 | `1` |
| `max_size` | int | | at most this many pixels per side: the pyramid level giving the largest copy within it, reduced while it is read when needed, so memory stays bounded even for a file without pyramid levels. Auto-discovered Xenium morphology uses the size that gives about 0.85 µm per pixel, halved on a machine without the memory for it. A read larger than a sixth of the machine's memory is refused until `max_size` is set or lowered |
| `crop` | bool | `true` | keep only the part of the image around the points (3% margin), so a slide scan does not size the grid cell; `false` keeps the whole image |
| `mask`, `mask_margin` | bool, µm | `false`, `150` | blank the image beyond `mask_margin` of the sample's own points. Set on its own when sibling sample folders of a converted R object hold the very same image (several sections cut from one slide), so a neighbour's tissue does not appear under this sample |
