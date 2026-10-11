# `spatialscape site build`

Write a folder you can upload to any static host.

From `site.yaml`: builds every dataset listed under `config:` whose data or yaml changed, copies the viewer into `OUT`, places every bundle at `OUT/<id>/` (or points at `data_url`), and writes `OUT/datasets.json` from the yaml and the bundles' manifests: names, descriptions, platforms, counts, thumbnails, paper links, tags and placeholder cards. From a folder of bundles: the same without any settings. Preview with `spatialscape serve OUT`.

## Usage

```bash
spatialscape site build <TARGET> [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `TARGET` | path | *required* | `site.yaml`, or a folder of built bundles for a gallery without any settings. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `-o`, `--out` | path | — | Site directory to write. Default: `site/` next to the target. |
| `--link` | flag | `off` | Symlink bundle folders into the site instead of copying them (local previews of large data). |

## Examples

**The gallery described in site.yaml (default output: site/ next to it)**

```bash
spatialscape site build site.yaml
```

**One dataset, no settings: viewer + bundles from a folder**

```bash
spatialscape site build bundles -o site
```

**Local preview of large bundles without copying them**

```bash
spatialscape site build site.yaml --link && spatialscape serve site
```

## See also

- [`spatialscape site init`](./site-init)
- [`spatialscape serve`](./serve)
- [`spatialscape build`](./build)
- Guide: [Publish your own site](/guide/publish)
