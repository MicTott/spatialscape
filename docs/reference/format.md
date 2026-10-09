# Bundle format

`formatVersion: 1`. A bundle is a directory of static files; everything is addressable by URL with plain `GET` and `Range` requests.

```
<dataset>/
  manifest.json                dataset description (python: manifest.py, app: data/manifest.ts)
  genes.json                   sorted union of plain gene symbols (autocomplete)
  features.json                {genes, groups:[{id, name, units, features:[{id, label}]}]}
  thumbnail.png                one section colored by the default annotation
  build-info.json
  samples/<sampleId>/
    genes.json                 gene order of the expression rows for this sample
    expr.zarr/                 Zarr v3 group
      u8      uint8   (nGenes, nObs)  chunk (1, nObs), shard (shardGenes, nObs), zstd
      gmax    float32 (nGenes)        value = u8 / 255 * gmax[gene]
      f16     float16 (nGenes, nObs)  optional; not read by the viewer
    obs.zarr/                  Zarr v3 group
      xy      float32 (nObs, 2)       microns, sample-local, y down, origin at bbox min
      order   uint32  (nObs)          source row of each bundle row (rows are shuffled once)
      cat/<fieldId>  uint16 (nObs)    codes into manifest.vocabularies[field.vocabulary].categories
      num/<fieldId>  float32 (nObs)
    ids/<block>.json           obs names in blocks of idBlock (default 65536)
    outlines/<fieldId>.json    {bin, paths:[{c: code, p:[[x, y], ...]}]} µm polylines
    polygons.offsets.u32       uint32[nObs+1] vertex start per cell
    polygons.i16               int16 (dx, dy) × 10 deltas from the cell centroid
    <imageId>.ome.zarr/        OME-Zarr NGFF 0.4 (zarr v2), axes c,y,x, 512² chunks
    thumbnail.png
```

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
  samples: Array<{
    id, name, platform, kind: "spatial"|"embedding", group?, nObs, nGenes,
    bbox: [minx, miny, maxx, maxy], toDataset: number[9], pointRadius,
    expr: {kind: "u8"|"csc", sharded, shardGenes}, hasF16, fields: string[],
    images: Array<{id, name, path, kind, pixelSize, translate, size: [h, w], channels?, defaultOpacity}>,
    outlines: string[], polygons?: {path, cells, vertices, scale}, idBlock
  }>;
};
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

Each sample may carry `suggestedGene`, its most variable gene; `build` uses the first spatial sample's as the dataset `defaultGene` when `default_gene` is not set.
