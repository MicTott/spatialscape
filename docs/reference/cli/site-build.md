# `spatialscape site build`

Write a folder you can upload to any static host.

Copies the viewer into `OUT`, places every bundle at `OUT/<id>/` (or references `--data-url`), and writes `OUT/datasets.json` from the bundles' manifests: names, descriptions, platforms, counts and thumbnails. Edit that file afterwards for paper links, tags, a `site` navigation block or "coming soon" entries; rerunning keeps those edits. Preview with `spatialscape serve OUT`.

## Usage

```bash
spatialscape site build <BUNDLES>... [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `BUNDLES` | path | *required* | Bundle directories, or folders that contain bundles. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `-o`, `--out` | path | *required* | Site directory to write (created if missing; an existing `datasets.json` there is merged, not replaced). |
| `--data-url` | text | — | Bundles are hosted elsewhere at `<data-url>/<id>`: write the registry to point there and copy nothing. |
| `--link` | flag | `off` | Symlink bundle folders into the site instead of copying them (local previews of large data). |
| `--title` | text | — | Gallery title. |
| `--intro` | text | — | One or two sentences under the title. |

## Examples

**Viewer + bundles in one folder, ready to upload**

```bash
spatialscape site build bundles/my_atlas bundles/other -o site --title "Our lab's data"
```

**Bundles already on R2 / S3; the site only carries the viewer and the registry**

```bash
spatialscape site build bundles/my_atlas -o site --data-url https://data.example.org
```

**Local preview of large bundles without copying them**

```bash
spatialscape site build bundles/my_atlas -o site --link && spatialscape serve site
```

## See also

- [`spatialscape serve`](./serve)
- [`spatialscape build`](./build)
- Guide: [Publish your own site](/guide/publish)
