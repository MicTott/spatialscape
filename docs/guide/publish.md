# Publish your own site

This is the whole path from a folder of exported samples to a public URL with a landing gallery, without
Node, without a server, and without touching the viewer's source. Ten minutes the first time.

## 1. Install

```bash
python -m venv .venv && source .venv/bin/activate   # or conda, uv, pipx
pip install spatialscape
spatialscape --version
```

The package includes the viewer, so everything below runs offline.

## 2. Describe and build each dataset

```bash
spatialscape init "data/visium/*/adata.h5ad" --platform visium --id dlpfc --name "Human DLPFC" -o dlpfc.yaml
spatialscape inspect data/visium/Br2743/adata.h5ad       # which obs columns and obsm keys exist
spatialscape plan dlpfc.yaml                            # ids and paths, nothing built
spatialscape build dlpfc.yaml -o bundles/dlpfc           # validates itself and renders thumbnails
```

Edit the yaml between `init` and `build` to name the annotations you want (`fields:`), map platforms
to the same field ids, and point `palette:` at your colors. See [Writing dataset.yaml](./dataset-yaml).
Repeat for every dataset; each one becomes a folder under `bundles/`.

## 3. Look at it

```bash
spatialscape serve bundles --open
```

One origin serves the viewer, a gallery of everything in `bundles/`, and the data. Double-click a section,
switch genes, lasso a region. Share nothing yet: this is your machine.

## 4. Assemble the site

```bash
spatialscape site build bundles/dlpfc bundles/other -o site --title "Our lab's spatial data"
spatialscape serve site        # same thing a visitor will see
```

`site/` now holds `index.html`, `assets/`, `datasets.json` and one folder per dataset. The registry was
written from the bundles' manifests. Open it and add what a manifest cannot know:

```json
{
  "title": "Our lab's spatial data",
  "intro": "Published datasets, viewable in the browser without any installation.",
  "site": { "title": "Our lab", "links": [{ "label": "Lab site", "url": "https://lab.example.org" }] },
  "datasets": [
    { "id": "dlpfc", "paper": { "title": "Someone et al. 2026", "url": "https://doi.org/..." }, "tags": ["cortex"] }
  ]
}
```

Only the keys you add are needed; counts, names and thumbnails are regenerated whenever you rerun
`site build`, and your additions are kept. Entries with an empty `url` show as *coming soon*.

## 5. Deploy

Upload `site/` to any static host. Three that work without configuration for small and medium data:

- **GitHub Pages**: push `site/` to a repository with Pages enabled (build demo bundles with `--no-shard`,
  since Pages does not guarantee Range requests; keep total size under 1 GB).
- **Cloudflare Pages / Netlify**: drag the folder in, or connect the repository.
- **Any web server**: copy the folder into the document root.

For large data, keep the viewer small and host the bundles on object storage:

```bash
rclone copy bundles r2:my-bucket                 # or aws s3 sync bundles s3://my-bucket
spatialscape validate https://data.example.org/dlpfc
spatialscape site build bundles/dlpfc -o site --data-url https://data.example.org
```

The site then carries only the viewer and the registry (about 5 MB); the data streams from the bucket.
[Hosting](./hosting) has the CORS policy each host needs and what `validate` checks.

## 6. Share views, not screenshots

Every control writes to the URL. `copy link` in the viewer header gives a link that reopens the same gene,
annotation, filters, camera and split. `PNG` exports the frame with its legend for slides.

## Updating later

- New dataset: `build` it, rerun `site build` with the full list, upload.
- Changed labels or colors: `spatialscape refresh dataset.yaml -o bundles/<id>`, then upload that bundle.
- One sample re-exported: `spatialscape add-sample dataset.yaml -o bundles/<id> --sample <sample>`.
