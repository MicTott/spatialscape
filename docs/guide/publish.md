# Publish your own site

This is the whole path from a saved object to a public URL with a landing gallery, without Node, without a
server, and without touching the viewer's source. Ten minutes the first time.

## 1. Install

```bash
python -m venv .venv && source .venv/bin/activate   # or conda, uv, pipx
pip install spatialscape
spatialscape --version
```

The package includes the viewer, so everything below runs offline.

## 2. Describe and build each dataset

Work inside your project folder:

```bash
spatialscape init analysis/spe_dlpfc.rds --id dlpfc --name "Human DLPFC"   # writes dlpfc.yaml, a menu of the data
# edit dlpfc.yaml: keep the annotations you want, name them, pick colors and the opening gene
spatialscape build dlpfc.yaml                                              # -> bundles/dlpfc; validates itself, renders thumbnails
```

`init` reads the object once and writes a yaml in which the likely annotations are already mapped and
every other column is a comment, so most edits are deleting or uncommenting a line; see
[Writing dataset.yaml](./dataset-yaml). Repeat for every dataset; each becomes a folder under `bundles/`.
`build` is the one command to rerun after any edit, and it only redoes what the edit requires.

## 3. Look at it

```bash
spatialscape serve bundles --open
```

One origin serves the viewer, a gallery of everything in `bundles/`, and the data. Double-click a section,
switch genes, lasso a region. Share nothing yet: this is your machine.

## 4. Describe the gallery

A single dataset needs no more than `spatialscape site build bundles -o site`. For a gallery with a title,
several datasets, paper links or "coming soon" cards, describe it in `site.yaml`:

```bash
spatialscape site init dlpfc.yaml other.yaml --title "Our lab's spatial data"
```

```yaml
title: Our lab's spatial data
intro: Published datasets, viewable in the browser without any installation.
nav: { title: Our lab, links: [{ label: Lab site, url: https://lab.example.org }] }
datasets:
  - config: dlpfc.yaml                        # built into bundles/dlpfc when its data or yaml changed
    paper: { title: Someone et al. 2026, url: https://doi.org/... }
    tags: [cortex]
  - config: other.yaml
  - id: hippocampus                           # a "coming soon" card
    name: Human hippocampus
    platforms: [visium, snrnaseq]
```

```bash
spatialscape site build site.yaml           # -> site/: viewer, datasets.json, one folder per dataset
spatialscape serve site                     # same thing a visitor will see
```

`site build` builds any listed dataset whose data or yaml changed, then writes `datasets.json` from
`site.yaml` and the bundles' manifests (names, counts, platforms, thumbnails). Edit `site.yaml`, never
`datasets.json`. [The gallery: site.yaml](./registry) lists every key.

## 5. Deploy

Upload `site/` to any static host. Three that work without configuration for small and medium data:

- **GitHub Pages**: push `site/` to a repository with Pages enabled (build demo bundles with `--no-shard`,
  since Pages does not guarantee Range requests; keep total size under 1 GB).
- **Cloudflare Pages / Netlify**: drag the folder in, or connect the repository.
- **Any web server**: copy the folder into the document root.

For large data, keep the site small and host the bundles on object storage:

```bash
rclone copy bundles r2:my-bucket                 # or aws s3 sync bundles s3://my-bucket
spatialscape validate https://data.example.org/dlpfc
```

Then add `data_url: https://data.example.org` to `site.yaml` and run `site build` again: the site carries
only the viewer and the registry (about 5 MB) and the data streams from the bucket.
[Hosting](./hosting) has the CORS policy each host needs and what `validate` checks.

## 6. Share views, not screenshots

Every control writes to the URL. `copy link` in the viewer header gives a link that reopens the same gene,
annotation, filters, camera and split. `PNG` exports the frame with its legend for slides.

## Changing things afterwards

[Making changes](./changes) lists, for every common edit, the yaml line and the command that applies it.

## Updating later

- Anything in a dataset yaml or its source files: `spatialscape build <yaml>` (or `site build site.yaml`, which runs it for every listed dataset), then upload the bundle.
- A new dataset: `init` it, add a `config:` line to `site.yaml`, `site build`, upload.
