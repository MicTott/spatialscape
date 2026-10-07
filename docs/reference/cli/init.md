# `spatialscape init`

Write a starter `dataset.yaml`.

Creates one `glob:` entry per pattern with templated ids (`<platform>_{name}`), and a platform block with `fields: auto` and `images: auto`, so the first build needs no hand-written mapping. Review the result with `plan`, then edit field names, palettes and scale factors as needed.

## Usage

```bash
spatialscape init <PATHS>... [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `PATHS` | text | *required* | One or more globs or paths of sample files, e.g. `'data/xenium/*/adata.zarr'`. Quote globs so the shell does not expand them. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `-o`, `--out` | path | `dataset.yaml` | Where to write the starter config. |
| `--platform` | text | `xenium` | Platform assigned to every matched sample: `visium`, `visium_hd`, `xenium`, `merfish`, `snrnaseq` or `other`. |
| `--id` | text | `my_dataset` | Dataset id (used in `?d=<id>` and bundle names). |
| `--name` | text | `My dataset` | Human-readable dataset name. |

## Examples

**Xenium donors in sibling folders**

```bash
spatialscape init "xenium/*/adata.zarr" --platform xenium --id amygdala --name "Human amygdala" -o dataset.yaml
```

**Two patterns, one config**

```bash
spatialscape init "visium/*/outs" "xenium/*/adata.zarr" --platform visium -o dataset.yaml
```

## See also

- [`spatialscape plan`](./plan)
- [`spatialscape inspect`](./inspect)
- [`spatialscape build`](./build)
- Guide: [Writing dataset.yaml](/guide/dataset-yaml)
