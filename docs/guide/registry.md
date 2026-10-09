# Registry and site bar

A `datasets.json` next to the app's `index.html` turns the viewer into a small portal: a landing gallery with thumbnails, short dataset ids in URLs, and an optional navigation bar.

```json
{
  "title": "LIBD spatial data browser",
  "intro": "Published spatial transcriptomics and snRNA-seq datasets, viewable in the browser.",
  "site": {
    "title": "spatialscape",
    "logo": "logo.svg",
    "links": [
      { "label": "Docs", "url": "https://mictott.github.io/spatialscape/docs/" },
      { "label": "GitHub", "url": "https://github.com/MicTott/spatialscape" }
    ]
  },
  "datasets": [
    {
      "id": "amygdala",
      "name": "Human amygdala",
      "description": "Visium, Visium HD and Xenium sections with spatial domains and cell types.",
      "platforms": ["visium", "xenium", "snrnaseq"],
      "samples": 12,
      "cells": 1185515,
      "genes": 34724,
      "url": "https://data.example.org/amygdala",
      "status": "live",
      "paper": { "title": "Totty et al.", "url": "https://doi.org/..." }
    }
  ]
}
```

## Dataset entries

| Key | Meaning |
|---|---|
| `id` | short name used in `?d=<id>` |
| `url` | bundle URL (absolute, or relative to the app); empty for "coming soon" entries |
| `thumbnail` | optional; defaults to `<url>/thumbnail.png`, which `spatialscape build` writes |
| `platforms`, `samples`, `cells`, `genes` | shown on the card |
| `status` | `live`, `local` or `coming soon` (badge) |
| `paper` | title and optional link |
| `accent` | color for the generated placeholder art when there is no thumbnail |

## The site bar

When `site` is present, a slim bar appears above the viewer and the gallery: the title links to the gallery, a dataset switcher lists every entry with a `url`, and `links` are rendered on the right. Without `site`, the viewer has no chrome above the map, which is right for embedding it in another page.

## Where the registry comes from

`spatialscape site build` writes it from the bundles' manifests and keeps whatever you add by hand (paper, tags, accent, status, a `site` block, placeholder entries). `spatialscape serve` generates the same thing on the fly for a folder of bundles. For an institute, generate the hand-written parts from the same source that produces your publications pages, so a dataset is entered once.
