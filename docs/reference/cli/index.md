# CLI commands

Four commands cover the normal path: `init` writes a dataset yaml from your data, `build` turns it into a bundle (and updates the bundle after every edit), `serve` opens it, `site build` writes the folder to publish. Every command is also available as `sscape <command>`, and `spatialscape <command> --help` prints the same information as these pages.

```bash
pip install spatialscape
spatialscape --help
```

| Command | Purpose |
|---|---|
| [`init`](./init) | Write a dataset yaml that doubles as a menu of what the data contains. |
| [`build`](./build) | Build or update a bundle from the dataset yaml. Rerun it after any edit. |
| [`serve`](./serve) | Open your bundles in the viewer locally: one origin for the app and the data. |
| [`site init`](./site-init) | Write a starter `site.yaml` listing your datasets. |
| [`site build`](./site-build) | Write a folder you can upload to any static host. |
| [`inspect`](./inspect) | Print what a sample file contains, to help edit the dataset yaml. |
| [`validate`](./validate) | Check a bundle on disk or over HTTP. |
| [`outlines`](./outlines) | Re-trace annotation boundaries from the arrays already in a bundle. |
| [`thumbnails`](./thumbnails) | Re-render `thumbnail.png` for the dataset and for each sample. |
| [`synth`](./synth) | Write a tiny synthetic dataset for tests and demos. |

## Typical sequence

```bash
spatialscape init analysis/spe_visium.rds --id my_atlas     # writes my_atlas.yaml, a menu of the data
# edit my_atlas.yaml: annotations, names, colors, the opening gene
spatialscape build my_atlas.yaml                            # -> bundles/my_atlas; rerun after any edit
spatialscape serve bundles --open
spatialscape site init my_atlas.yaml && spatialscape site build site.yaml   # only for a gallery with settings
# ... upload site/ (or the bundles alone) ...
spatialscape validate https://data.example.org/my_atlas
```

## Exit codes

`build` and `validate` exit with status 1 when validation reports problems, so they can gate a deployment script. Every other command exits 0 on success and prints a one-line error otherwise (`SPATIALSCAPE_DEBUG=1` shows the traceback).

::: tip Generated reference
These pages are generated from the CLI's own help text by `python/scripts/gen_cli_docs.py`. If a page and `--help` ever disagree, `--help` is right and the generator needs re-running.
:::
