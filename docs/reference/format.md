# Bundle format

`formatVersion: 1`. A bundle is a directory of static files; everything is addressable by URL with plain `GET` and `Range` requests.

## Stability

Format 1 is final. Everything this page lists, every file, array, shape, dtype, encoding and precision, keeps its
meaning: a bundle built today opens in every later viewer, and a reader written against this page keeps reading
bundles built later.

- **Changes within format 1 only add.** A new optional file or manifest key may appear; a reader ignores keys it
  does not know, and nothing listed here changes meaning. A change that would break a reader bumps `formatVersion`
  to 2, and the viewer refuses a version it does not know.
- **Required and optional.** Required: `manifest.json`, `genes.json`, `features.json`, and per sample `genes.json`,
  `expr.zarr/{u8, gmax, gmin}`, `obs.zarr/{xy, order, cat, num}` and `ids/`. Optional, each announced by its manifest
  entry: `rows.zarr`, `zero_genes.json`, `f16`, images, `shapes`, `segmentations/`, `molecules`, `tracks/`,
  `comparisons/`, `thumbnail.png`. `build.json` and `build-info.json` are build aids, not part of the format: a
  reader never needs them and an upload may leave them out. Bundles built before 0.6 have no row store and no
  zero-gene list and may carry whole-sample `polygons` files instead of shape tiles; the viewer still reads them.
- **Conformance.** `spatialscape validate <bundle | url>` checks a bundle against this page: shapes and dtypes,
  gene-major chunking, codes within their vocabularies, tile indices that decode, id blocks, the row store, the
  zero-gene list, images, and over HTTP the CORS and `Range` behaviour a static host must provide. `python -m
  spatialscape.fidelity` measures a bundle against the data it was built from, to the precision stated below.
- **Reference decoders.** `python/src/spatialscape/{expression, rows, obs, shapes, molecules}.py` write and read
  back every store; `app/src/data/{worker, rows, shapeTiles, moleculeTiles}.ts` are the viewer's readers. Where the
  two could disagree, the Python decoder is the specification.

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
    zero_genes.json            features the sample measured and found zero everywhere: part of its panel, not stored
                               (manifest samples[].nZeroGenes counts them; the viewer draws them as zero, a test counts their cells)
    expr.zarr/                 Zarr v3 group
      u8      uint8   (nGenes, nObs)  chunk (1, nObs), shard (shardGenes, nObs), zstd
      gmax    float32 (nGenes)        value = gmin + u8 / 255 * (gmax - gmin)
      gmin    float32 (nGenes)        0 for non-negative features; -gmax for features with negative values (quantized symmetrically, zero at the centre)
                                      precision: a value is within (gmax - gmin) / 510 of the source, except a positive value under
                                      half a step, stored as code 1 so an expressed cell never draws as zero; zeros are exact
                                      (checked by `python -m spatialscape.fidelity`, see benchmarks/)
      f16     float16 (nGenes, nObs)  optional; not read by the viewer
    rows.zarr/                 Zarr v3 group, optional (`expression.rows`): the same codes one cell at a time
      indptr  uint32  (nObs + 1)      stored values before each row of the store
      gene    uint16|uint32 (nnz)     kept-gene index (row of u8) of every stored value, as the step from the row's previous id (first absolute); chunk 2^20, shard 32 chunks
      value   uint8   (nnz)           the u8 code of that value; zeros are not stored
      pos     uint32  (nObs)          position in the store of bundle row i; rows follow a Morton curve over xy
    obs.zarr/                  Zarr v3 group
      xy      float32 (nObs, 2)       microns, sample-local, y down, origin at bbox min
      order   uint32  (nObs)          source row of each bundle row (rows are shuffled once)
      cat/<fieldId>  uint16 (nObs)    codes into manifest.vocabularies[field.vocabulary].categories
      num/<fieldId>  float32 (nObs)
    ids/<block>.json           obs names in blocks of idBlock (default 65536)
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
    <imageId>.ome.zarr/        OME-Zarr NGFF 0.4 (zarr v2), axes c,y,x, 512² chunks (an OME-Zarr source passed through
                               keeps its own axes and chunks)
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
- **Rows for tests on a selection.** A differential expression test on a lasso needs every gene of a few cells, the opposite access pattern, so a sample may carry the matrix a second time as sparse rows ordered along a space-filling curve: a compact region is a few contiguous runs of rows, fetched with a few range requests. It costs about as much as the gene-major store (on the amygdala sections 0.96×: the dense store's zeros compress well, and the codes themselves are most of the rows); `expression.rows: auto` writes it for tissue sections and not for embeddings.
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
  layout: {mode: "grid"|"strip", gutterFraction: number, order: string[], columns?: number};
  colormaps: string[];
  vocabularies: Record<string, {categories: string[], colors: string[], aliases?: Record<string,string>}>;
  fields: Array<{id, name, type: "categorical", vocabulary, description?}
              | {id, name, type: "continuous", range?, colormap?, description?}>;
  featureGroups: Array<{id, name, units?, count}>;
  thumbnailSample?: string;                       // the sample drawn on thumbnail.png
  meta: Array<{id, name, levels: string[]}>;      // sample metadata keys the viewer can split the canvas by
  comparisons: Array<{id, kind: "contrast"|"markers", name, description?, path, groups, contrast?, effect, units?,
                      population?: {field, value}, split?, link?, facet?: {column, field?},
                      levels: Array<{id, name, path, nGenes, nSignificant, nUnmatched, nReplicates, hasPseudobulk,
                                     population?: {field, value}}>,
                      nGenes, nReplicates, nUnmatched, nMatrixGenes,
                      hasEffect, hasP, hasPadj, hasMean, hasPct, hasScore, hasPseudobulk}>;
  samples: Array<{
    id, name, platform, kind: "spatial"|"embedding", group?, meta?: Record<string, string>, nObs, nGenes,
    bbox: [minx, miny, maxx, maxy], toDataset: number[9], pointRadius,
    expr: {kind: "u8"|"csc", sharded, shardGenes, normalized?: "lognorm"|"log1p_cp10k"|"raw"}, hasF16, fields: string[],
    images: Array<{id, name, path, kind, pixelSize, translate, size: [h, w], channels?: Array<{name, color, window}>, defaultOpacity}>,
    shapes?: {path, cells, vertices, tile, tiles, bytes, medianArea?},
    molecules?: {path, count, genes, tile, tiles, bytes},
    segmentations: Array<{id, name, path, cells, vertices, tile, tiles, bytes, medianArea?}>,
    rows?: {nnz, chunk, order: "morton"},           // rows.zarr
    tracks?: {genome, bin, units, all?, by: Array<{field, categories: Record<string, string>}>, peaks?, genes?, links?, chromSizes},
    nZeroGenes, suggestedGene?, idBlock
    // polygons?: {path, cells, vertices, scale}: whole-sample polygons of bundles built before shape tiles (still drawn)
  }>;
};
```

## comparisons/

One folder per `comparisons:` entry, next to `samples/`:

```
comparisons/<id>/
  comparison.json     the manifest entry (kind, groups, facet, levels[]) plus replicates per level:
                      {<level id>: [{id, group, subject, samples: [sample ids]}]}, the columns taken from each
                      table, the source file names and the match counts
  matrix.json         {genes, levels, stats, unmeasured}: the row order of matrix.zarr (every gene of every
                      level once), the level ids in column order, which statistics are present
  matrix.zarr/<stat>  float32 (genes, levels) per statistic (effect, padj, p, pct_in, pct_out, rank), NaN where
                      a level's table has no row for the gene; Blosc (zstd), chunked by 4096 genes, so the
                      panel's matrix is one fetch per statistic for most tables
  levels/<level>/     one folder per level: "all" for a comparison without a facet, else one per cluster or
                      cell type (the level's label made file-safe)
    results.json      {genes, effect, p, padj, mean, pct_in, pct_out, score, unmeasured}: column arrays in one
                      order, rows sorted by padj then p then |effect| (a ranked list without statistics keeps
                      its file order); arrays the table lacks are null; unmeasured lists the row indices of
                      genes no sample measures
    pseudobulk.zarr   float32 (nGenes, nReplicates) in results order, Blosc (zstd), chunked by 1024 genes; only when
                      a pseudobulk table was given for the level
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

`spatialscape build` writes `bundles/<id>` by default and keeps one thing beside it that is not part of the bundle: `bundles/.cache/<id>/<key>/` holds R objects converted into AnnData files (one folder per conversion key, with an `index.json` describing the source). Upload `bundles/<id>` alone; `find_bundles` and `site build` ignore the cache because it has no `manifest.json`.
