# `spatialscape plan`

Show the expanded sample list without building anything.

Globs are expanded, templates filled, and `defaults` / `platforms` blocks merged exactly as `build` would do it. Use it to check ids, platforms and paths before a long build. No data files are read.

## Usage

```bash
spatialscape plan <CONFIG>
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `CONFIG` | path | *required* | Path to `dataset.yaml`. Relative paths inside it resolve against its own folder. |

## Examples

**Check what a build would do**

```bash
spatialscape plan dataset.yaml
```

## See also

- [`spatialscape init`](./init)
- [`spatialscape build`](./build)
- Guide: [Writing dataset.yaml](/guide/dataset-yaml)
