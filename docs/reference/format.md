# Bundle format

`formatVersion: 1`. A bundle is a directory of static files; everything is addressable by URL with plain `GET` and `Range` requests.

```
<dataset>/
  manifest.json                dataset description (python: manifest.py, app: data/manifest.ts)
  genes.json                   sorted union of plain gene symbols (autocomplete)
  features.json                {genes, groups:[{id, name, units, features:[{id, label}]}]}
  thumbnail.png                one section colored by the default annotation
  build-info.json              spatialscape version, config path, build time
  samples/<sampleId>/
    build.json                 fingerprint of the inputs and settings this sample was built from (incremental builds)
    genes.json                 gene order of the expression rows for this sample
    expr.zarr/                 Zarr v3 group
      u8      uint8   (nGenes, nObs)  chunk (1, nObs), shard (shardGenes, nObs), zstd
      gmax    float32 (nGenes)        value = gmin + u8 / 255 * (gmax - gmin)
      gmin    float32 (nGenes)        0 for non-negative features; -gmax for features with negative values (quantized symmetrically, zero at the centre)
      f16     float16 (nGenes, nObs)  optional; not read by the viewer
    obs.zarr/                  Zarr v3 group
      xy      float32 (nObs, 2)       microns, sample-local, y down, origin at bbox min
      order   uint32  (nObs)          source row of each bundle row (rows are shuffled once)
      cat/<fieldId>  uint16 (nObs)    codes into manifest.vocabularies[field.vocabulary].categories
      num/<fieldId>  float32 (nObs)
    ids/<block>.json           obs names in blocks of idBlock (default 65536)
    outlines/<fieldId>.json    {bin, paths:[{c: code, p:[[x, y], ...]}]} µm polylines
    shapes.json                cell shape tile index: {version, grid (µm per unit, 0.1), tile (µm), origin [x, y] µm,
                               nx, ny, reach (µm), layout "packed"|"files", tiles: [[ix, iy, offset, bytes, rings, vertices]]}
    shapes.bin                 the tiles' zstd frames back to back, row-major (layout "packed", read with byte ranges);
    shapes/<ix>_<iy>.bin       or one file per tile (layout "files", from `build --no-shard`)
    segmentations/<id>/shapes.json, shapes.bin   another segmentation of the section, in the shape tile format; its rings are
                               numbered 0..n-1 (not cell rows); the manifest entry carries cells, vertices, tile, tiles, bytes, medianArea
    molecules.json             molecule tile index: {version, grid (µm per unit, 1/64), tile (µm), origin, nx, ny, genes
                               (names; a molecule's gene id indexes them), counts (per gene), count, flags ["assigned", "nucleus"],
                               layout, tiles: [[ix, iy, offset, bytes, molecules]]}
    molecules.bin              the tiles' zstd frames back to back, or molecules/<ix>_<iy>.bin
    <imageId>.ome.zarr/        OME-Zarr NGFF 0.4 (zarr v2), axes c,y,x, 512² chunks
    tracks/                    ATAC samples built with `tracks:` (manifest samples[].tracks: genome, bin, units, all?, by)
      all.bw                   every cell, binned (bigWig): built from fragments, or copied when `bigwigs.all` was given
      <field>/<label>.bw       one per category of each `tracks.by` field: insertions per million from fragments
                               (summed over runs before scaling), or exported bigWigs copied as they are
      peaks.bed, links.bedpe, chrom.sizes
      genes/index.json         gene names per chromosome (search); genes/<chrom>.json: [name, strand, start, end, exon starts, exon ends]
    thumbnail.png
```

### Cell shape tiles

A ring belongs to the tile holding its centroid and is never clipped; a reader widens its view by `reach`, the
largest distance from a ring's centroid to one of its vertices. One tile, after zstd, is little endian, with every
multi-byte stream split into byte planes (low byte first):

```
u32 rings, u32 vertices
row steps   u32[rings], 4 planes        bundle rows ascending; the first step is the first row itself
counts      u8[rings]                   vertices per ring, the closing vertex not repeated
start x, y  i16[rings] each, 2 planes   first vertex, grid units from the tile origin
step x, y   i16[vertices - rings] each, 2 planes   steps between consecutive vertices of a ring
```

The tile size is the largest of 1024, 512, 256, 128 or 64 µm whose densest tile holds at most 2,048 rings. Every
ring records its cell's bundle row, so the viewer colours shapes from the per-cell arrays it already holds.
`python/src/spatialscape/shapes.py` writes and decodes it; `app/src/data/shapeTiles.ts` is the viewer's decoder.

### Molecule tiles

Per sample, in the sample frame. The tile size is the largest of 512, 256, 128 or 64 µm whose densest tile holds at
most 50,000 molecules. One tile, after zstd, little endian, multi-byte streams split into byte planes:

```
u32 n, u32 runs
run gene    u16[runs], 2 planes    gene ids ascending (indexes molecules.json genes)
run count   u32[runs], 4 planes    molecules of that gene
dx, dy      i16[n] each, 2 planes  steps between consecutive molecules on the 1/64 µm grid, the first from the tile
                                   origin; within a gene the order is a Morton curve, so steps are short
flags       u8[n]                  bit 0 assigned to a cell, bit 1 overlaps the nucleus
```

About 3.5 bytes per molecule on Xenium data. `python/src/spatialscape/molecules.py` writes and decodes it;
`app/src/data/moleculeTiles.ts` is the viewer's decoder.

## Design notes

- **Gene-major uint8.** Coloring N cells by a gene needs N bytes. One inner chunk per gene means one range request per gene per sample; shards keep file counts small. Quantization to 8 bits is visually lossless; `gmax` restores the scale for tooltips and statistics.
- **Shuffled rows.** Any prefix of an array is a uniform random subsample, so the viewer draws the first k rows at overview zoom with no extra data.
- **Dataset-level vocabularies.** Codes are shared across samples and platforms; the same label has the same code and color everywhere.
- **Images carry their geometry in the manifest** (`pixelSize` µm per level-0 pixel, `translate` µm), independent of NGFF transforms. NGFF 0.4 / zarr v2 is used because that is what the image renderer reads.
- **Reserved**: `expr.kind: "csc"` is declared in the schema for a future sparse layout; the viewer only reads `u8` today.

## manifest.json

Field names are camelCase and mirrored one-to-one between the Python and TypeScript models.

```ts
type Manifest = {
  formatVersion: 1; id: string; name: string; description?: string;
  defaultGene?: string; defaultColor: {kind: "gene"|"field", gene?, field?};
  layout: {mode: "grid"|"strip", gutterFraction: number, order: string[]};
  colormaps: string[];
  vocabularies: Record<string, {categories: string[], colors: string[], aliases?: Record<string,string>}>;
  fields: Array<{id, name, type: "categorical", vocabulary} | {id, name, type: "continuous", range?, colormap?}>;
  featureGroups: Array<{id, name, units?, count}>;
  meta: Array<{id, name, levels: string[]}>;      // sample metadata keys the viewer can split the canvas by
  comparisons: Array<{id, name, description?, path, groups, units?, population?: {field, value}, split?, link?,
                      nGenes, nReplicates, nUnmatched, hasP, hasPadj, hasMean, hasPseudobulk}>;
  samples: Array<{
    id, name, platform, kind: "spatial"|"embedding", group?, meta?: Record<string, string>, nObs, nGenes,
    bbox: [minx, miny, maxx, maxy], toDataset: number[9], pointRadius,
    expr: {kind: "u8"|"csc", sharded, shardGenes}, hasF16, fields: string[],
    images: Array<{id, name, path, kind, pixelSize, translate, size: [h, w], channels?, defaultOpacity}>,
    outlines: string[], shapes?: {path, cells, vertices, tile, tiles, bytes},
    molecules?: {path, count, genes, tile, tiles, bytes},
    segmentations: Array<{id, name, path, cells, vertices, tile, tiles, bytes, medianArea}>, idBlock
    // polygons?: {path, cells, vertices, scale}: whole-sample polygons of bundles built before shape tiles (still drawn)
  }>;
};
```

## comparisons/

One folder per `comparisons:` entry, next to `samples/`:

```
comparisons/<id>/
  comparison.json     the manifest entry plus replicates: [{id, group, subject, samples: [sample ids]}],
                      the columns taken from each table, the source file names and the match counts
  results.json        {genes, effect, p, padj, mean, unmeasured}: column arrays in one order, rows sorted by
                      padj then p then |effect|; p / padj / mean are null when the table lacks them;
                      unmeasured lists the row indices of genes no sample measures
  pseudobulk.zarr     float32 (nGenes, nReplicates) in results order, zstd, chunked by 1024 genes;
                      only when a pseudobulk table was given
  build.json          fingerprint of the tables and settings (the incremental rule)
```

## Reading a bundle elsewhere

Python:

```python
import zarr, json
g = zarr.open_group("bundle/samples/xen_Br9280/expr.zarr", mode="r")
genes = json.load(open("bundle/samples/xen_Br9280/genes.json"))
gmax = g["gmax"][:]
penk = g["u8"][genes.index("PENK"), :] / 255 * gmax[genes.index("PENK")]
```

R (Rarr / pizzarr) reads the same arrays; `obs.zarr/order` maps rows back to the source object.

Each sample may carry `suggestedGene`, its most variable gene; `build` uses the first spatial sample's as the dataset `defaultGene` when `default_gene` is not set. The manifest may carry `thumbnailSample`, the sample drawn on `thumbnail.png`.

## Next to the bundle

`spatialscape build` writes `bundles/<id>` by default and keeps two things beside it that are not part of the bundle: `bundles/.cache/<id>/<key>/` holds R objects converted into AnnData files (one folder per conversion key, with an `index.json` describing the source), and nothing else. Upload `bundles/<id>` alone; `find_bundles` and `site build` ignore the cache because it has no `manifest.json`.
