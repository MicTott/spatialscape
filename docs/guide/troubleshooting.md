# Troubleshooting

## "Could not load dataset" with a CORS or Range hint

The browser could not fetch `manifest.json`, or fetched it without the headers the viewer needs. Run `spatialscape validate <url>`; it reports exactly which header or status is missing. GitHub Pages and some institutional servers do not honor `Range`.

## The page loads but no points appear

- Open the browser console. A CORS error on `obs.zarr/xy` or `expr.zarr/u8` means the bucket policy allows the manifest but not range requests on other paths.
- The status bar shows per-sample state; a red frame and "(failed to load)" label mark samples whose arrays could not be read.

## Points are off the tissue

The coordinates and the image are in different frames. Check `pixels_per_unit` (image pixels per coordinate unit) and whether a `transform` was applied to one but not the other. The build log prints the micron scale it inferred; compare it with what you expect (Visium: 100 µm between spot centers).

## "cannot infer microns per coordinate unit"

The sample is neither a Visium file with SpaceRanger scale factors nor a platform whose coordinates are known
to be microns. Three usual answers:

- coordinates already in microns (Xenium, MERFISH, most segmentation outputs): `platform: xenium` /
  `merfish`, or `microns: { already_microns: true }` on another platform;
- Visium HD: `microns: { microns_per_unit: <SpaceRanger microns_per_pixel> }`;
- Visium without scale factors in the file: `microns: { spot_spacing: <pixels between spot centres> }` or
  `{ scalefactors_json: spatial/scalefactors_json.json }`.

`images: []` on a SpaceRanger-layout sample keeps the scale factors next to it. See
[Getting the scale right](./preparing-data#getting-the-scale-right).

## Gene search does not find a gene

The gene is not in `genes.json`, which holds the union across samples minus any feature groups. Check `spatialscape inspect` for the var names, and whether a `feature_groups.pattern` captured it.

## A sample is grey

The selected feature is not measured on that sample (a gene missing from a Xenium panel, RCTD weights on snRNA-seq). Grey means "not measured", not "zero".

## The build is slow

Expression is written in one pass over the stored values: a Visium donor with 36k genes and 30k spots takes 3–6 s, a 15k-nucleus snRNA-seq object about 4 s, and `--no-shard` is not faster. A slow build is almost always the input: a large `.h5ad` on a network drive, an R object converted on first use (into `bundles/.cache`, once), or a full-resolution image without pyramid levels (export it as a pyramidal OME-TIFF or OME-Zarr, which `build` reads at the level `max_size` asks for). Peak memory is about the matrix of the largest sample, twice that for files that store it row-wise (CSR is transposed once), plus one 128 MB shard. After the first build only the samples whose inputs or settings changed are rebuilt, so edits to names, colors and defaults take seconds; `spatialscape build <yaml> --dry-run` shows what a run would do before it starts.

## A sample was rebuilt that I did not change

`build` compares each sample's `build.json` with the yaml and the input files. Touching a source file (a fresh export with identical content, a copy that reset modification times) counts as `source changed`; editing a declared field's `aliases`, `categories`, `type` or `vocabulary` rebuilds every sample that maps it; `--no-shard` on and off flips every sample. The reason is printed next to each sample. Bundles built before fingerprints existed are rebuilt once in full.

## "genome tracks need pyBigWig"

Building `tracks:` needs the optional dependency: `pip install "spatialscape[tracks]"`. On platforms without a
prebuilt wheel it compiles against zlib and libcurl; a C compiler and those headers are enough.

## An R object was converted again

The conversion cache under `bundles/.cache/<id>/` is keyed on the object's path, size and modification time plus `assay`, `sample_col`, `embedding` and `object`. Re-saving the object or changing any of those converts again; editing `fields:` or anything else never does.

## Outlines look fragmented or too coarse

Tune `spatialscape outlines dataset.yaml -o bundle --smooth-um 150 --min-feature-um 300`. Larger values merge islands; smaller values follow finer structure. Cells labeled `NA` are treated as unknown and filled by their neighbors.

## Polygons matched 0 cells

The `cell_id` values in the boundary file do not match `obs_names`. This happens when the object was built from a different segmentation run than the boundary file. Use the boundaries from the run that produced the cells.

## Warning: polygon centroids sit far from their cells

Ids matched but the vertices are in another frame: the coordinates were transposed, mirrored or cropped after segmentation. Set `polygons.affine` to undo that (see [Inputs: what the CLI reads](./preparing-data#cell-boundary-polygons)). For a crop, the shift is the crop origin in the uncropped frame.

## The hosted viewer cannot open my local bundle

A page on `https://mictott.github.io` fetching `http://127.0.0.1:8787` is a public site reaching into your local network. Browsers increasingly gate that behind a permission prompt (Chrome's local-network access) or block it outright, and the error reads like a CORS failure. Use `spatialscape serve` instead: it serves the viewer and the data from the same local address, so nothing crosses origins.

## Headless or hidden tabs

The viewer falls back to timers when `requestAnimationFrame` is paused (hidden tab, collapsed pane), so data keeps loading; rendering resumes when the tab is visible.
