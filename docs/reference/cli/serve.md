# `spatialscape serve`

Open your bundles in the viewer locally: one origin for the app and the data.

Serves the viewer that ships with this package at `/`, a `datasets.json` generated from every bundle in the folder (so the landing gallery lists them all), and the bundles themselves with CORS and HTTP Range headers. A folder that already contains `index.html` (the output of `site build`) is served as-is. A development server, not meant for production traffic.

## Usage

```bash
spatialscape serve [DIRECTORY] [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `DIRECTORY` | path | `.` | Folder of bundles (each reachable at `/<folder-name>`), a single bundle, or a site written by `site build`. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--port` | int | `8787` | TCP port. |
| `--host` | text | `127.0.0.1` | Interface to bind. Use `0.0.0.0` to reach the server from other machines. |
| `--open` | flag | `off` | Open the viewer in the default browser once the server is up. |

## Examples

**Open everything under a folder in the viewer**

```bash
spatialscape serve bundles --open
```

**Reachable from another machine on the network**

```bash
spatialscape serve bundles --host 0.0.0.0 --port 8787
```

**Preview a site written by `site build`**

```bash
spatialscape serve site
```

## See also

- [`spatialscape site build`](./site-build)
- [`spatialscape validate`](./validate)
- Guide: [Getting started](/guide/getting-started)
