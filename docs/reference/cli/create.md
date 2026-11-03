# `spatialscape create`

Make a dataset from data on this machine, in the browser: pick an object or folder, see what it holds,
tick what to show, build, open.

The page is `init`, `build` and `serve` with buttons: it browses this machine's files by path (nothing is uploaded), writes the dataset yaml to PROJECT/<id>.yaml exactly as `init` would, builds into PROJECT/bundles/<id>, and lists the result in the gallery it serves. Edit the yaml and run `build` later to change the dataset; the page keeps no state of its own. On a cluster, run it on a compute node and forward the port, as you would for RStudio Server or Jupyter.

## Usage

```bash
spatialscape create [PROJECT] [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `PROJECT` | path | `.` | Project folder: the dataset yamls the page writes go here, the bundles into `bundles/` inside it. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--port` | int | — | TCP port. Default 8787, or the next free port when that one is busy. |
| `--host` | text | `127.0.0.1` | Interface to bind. |
| `--open`, `--no-open` | flag | `on` | Open the Create page in the default browser once the server is up. |

## Examples

**Make datasets in the browser from data on this machine; yamls and bundles go into the current folder**

```bash
spatialscape create
```

**A project folder of its own, on another port**

```bash
spatialscape create ~/spatialscape-projects --port 8790
```

**On a cluster: a compute node, then forward the port from your laptop**

```bash
srun --pty --mem=16G bash
spatialscape create /path/to/project --no-open
# on the laptop: ssh -L 8787:127.0.0.1:8787 user@that-node
```

## See also

- [`spatialscape init`](./init)
- [`spatialscape build`](./build)
- [`spatialscape serve`](./serve)
- Guide: [Getting started](/guide/getting-started#goal-2-your-own-data-on-your-machine)
