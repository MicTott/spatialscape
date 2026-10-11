# site.yaml schema

Validated by pydantic models in `python/src/spatialscape/site.py`. Unknown keys are errors. `config:` and
`bundle:` paths are resolved relative to the yaml. `spatialscape site init` writes a commented starter;
`spatialscape site build site.yaml` turns it into `datasets.json` (see [The gallery](../guide/registry)).

## Top level

| Key | Type | Default | Notes |
|---|---|---|---|
| `title` | string | `spatialscape` | gallery heading |
| `intro` | string | | one or two sentences under the title |
| `nav` | `{title, logo, links: [{label, url}]}` | | the bar above the viewer and gallery; omit for no chrome |
| `data_url` | URL | | bundles are hosted at `<data_url>/<id>`; nothing is copied into the site |
| `datasets` | list of cards | required | in gallery order |

## Cards

Exactly one of `config`, `bundle` or `id` per card.

| Key | Type | Notes |
|---|---|---|
| `config` | path | a dataset yaml; `site build` runs `build` on it (into `bundles/<id>` next to it) and places the result |
| `bundle` | path | an already built bundle directory |
| `id` | string | a placeholder card; needs `name` |
| `name` | string | card title; default: the dataset's name |
| `description` | string | card text; default: the dataset's description |
| `platforms` | list | placeholders only (`visium`, `visium_hd`, `xenium`, `merfish`, `snrnaseq`) |
| `status` | `live`, `local`, `coming soon` | badge; default `live`, placeholders `coming soon` |
| `paper` | `{title, url}` | |
| `tags` | list of strings | |
| `accent` | `#hex` | color of the generated art when there is no thumbnail |
| `thumbnail` | URL | default `<bundle>/thumbnail.png` |

## Output

`datasets.json` next to the viewer: `{ title, intro?, site?: nav, datasets: [...] }`, each dataset with
`id`, `name`, `description`, `platforms`, `samples`, `cells`, `genes`, `url`, `status` and the optional
keys above. Every key the viewer reads is always present, so a hand-written entry is never needed.
