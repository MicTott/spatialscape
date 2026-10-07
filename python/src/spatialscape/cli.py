"""spatialscape command line.

Every command is also available as ``sscape <command>``. Help strings here are the source for the
generated CLI reference (``python/scripts/gen_cli_docs.py``), so keep them complete.
"""
from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(
    help="Build, check and serve static spatialscape viewer bundles.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

CONFIG_ARG = typer.Argument(..., help="Path to `dataset.yaml`. Relative paths inside it resolve against its own folder.", show_default=False)
OUT_OPT = typer.Option(..., "-o", "--out", help="Bundle directory to write (created if missing).", show_default=False)


@app.command()
def init(
    paths: list[str] = typer.Argument(..., help="One or more globs or paths of sample files, e.g. `'data/xenium/*/adata.zarr'`. Quote globs so the shell does not expand them.", show_default=False),
    out: Path = typer.Option("dataset.yaml", "-o", "--out", help="Where to write the starter config."),
    platform: str = typer.Option("xenium", "--platform", help="Platform assigned to every matched sample: `visium`, `visium_hd`, `xenium`, `merfish`, `snrnaseq` or `other`."),
    dataset_id: str = typer.Option("my_dataset", "--id", help="Dataset id (used in `?d=<id>` and bundle names)."),
    name: str = typer.Option("My dataset", "--name", help="Human-readable dataset name."),
):
    """Write a starter `dataset.yaml`.

    Creates one `glob:` entry per pattern with templated ids (`<platform>_{name}`), and a platform block with
    `fields: auto` and `images: auto`, so the first build needs no hand-written mapping. Review the result with
    `plan`, then edit field names, palettes and scale factors as needed.
    """
    import yaml

    doc = {
        "id": dataset_id,
        "name": name,
        "layout": {"mode": "grid"},
        "platforms": {platform: {"fields": "auto", "images": "auto"}},
        "samples": [
            {"glob": p, "platform": platform, "id": f"{platform[:3]}_{{name}}", "name": f"{{name}} ({platform})", "group": "{name}"} for p in paths
        ],
    }
    out.write_text(yaml.safe_dump(doc, sort_keys=False, width=200))
    typer.echo(f"wrote {out}; next: `spatialscape plan {out}` then `spatialscape build {out} -o bundle`")


@app.command()
def plan(config: Path = CONFIG_ARG):
    """Show the expanded sample list without building anything.

    Globs are expanded, templates filled, and `defaults` / `platforms` blocks merged exactly as `build` would do
    it. Use it to check ids, platforms and paths before a long build. No data files are read.
    """
    from .config import load_config

    cfg = load_config(config)
    typer.echo(f"{cfg.id}: {len(cfg.samples)} samples")
    for s in cfg.samples:
        fields = "auto" if s.fields == "auto" else f"{len(s.fields)} fields"
        images = "auto" if s.images == "auto" else f"{len(s.images)} image(s)"
        typer.echo(f"  {s.id:<22} {s.platform:<10} {s.kind:<9} {fields:<10} {images:<10} {s.path}")


@app.command()
def inspect(
    path: Path = typer.Argument(..., help="An `.h5ad` file, an AnnData Zarr store, or a SpatialData Zarr store.", show_default=False),
    table: str | None = typer.Option(None, "--table", help="Table key inside a SpatialData store (required when the store has more than one)."),
):
    """Print what a sample file contains, to help write `dataset.yaml`.

    Lists every `obs` column with its type and number of levels (with example values for categoricals),
    the `obsm` keys and their shapes, the layers, and any `uns` keys that look like scale information.
    """
    import numpy as np

    from .readers import read_anndata

    a = read_anndata(path, table)
    typer.echo(f"{path}: {a.n_obs} obs x {a.n_vars} vars")
    typer.echo("obs columns:")
    for c in a.obs.columns:
        s = a.obs[c]
        if isinstance(s.dtype, object) and str(s.dtype) in ("category", "object", "string", "bool"):
            n = s.nunique(dropna=True)
            ex = list(map(str, s.dropna().unique()[:6]))
            typer.echo(f"  {c:<40} categorical  {n:>5} levels  e.g. {ex}")
        else:
            v = s.to_numpy()
            typer.echo(f"  {c:<40} numeric     range {np.nanmin(v):.3g}..{np.nanmax(v):.3g}")
    typer.echo("obsm: " + ", ".join(f"{k}{tuple(np.asarray(a.obsm[k]).shape)}" for k in a.obsm))
    typer.echo("layers: " + ", ".join(a.layers.keys()))
    hints = [k for k in a.uns if any(t in k.lower() for t in ("scale", "spacing", "unit", "spatial", "pixel"))]
    typer.echo("uns scale hints: " + ", ".join(hints))
    for k in hints:
        v = a.uns[k]
        if not isinstance(v, dict):
            typer.echo(f"  {k} = {v}")


@app.command()
def build(
    config: Path = CONFIG_ARG,
    out: Path = OUT_OPT,
    no_shard: bool = typer.Option(False, "--no-shard", help="Write one file per gene instead of sharded Zarr. Larger file counts, but works on hosts without HTTP Range support (e.g. GitHub Pages)."),
    quiet: bool = typer.Option(False, "-q", "--quiet", help="Suppress per-sample progress output."),
):
    """Build a complete bundle from `dataset.yaml`.

    For every sample: read the object, resolve automatic fields and images, quantize and shard the expression
    matrix, convert coordinates to microns, write observation arrays and ids, pack polygons, convert images,
    and trace annotation outlines. Then write the dataset-level files, render thumbnails and run the same
    checks as `validate`. Exits with status 1 if validation reports problems.
    """
    from .build import build_dataset
    from .config import load_config
    from .validate import validate_local

    cfg = load_config(config)
    log = (lambda *_: None) if quiet else typer.echo
    m = build_dataset(cfg, out, sharded=not no_shard, log=log)
    try:
        from .thumbnail import write_thumbnails

        write_thumbnails(out, hero_id=cfg.thumbnail_sample, log=log)
    except Exception as e:
        typer.secho(f"  thumbnails skipped: {e}", fg="yellow")
    problems = validate_local(out)
    for p in problems:
        typer.secho(f"  ! {p}", fg="red")
    typer.echo(f"built {out} : {len(m.samples)} samples, {sum(s.nObs for s in m.samples)} obs")
    raise typer.Exit(1 if problems else 0)


@app.command("add-sample")
def add_sample_cmd(
    config: Path = CONFIG_ARG,
    out: Path = OUT_OPT,
    sample: str = typer.Option(..., "--sample", help="Id of the sample to (re)build, as listed by `plan`.", show_default=False),
    no_shard: bool = typer.Option(False, "--no-shard", help="Write one file per gene instead of sharded Zarr."),
    allow_vocab_append: bool = typer.Option(True, "--allow-vocab-append/--no-allow-vocab-append", help="Allow category labels not yet in the dataset vocabulary. They are appended, so existing codes never change; with `--no-allow-vocab-append` a new label is an error."),
):
    """Rebuild one sample inside an existing bundle.

    Reads the sample's entry from `dataset.yaml`, rebuilds only that sample folder, and refreshes
    `manifest.json`, `genes.json` and `features.json`. Other samples are untouched.
    """
    from .build import add_sample
    from .config import load_config

    add_sample(load_config(config), out, sample, sharded=not no_shard, allow_vocab_append=allow_vocab_append)
    typer.echo(f"updated {out} with sample {sample}")


@app.command()
def refresh(config: Path = CONFIG_ARG, out: Path = OUT_OPT):
    """Rewrite the dataset-level files without rebuilding any sample.

    Use after changing field display names, the palette, feature groups, layout order or `thumbnail_sample`.
    Reads each sample's existing `genes.json` and the current manifest, then rewrites `manifest.json`,
    `genes.json` and `features.json`.
    """
    from .build import refresh as _refresh
    from .config import load_config

    m = _refresh(load_config(config), out)
    typer.echo(f"refreshed {out}: {len(m.samples)} samples, groups: {[g.id for g in m.featureGroups]}")


@app.command()
def outlines(
    config: Path = CONFIG_ARG,
    out: Path = OUT_OPT,
    sample: list[str] = typer.Option(None, "--sample", help="Only these sample ids (repeatable). Default: every spatial sample."),
    field: list[str] = typer.Option(None, "--field", help="Only these categorical field ids (repeatable). Default: every categorical field the sample carries."),
    smooth_um: float = typer.Option(150.0, "--smooth-um", help="Side of the majority-vote smoothing window, in microns. Larger values merge small islands into their neighbours."),
    min_feature_um: float = typer.Option(300.0, "--min-feature-um", help="Islands and holes smaller than this (per side, in microns) are removed before tracing."),
):
    """Trace annotation boundaries from the arrays already in a bundle.

    Labels are rasterized at half the cell spacing, majority-smoothed, cleaned of small features, traced with
    marching squares and simplified. Cells labelled `NA` are treated as unknown and filled by their neighbours.
    Results go to `samples/<id>/outlines/<field>.json` and the manifest. No source data is needed, so this is
    cheap to re-run while tuning the two size parameters.
    """
    from .build import add_outlines
    from .config import load_config

    m = add_outlines(load_config(config), out, sample_ids=sample or None, fields=field or None, smooth_um=smooth_um, min_feature_um=min_feature_um)
    typer.echo(f"outlines written: {[(s.id, s.outlines) for s in m.samples if s.outlines]}")


@app.command()
def thumbnails(
    out: Path = typer.Argument(..., help="Bundle directory.", show_default=False),
    hero: str | None = typer.Option(None, "--hero", help="Sample shown on the dataset thumbnail. Default: `thumbnail_sample` from the build, else the first spatial sample in layout order."),
    no_per_sample: bool = typer.Option(False, "--no-per-sample", help="Skip the per-sample thumbnails."),
):
    """Render `thumbnail.png` for the dataset and for each sample.

    One section is drawn from the bundle's own coordinates, colored by the default annotation
    (or the first categorical field the sample carries). `build` runs this automatically.
    """
    from .thumbnail import write_thumbnails

    paths = write_thumbnails(out, per_sample=not no_per_sample, hero_id=hero, log=typer.echo)
    typer.echo(f"wrote {len(paths)} thumbnail(s)")


@app.command()
def validate(target: str = typer.Argument(..., help="A bundle directory, or the `http(s)://` URL of a hosted bundle.", show_default=False)):
    """Check a bundle on disk or over HTTP.

    Locally: the manifest parses, every array has the expected shape and gene-major chunking, categorical
    codes fit their vocabularies, id blocks, polygon files and images are consistent. For a URL: the manifest
    is fetched with CORS headers present, and one expression chunk is requested with a `Range` header expecting
    `206 Partial Content`. Exits with status 1 when problems are found.
    """
    from .validate import validate as _validate

    problems = _validate(target)
    for p in problems:
        typer.secho(f"  ! {p}", fg="red")
    if problems:
        raise typer.Exit(1)
    typer.secho("ok", fg="green")


@app.command()
def serve(
    directory: Path = typer.Argument(".", help="Directory to serve; each bundle inside is reachable at `/<name>`."),
    port: int = typer.Option(8787, "--port", help="TCP port."),
    host: str = typer.Option("127.0.0.1", "--host", help="Interface to bind. Use `0.0.0.0` to reach the server from other machines."),
):
    """Serve a directory for local viewing, with CORS and HTTP Range.

    A development server: it sends the headers the viewer needs and answers byte-range requests, which the
    standard library server does not. Not intended for production traffic.
    """
    from .serve import serve as _serve

    _serve(directory.resolve(), port=port, host=host)


@app.command()
def synth(
    out: Path = typer.Argument(..., help="Directory for the generated inputs.", show_default=False),
    cells: int = typer.Option(2000, "--cells", help="Cells in the first synthetic section (the second has 40% more)."),
    genes: int = typer.Option(50, "--genes", help="Number of synthetic genes."),
):
    """Write a tiny synthetic dataset for tests and demos.

    Produces two fake tissue sections (one log-normalized, one as counts with a flip and rotation), PNG images,
    cell polygons, an embedding sample, and a `dataset.yaml` that ties them together.
    """
    from .synthetic import make_synthetic

    typer.echo(f"wrote {make_synthetic(out, cells, genes)}")


if __name__ == "__main__":
    app()
