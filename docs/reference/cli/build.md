# `spatialscape build`

Build or update a bundle from the dataset yaml. Rerun it after any edit.

The first run converts R objects listed under `samples:` (kept in `bundles/.cache/<id>/` next to the bundle), builds every sample and writes the dataset-level files. Later runs rebuild only the samples whose source files, settings or field declarations changed (compared with `samples/<id>/build.json`), remove samples the yaml no longer lists, and always rewrite `manifest.json`, `genes.json`, `features.json` and the thumbnails, so renamed fields, palettes and defaults apply in seconds. Ends with the same checks as `validate`; exits with status 1 if they report problems.

## Usage

```bash
spatialscape build <CONFIG> [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `CONFIG` | path | *required* | Path to the dataset yaml. Relative paths inside it resolve against its own folder. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `-o`, `--out` | path | — | Bundle directory. Default: `bundles/<id>` next to the yaml. |
| `--dry-run` | flag | `off` | Show which samples would be built, kept or removed, and why; write nothing. |
| `--force` | flag | `off` | Rebuild every sample even when nothing changed. |
| `--no-shard` | flag | `off` | Write one file per gene instead of sharded Zarr. Larger file counts, but works on hosts without HTTP Range support (e.g. GitHub Pages). |
| `-q`, `--quiet` | flag | `off` | Suppress per-sample progress output. |

## Examples

**Build, or update after editing the yaml (default output: `bundles/<id>` next to it)**

```bash
spatialscape build dlpfc.yaml
```

**See what would be rebuilt and why, without writing anything**

```bash
spatialscape build dlpfc.yaml --dry-run
```

**For GitHub Pages or other hosts without Range support**

```bash
spatialscape build dlpfc.yaml --no-shard
```

**Rebuild everything**

```bash
spatialscape build dlpfc.yaml --force
```

## See also

- [`spatialscape serve`](./serve)
- [`spatialscape validate`](./validate)
- [`spatialscape site build`](./site-build)
- Guide: [Building and validating](/guide/building)
