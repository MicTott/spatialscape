# `spatialscape synth`

Write a tiny synthetic dataset for tests and demos.

Produces two fake tissue sections (one log-normalized, one as counts with a flip and rotation), PNG images, cell polygons, an embedding sample, and a `dataset.yaml` that ties them together.

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

## Examples

**Make inputs, build them, serve them**

```bash
spatialscape synth demo-src && spatialscape build demo-src/dataset.yaml -o bundles/demo && spatialscape serve bundles
```

## See also

- [`spatialscape build`](./build)
- Guide: [Getting started](/guide/getting-started#try-it-with-synthetic-data)
