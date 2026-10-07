# CLI commands

The `spatialscape` command converts data into viewer bundles and checks them. Every command is also available as `sscape <command>`, and `spatialscape <command> --help` prints the same information as these pages.

```bash
pip install spatialscape
spatialscape --help
```

| Command | Purpose |
|---|---|
| [`init`](./init) | Write a starter `dataset.yaml`. |
| [`plan`](./plan) | Show the expanded sample list without building anything. |
| [`inspect`](./inspect) | Print what a sample file contains, to help write `dataset.yaml`. |
| [`build`](./build) | Build a complete bundle from `dataset.yaml`. |
| [`add-sample`](./add-sample) | Rebuild one sample inside an existing bundle. |
| [`refresh`](./refresh) | Rewrite the dataset-level files without rebuilding any sample. |
| [`outlines`](./outlines) | Trace annotation boundaries from the arrays already in a bundle. |
| [`thumbnails`](./thumbnails) | Render `thumbnail.png` for the dataset and for each sample. |
| [`validate`](./validate) | Check a bundle on disk or over HTTP. |
| [`serve`](./serve) | Serve a directory for local viewing, with CORS and HTTP Range. |
| [`synth`](./synth) | Write a tiny synthetic dataset for tests and demos. |

## Typical sequence

```bash
spatialscape init "data/*/adata.zarr" --platform xenium --id my_atlas -o dataset.yaml
spatialscape plan dataset.yaml
spatialscape build dataset.yaml -o bundles/my_atlas
spatialscape serve bundles --port 8787
# ... upload bundles/my_atlas ...
spatialscape validate https://data.example.org/my_atlas
```

## Exit codes

`build` and `validate` exit with status 1 when validation reports problems, so they can gate a deployment script. Every other command exits 0 on success and raises on error.

::: tip Generated reference
These pages are generated from the CLI's own help text by `python/scripts/gen_cli_docs.py`. If a page and `--help` ever disagree, `--help` is right and the generator needs re-running.
:::
