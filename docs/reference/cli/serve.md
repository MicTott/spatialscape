# `spatialscape serve`

Serve a directory for local viewing, with CORS and HTTP Range.

A development server: it sends the headers the viewer needs and answers byte-range requests, which the standard library server does not. Not intended for production traffic.

## Usage

```bash
spatialscape serve [DIRECTORY] [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `DIRECTORY` | path | `.` | Directory to serve; each bundle inside is reachable at `/<name>`. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--port` | int | `8787` | TCP port. |
| `--host` | text | `127.0.0.1` | Interface to bind. Use `0.0.0.0` to reach the server from other machines. |

## Examples

**Serve every bundle under a folder**

```bash
spatialscape serve bundles --port 8787
```

**Reachable from another machine on the network**

```bash
spatialscape serve bundles --host 0.0.0.0 --port 8787
```

## See also

- [`spatialscape validate`](./validate)
- Guide: [Getting started](/guide/getting-started)
