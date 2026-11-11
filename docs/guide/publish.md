# Publish your own site

This guide builds a viewer and dataset gallery from saved data, then publishes them on a static host.
You will need the input data, a reviewed dataset configuration and access to the host. The Python package
includes the viewer; publishing does not require editing its source code.

## 1. Install

```bash
python -m venv .venv && source .venv/bin/activate   # or conda, uv, pipx
pip install spatialscape
spatialscape --version
```

With the package and input files installed locally, you can build and preview a site offline. Remote inputs, reference downloads and deployment require network access.

## 2. Describe and build each dataset

Work inside your project folder:

```bash
mkdir -p spatialscape && cd spatialscape
spatialscape init ../analysis/spe_dlpfc.rds --id dlpfc --name "Human DLPFC"   # writes ./dlpfc.yaml for review
# edit dlpfc.yaml: keep the annotations you want, name them, pick colors and the opening gene
spatialscape build dlpfc.yaml                                                 # -> bundles/dlpfc; validates itself, renders thumbnails
```

If the site is going to GitHub Pages, put `sharded: false` at the top of each dataset yaml before the first
build (Pages does not guarantee the Range requests sharded bundles need); `build` and `site build` then keep
every rebuild unsharded.

`init` reads the object once and writes a yaml in which the likely annotations are already mapped and
every other column is a comment, so most edits are deleting or uncommenting a line; see
[Writing dataset.yaml](./dataset-yaml). Repeat for every dataset; each becomes a folder under `bundles/`.
Rerun `build` after an edit to the dataset configuration. It rebuilds affected samples and updates the dataset metadata.

## 3. Look at it

```bash
spatialscape serve bundles --open
```

The local server serves the viewer, gallery and data from the same address. Check the annotations, images
and gene colors before uploading. Links copied from this preview point to `127.0.0.1` and are local to the
computer running the server.

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

`site/` is a plain folder. Which host depends on the size of the bundles (`du -sh site`).

### Under 1 GB: GitHub Pages, start to finish

Use this route when the complete site fits within the hosting limits. The bundles must be unsharded (`sharded: false` in each
dataset yaml, see step 2). The site goes on its own branch of any repository, so your analysis repository can
host it without mixing the two:

```bash
cd site
git init -b gh-pages && git add -A && git commit -m "spatialscape site"
git remote add origin git@github.com:YOURORG/YOURREPO.git
git push -u origin gh-pages
```

Then, once, on GitHub: *Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch:
`gh-pages`, folder `/ (root)`*. After the deployment completes, the site is at `https://YOURORG.github.io/YOURREPO/`; open it
and run `spatialscape validate https://YOURORG.github.io/YOURREPO/dlpfc`. `site build` writes a `.nojekyll`
file, so Pages serves the folder as is. To update: rebuild, then in `site/` commit and push again.

Cloudflare Pages, Netlify and other static hosts can also serve the output folder. Check the host's current
file-size and file-count limits, and verify HTTP Range support before uploading sharded bundles.
See [Hosting](./hosting) for the required headers and validation command.

### Larger data: the site on Pages, the bundles on object storage

Keep the site small and put each bundle on a bucket, one bundle folder at a time (never `bundles/` itself:
its `.cache/` sibling holds the converted R objects and is not meant to travel):

```bash
rclone copy bundles/dlpfc r2:my-bucket/dlpfc     # or aws s3 sync bundles/dlpfc s3://my-bucket/dlpfc
spatialscape validate https://data.example.org/dlpfc
```

Then add `data_url: https://data.example.org` to `site.yaml` and run `site build` again: the site carries
only the viewer and the gallery's `datasets.json` (about 5 MB) and the data streams from the bucket.
[Hosting](./hosting) has the CORS policy each host needs, a copy-and-paste S3 + CloudFront setup, and what
`validate` checks.

## 6. Share a view or export an image

View settings are stored in the URL. `copy link` in the viewer header gives a link that reopens the same gene,
annotation, filters, camera and split. A link copied from `spatialscape serve` points at `127.0.0.1` and
only opens on your computer (the button says so); links from the published site are the ones to send. `PNG`
exports the frame with its legend for slides.

## Changing things afterwards

[Making changes](./changes) lists, for every common edit, the yaml line and the command that applies it.

## Updating later

- Anything in a dataset yaml or its source files: `spatialscape build <yaml>` (or `site build site.yaml`, which runs it for every listed dataset), then upload the bundle.
- A new dataset: `init` it, add a `config:` line to `site.yaml`, `site build`, upload.
