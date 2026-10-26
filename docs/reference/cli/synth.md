# `spatialscape synth`

Write a tiny synthetic dataset for tests and demos.

Produces two fake tissue sections (one log-normalized, one as counts with a flip and rotation), PNG images, cell polygons, an embedding sample, and a `dataset.yaml` that ties them together. `--comparisons` adds two more sections and sample metadata (a control and a stress group), the input for comparing groups side by side.

## Usage

```bash
spatialscape synth <OUT> [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `OUT` | path | *required* | Directory for the generated inputs. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--cells` | int | `2000` | Cells in the first synthetic section (the second has 40% more). |
| `--genes` | int | `50` | Number of synthetic genes. |
| `--comparisons` | flag | `off` | Two experimental groups: four sections with sample metadata (`condition` control / stress, one `mouse` each), a differential expression table with three planted genes, the per-mouse pseudobulk and a replicate sheet, and the `comparisons:` entry that ties them together. |

## Examples

**Make inputs, build them, serve them**

```bash
spatialscape synth demo-src && spatialscape build demo-src/dataset.yaml && spatialscape serve demo-src/bundles --open
```

## See also

- [`spatialscape build`](./build)
- Guide: [Getting started](/guide/getting-started#try-the-full-path-in-two-minutes)
