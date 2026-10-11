# The gallery: site.yaml

`site.yaml` describes the landing gallery and the chrome around the viewer: a title and intro, the datasets
and their cards, an optional navigation bar, and where the bundles are hosted. `spatialscape site build
site.yaml` turns it into `datasets.json` next to the viewer's `index.html`, which is what the gallery reads.
You edit the yaml; the JSON is a build output.

```yaml
title: LIBD spatial data browser
intro: Published spatial transcriptomics and snRNA-seq datasets, viewable in the browser.
nav:
  title: spatialscape
  logo: logo.svg
  links:
    - { label: Docs, url: https://mictott.github.io/spatialscape/docs/ }
    - { label: GitHub, url: https://github.com/MicTott/spatialscape }
# data_url: https://data.example.org          # bundles live there at <data_url>/<id>; the site carries only the viewer
datasets:
  - config: amygdala.yaml                      # a dataset yaml: built into bundles/amygdala next to it when needed
    paper: { title: Totty et al., url: https://doi.org/... }
    tags: [amygdala, visium, xenium]
  - bundle: ../dlpfc/bundles/dlpfc             # an already built bundle
    description: Thirty sections across ten donors.   # replaces the manifest's description on the card
  - id: hippocampus                            # a placeholder card
    name: Human hippocampus
    description: Coming later this year.
    platforms: [visium, snrnaseq]
```

`spatialscape site init` writes this file for the yamls and bundles you name, or for every dataset yaml and
`bundles/*` folder next to it when you name none.

## Dataset cards

Each entry is exactly one of `config:` (a dataset yaml), `bundle:` (a built bundle) or `id:` (a placeholder,
which also needs `name:`). Everything the gallery shows comes from the bundle's manifest (name,
description, platforms, sample and cell counts, gene count, thumbnail); these keys add to or replace it.

| Key | Meaning |
|---|---|
| `name`, `description` | card text; default: the dataset's own |
| `paper` | `{ title, url }` shown under the description |
| `tags` | short labels |
| `status` | `live`, `local` or `coming soon` (the badge); default `live`, placeholders `coming soon` |
| `accent` | color of the generated card art when there is no thumbnail |
| `thumbnail` | image URL; default `<bundle>/thumbnail.png`, which `build` renders |
| `platforms` | placeholders only; bundles report their own |

## The navigation bar

When `nav` is present, a slim bar appears above the viewer and the gallery: its title links to the gallery,
a dataset switcher lists every card that has a bundle, and `links` are rendered on the right. Without
`nav` the viewer has no chrome above the map, which is right for embedding it in another page.

## What the viewer reads

`datasets.json` is plain JSON: `title`, `intro`, `site` (the `nav` block) and `datasets`, one object per
card with `id`, `name`, `description`, `platforms`, `samples`, `cells`, `genes`, `url` (empty for
placeholders), `status`, `thumbnail`, `paper`, `tags` and `accent`. `?d=<id>` opens a card by id and
`?d=<url>` opens any bundle anywhere.

`spatialscape serve <folder>` generates the same document on the fly for a folder of bundles, and
`spatialscape site build <folder>` writes it without any settings, which is all a single dataset needs. If
you keep publication metadata elsewhere, generate `site.yaml` from it so a dataset is entered once.
