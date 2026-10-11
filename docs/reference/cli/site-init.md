# `spatialscape site init`

Write a starter `site.yaml` listing your datasets.

Only needed for a gallery of several datasets, a title and intro, a navigation bar, paper links, tags or "coming soon" cards; a single dataset can be served and published straight from its bundle. The optional settings are present as comments.

## Usage

```bash
spatialscape site init [ITEMS] [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `ITEMS` | path | — | Dataset yamls and/or built bundle folders to list. Default: every `*.yaml` next to the output that looks like a dataset yaml, plus `bundles/*` there. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `-o`, `--out` | path | `site.yaml` | Where to write the site yaml. |
| `--title` | text | — | Gallery title. |

## Examples

**List two datasets and start a gallery yaml**

```bash
spatialscape site init dlpfc.yaml amygdala.yaml --title "Our lab's spatial data"
```

**Pick up every dataset yaml and bundle in the current folder**

```bash
spatialscape site init
```

## See also

- [`spatialscape site build`](./site-build)
- Guide: [The gallery: site.yaml](/guide/registry)
