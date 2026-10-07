# dataset.yaml schema

Validated by pydantic models in `python/src/spatialscape/config.py`. Unknown keys are errors. Paths are resolved relative to the YAML file.

## Top level

| Key | Type | Default | Notes |
|---|---|---|---|
| `id` | string | required | dataset id |
| `name` | string | required | |
| `description` | string | | |
| `default_gene` | string | | must exist in the gene union |
| `default_color` | `{gene}` or `{field}` | first categorical field | |
| `palette` | path | | `{vocabulary: {label: "#hex"}}` JSON |
| `layout` | `{mode, order, gutter_fraction}` | `grid`, build order, `0.1` | |
| `thumbnail_sample` | sample id | first spatial sample | |
| `shard_genes` | int | `512` | genes per shard (capped to ~128 MB) |
| `feature_groups` | list of `{id, name, pattern, strip, units}` | `[]` | regex over var names |
| `fields` | list of field specs | `[]` | declarations; undeclared fields are inferred |
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
| `id` | string | sanitized `{name}` | unique |
| `name` | string | `id` | |
| `platform` | `visium`, `visium_hd`, `xenium`, `merfish`, `snrnaseq`, `other` | required | |
| `kind` | `spatial` or `embedding` | `spatial` | |
| `group` | string | | donor or batch label |
| `path` | path | required | h5ad, AnnData zarr, SpatialData zarr |
| `table` | string | | SpatialData table key |
| `coords` | string | `obsm/spatial` | or `obs/x,obs/y` |
| `expression` | `{layer, normalized, keep_f16}` | `X`, `auto`, `false` | `normalized`: `auto`, `lognorm`, `counts` |
| `microns` | one of `already_microns`, `microns_per_unit`, `spot_diameter_fullres`, `spot_spacing`, `scalefactors_json` | inferred | |
| `transform` | `{flip: none \| x \| y, rotate: 0 \| 90 \| 180 \| 270}` | none | applied to points and images |
| `fields` | `{field_id: obs_column}` or `{field_id: {column, scale}}` or `auto` | `{}` | `scale` multiplies a numeric column, e.g. `100` to show a ratio as a percent |
| `images` | list of image specs or `auto` | `auto` | |
| `polygons` | `{path \| obsm, id_column, x_column, y_column, max_vertices, affine}` | auto from `obsm` | one of `path` (long-format parquet) or `obsm` (n, v, 2); `affine` maps vertices into the coordinate frame |
| `extent` | number | `5000` | embeddings: world size of the longest side |
| `point_radius` | µm | per platform | Visium 27.5, Xenium 5, HD from spacing |
| `seed` | int | `7` | row shuffle |
| `gene_column` | var column | `var_names` | |

## Image spec

| Key | Type | Default |
|---|---|---|
| `id`, `name` | string | `image`, `Image` |
| `path` | path | required |
| `kind` | `rgb` or `multichannel` | `rgb` |
| `pixel_size` | µm per level-0 pixel, or `auto` | `auto` |
| `pixels_per_unit` | image pixels per coordinate unit | `1.0` |
| `translate` | `[x, y]` µm | `[0, 0]` |
| `channels` | list of `{name, color, window}` | |
| `default_opacity` | 0..1 | `1` |
| `max_size` | int | | downsample level 0 to this many pixels per side |
