# `spatialscape validate`

Check a bundle on disk or over HTTP: the conformance check for the bundle format.

Locally: the manifest parses, every array has the shape, dtype and gene-major chunking the format states, categorical codes fit their vocabularies, the row store and the zero-gene list match their manifest entries, shape and molecule tile indices decode, id blocks and images are consistent. For a URL: the manifest is fetched with CORS headers present, and one expression chunk is requested with a `Range` header expecting `206 Partial Content`. Exits with status 1 when problems are found. `build` runs the same checks at its end.

## Usage

```bash
spatialscape validate <TARGET>
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `TARGET` | text | *required* | A bundle directory, or the `http(s)://` URL of a hosted bundle. |

## Examples

**Before upload**

```bash
spatialscape validate bundles/dlpfc
```

**After upload**

```bash
spatialscape validate https://data.example.org/dlpfc
```

## See also

- [`spatialscape build`](./build)
- [`spatialscape serve`](./serve)
- Guide: [Hosting](/guide/hosting)
