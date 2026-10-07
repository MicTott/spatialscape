# `spatialscape validate`

Check a bundle on disk or over HTTP.

Locally: the manifest parses, every array has the expected shape and gene-major chunking, categorical codes fit their vocabularies, id blocks, polygon files and images are consistent. For a URL: the manifest is fetched with CORS headers present, and one expression chunk is requested with a `Range` header expecting `206 Partial Content`. Exits with status 1 when problems are found.

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
spatialscape validate bundles/amygdala
```

**After upload**

```bash
spatialscape validate https://data.example.org/amygdala
```

## See also

- [`spatialscape build`](./build)
- [`spatialscape serve`](./serve)
- Guide: [Hosting](/guide/hosting)
