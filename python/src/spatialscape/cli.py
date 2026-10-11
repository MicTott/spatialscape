"""spatialscape command line.

Every command is also available as ``sscape <command>``. Help strings here are the source for the
generated CLI reference (``python/scripts/gen_cli_docs.py``), so keep them complete.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import typer

app = typer.Typer(
    help="Build, check and serve static spatialscape viewer bundles.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
    pretty_exceptions_enable=False,
)


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import version

        typer.echo(f"spatialscape {version('spatialscape')}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(False, "--version", "-V", help="Print the version and exit.", callback=_version_callback, is_eager=True),
) -> None:
    """Build, check and serve static spatialscape viewer bundles."""


CONFIG_ARG = typer.Argument(..., help="Path to the dataset yaml. Relative paths inside it resolve against its own folder.", show_default=False)
OUT_OPT = typer.Option(None, "-o", "--out", help="Bundle directory. Default: `bundles/<id>` next to the yaml.", show_default=False)


@app.command()
def init(
    paths: list[str] = typer.Argument(..., help="What to describe: R objects (`.rds` / `.rda` holding a SpatialExperiment or SingleCellExperiment) and/or globs of sample files such as `'data/*/adata.h5ad'` (quoted, so the shell does not expand them). One `samples:` entry per argument.", show_default=False),
    out: Path | None = typer.Option(None, "-o", "--out", help="Where to write the yaml. Default: `<id>.yaml` in the current folder.", show_default=False),
    dataset_id: str | None = typer.Option(None, "--id", help="Dataset id: used in `?d=<id>` and as the bundle folder name. Default: the object's file name, or the folder a glob starts in.", show_default=False),
    name: str | None = typer.Option(None, "--name", help="Human-readable dataset name. Default: the id, prettified.", show_default=False),
    platform: str | None = typer.Option(None, "--platform", help="Platform of the spatial samples: `visium`, `visium_hd`, `xenium`, `merfish` or `other`. Default: `visium`. Objects and files without spatial coordinates become `snrnaseq` embeddings regardless.", show_default=False),
    table: str | None = typer.Option(None, "--table", help="Table key inside a SpatialData store.", show_default=False),
):
    """Write a dataset yaml that doubles as a menu of what the data contains.

    The yaml gets one `samples:` entry per argument. Inside it, `fields:` already maps the columns that look
    like spatial domains, cell types and the usual QC metrics (total counts, detected genes, mito percent),
    and every other column is listed as a comment with its type and levels, so showing one more annotation is
    uncommenting a line. Optional settings (opening gene, palette, thumbnail, layout) are present as comments.
    The file builds as written; edit it, then run `build`.
    """
    from .init import write_menu

    r = write_menu(paths, out=out, dataset_id=dataset_id, name=name, platform=platform, table=table, log=lambda m: typer.secho(m, dim=True))
    typer.echo(f"wrote {r.out.resolve()}")
    if r.samples:
        typer.echo(f"  {len(r.samples)} sample{'s' if len(r.samples) != 1 else ''}: {', '.join(r.samples[:8])}{', ...' if len(r.samples) > 8 else ''}")
    typer.echo(f"  annotations mapped: {', '.join(r.mapped) or 'none'}; {r.commented} more column{'s' if r.commented != 1 else ''} listed as comments")
    typer.echo(f"  next: edit {r.out.name} (names, colors, which annotations), then `spatialscape build {r.out}`")


@app.command()
def inspect(
    path: Path = typer.Argument(..., help="An `.h5ad` file, an AnnData Zarr store, a SpatialData Zarr store, or an R `.rds` / `.rda` holding a SpatialExperiment / SingleCellExperiment.", show_default=False),
    table: str | None = typer.Option(None, "--table", help="Table key inside a SpatialData store (required when the store has more than one)."),
):
    """Print what a sample file contains, to help edit the dataset yaml.

    Lists every `obs` column with its type and number of levels (with example values for categoricals),
    the `obsm` keys and their shapes, the layers, and any `uns` keys that look like scale information.
    `init` writes the same information into a yaml you can edit; `inspect` only prints it.
    """
    import numpy as np

    if path.suffix.lower() in (".rds", ".rda", ".rdata"):
        from .rds import read_experiment

        x = read_experiment(path)
        typer.echo(f"{path}: {x.class_name}, {x.n_obs} cells x {x.n_vars} genes; assays: {', '.join(x.assays)}")
        if "sample_id" in x.obs:
            counts = x.obs["sample_id"].astype(str).value_counts()
            typer.echo(f"samples ({len(counts)}): " + ", ".join(f"{k} ({v})" for k, v in counts.items()))
        typer.echo("colData columns:")
        for c in x.obs.columns:
            s = x.obs[c]
            if isinstance(s.dtype, pd.CategoricalDtype) or s.dtype == object:
                n = s.nunique(dropna=True)
                typer.echo(f"  {c:<40} categorical  {n:>5} levels  e.g. {list(map(str, s.dropna().unique()[:6]))}")
            else:
                v = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
                typer.echo(f"  {c:<40} numeric     range {np.nanmin(v):.3g}..{np.nanmax(v):.3g}")
        typer.echo("spatialCoords: " + ("yes" if x.spatial is not None else "no (an snRNA-seq / embedding object)"))
        typer.echo("reducedDims: " + ", ".join(f"{k}{v.shape}" for k, v in x.reduced_dims.items()))
        typer.echo("images: " + (", ".join(f"{i.sample_id}/{i.image_id} (scale {i.scale_factor:.4g}, {'loaded' if i.rgb is not None else 'stored'})" for i in x.images) or "none"))
        typer.echo("rowData columns: " + ", ".join(x.var.columns) + f"; rownames e.g. {', '.join(x.var.index[:3])}")
        typer.echo(f"next: spatialscape init {path} --id <dataset id>")
        return

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
    typer.echo("layers: " + ", ".join(k for k in a.layers if k))
    hints = [k for k in a.uns if any(t in k.lower() for t in ("scale", "spacing", "unit", "spatial", "pixel"))]
    typer.echo("uns scale hints: " + ", ".join(hints))
    for k in hints:
        v = a.uns[k]
        if not isinstance(v, dict):
            typer.echo(f"  {k} = {v}")


@app.command()
def build(
    config: Path = CONFIG_ARG,
    out: Path | None = OUT_OPT,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show which samples would be built, kept or removed, and why; write nothing."),
    force: bool = typer.Option(False, "--force", help="Rebuild every sample even when nothing changed."),
    no_shard: bool = typer.Option(False, "--no-shard", help="Write one file per gene instead of sharded Zarr. Larger file counts, but works on hosts without HTTP Range support (e.g. GitHub Pages)."),
    quiet: bool = typer.Option(False, "-q", "--quiet", help="Suppress per-sample progress output."),
):
    """Build or update a bundle from the dataset yaml. Rerun it after any edit.

    The first run converts R objects listed under `samples:` (kept in `bundles/.cache/<id>/` next to the
    bundle), builds every sample and writes the dataset-level files. Later runs rebuild only the samples whose
    source files, settings or field declarations changed (compared with `samples/<id>/build.json`), remove
    samples the yaml no longer lists, and always rewrite `manifest.json`, `genes.json`, `features.json` and
    the thumbnails, so renamed fields, palettes and defaults apply in seconds. Ends with the same checks as
    `validate`; exits with status 1 if they report problems.
    """
    from .build import build_bundle
    from .config import load_config

    cfg = load_config(config)
    target = (out or cfg.default_bundle_dir).resolve()
    log = (lambda *_: None) if quiet and not dry_run else typer.echo
    log(f"{cfg.id} -> {target}")
    res = build_bundle(cfg, target, sharded=not no_shard, force=force, dry_run=dry_run, log=log)
    if dry_run:
        typer.echo("dry run: nothing written")
        return
    for p in res.problems:
        typer.secho(f"  ! {p}", fg="red")
    m = res.manifest
    n_built, n_kept, n_gone = len(res.plan.to_build), len(res.plan.reused), len(res.plan.removed)
    parts = [f"{n_built} built"] + ([f"{n_kept} unchanged"] if n_kept else []) + ([f"{n_gone} removed"] if n_gone else [])
    typer.echo(f"built {res.out}: {len(m.samples)} samples ({', '.join(parts)}), {sum(s.nObs for s in m.samples):,} obs")
    typer.echo(f"  next: spatialscape serve {res.out.parent} --open")
    raise typer.Exit(1 if res.problems else 0)


@app.command()
def outlines(
    config: Path = CONFIG_ARG,
    out: Path | None = OUT_OPT,
    sample: list[str] = typer.Option(None, "--sample", help="Only these sample ids (repeatable). Default: every spatial sample."),
    field: list[str] = typer.Option(None, "--field", help="Only these categorical field ids (repeatable). Default: every categorical field the sample carries."),
    smooth_um: float = typer.Option(150.0, "--smooth-um", help="Side of the majority-vote smoothing window, in microns. Larger values merge small islands into their neighbours."),
    min_feature_um: float = typer.Option(300.0, "--min-feature-um", help="Islands and holes smaller than this (per side, in microns) are removed before tracing."),
):
    """Re-trace annotation boundaries from the arrays already in a bundle.

    `build` traces outlines with the default settings. This command redoes them with other sizes: labels are
    rasterized at half the cell spacing, majority-smoothed, cleaned of small features, traced with marching
    squares and simplified. Cells labelled `NA` are treated as unknown and filled by their neighbours. Results
    go to `samples/<id>/outlines/<field>.json` and the manifest; no source data is read.
    """
    from .build import add_outlines
    from .config import load_config

    cfg = load_config(config)
    target = out or cfg.default_bundle_dir
    m = add_outlines(cfg, target, sample_ids=sample or None, fields=field or None, smooth_um=smooth_um, min_feature_um=min_feature_um)
    typer.echo(f"outlines written: {[(s.id, s.outlines) for s in m.samples if s.outlines]}")


@app.command()
def thumbnails(
    out: Path = typer.Argument(..., help="Bundle directory.", show_default=False),
    hero: str | None = typer.Option(None, "--hero", help="Sample shown on the dataset thumbnail. Default: `thumbnail_sample` from the yaml, else the first spatial sample in layout order."),
    no_per_sample: bool = typer.Option(False, "--no-per-sample", help="Skip the per-sample thumbnails."),
):
    """Re-render `thumbnail.png` for the dataset and for each sample.

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
    directory: Path = typer.Argument(".", help="Folder of bundles (each reachable at `/<folder-name>`), a single bundle, or a site written by `site build`."),
    port: int | None = typer.Option(None, "--port", help="TCP port. Default 8787, or the next free port when that one is busy."),
    host: str = typer.Option("127.0.0.1", "--host", help="Interface to bind. Use `0.0.0.0` to reach the server from other machines."),
    open_browser: bool = typer.Option(False, "--open", help="Open the viewer in the default browser once the server is up."),
):
    """Open your bundles in the viewer locally: one origin for the app and the data.

    Serves the viewer that ships with this package at `/`, a `datasets.json` generated from every bundle in
    the folder (so the landing gallery lists them all), and the bundles themselves with CORS and HTTP Range
    headers. A folder that already contains `index.html` (the output of `site build`) is served as-is.
    A development server, not meant for production traffic.
    """
    from .serve import serve as _serve

    _serve(directory.resolve(), port=port or 8787, host=host, open_browser=open_browser, port_chosen=port is not None)


site_app = typer.Typer(help="The gallery: describe it in `site.yaml`, build it into a folder you can upload.", no_args_is_help=True)
app.add_typer(site_app, name="site")


@site_app.command("init")
def site_init(
    items: list[Path] = typer.Argument(None, help="Dataset yamls and/or built bundle folders to list. Default: every `*.yaml` next to the output that looks like a dataset yaml, plus `bundles/*` there.", show_default=False),
    out: Path = typer.Option("site.yaml", "-o", "--out", help="Where to write the site yaml."),
    title: str | None = typer.Option(None, "--title", help="Gallery title.", show_default=False),
):
    """Write a starter `site.yaml` listing your datasets.

    Only needed for a gallery of several datasets, a title and intro, a navigation bar, paper links, tags or
    "coming soon" cards; a single dataset can be served and published straight from its bundle. The optional
    settings are present as comments.
    """
    from .site import write_site_template

    out = out.expanduser()
    found = list(items or [])
    if not found:
        base = out.parent
        listed: set[str] = set()
        for y in sorted(base.glob("*.yaml")):
            did = _dataset_id_of(y) if y.resolve() != out.resolve() else None
            if did:
                found.append(y)
                listed.add(did)
        found += [m.parent for m in sorted((base / "bundles").glob("*/manifest.json")) if m.parent.name not in listed]
    if not found:
        raise ValueError("nothing to list: pass the dataset yamls or bundle folders to include, e.g. `spatialscape site init amygdala.yaml dlpfc.yaml`")
    p = write_site_template(found, out, title=title)
    typer.echo(f"wrote {p.resolve()} ({len(found)} dataset(s))\n  next: edit it, then `spatialscape site build {p}`")


def _dataset_id_of(y: Path) -> str | None:
    """The id of a dataset yaml, or None for anything else (a site.yaml, an unrelated file)."""
    import yaml

    try:
        doc = yaml.safe_load(y.read_text())
    except Exception:
        return None
    return str(doc["id"]) if isinstance(doc, dict) and "samples" in doc and "id" in doc else None


@site_app.command("build")
def site_build(
    target: Path = typer.Argument(..., help="`site.yaml`, or a folder of built bundles for a gallery without any settings.", show_default=False),
    out: Path | None = typer.Option(None, "-o", "--out", help="Site directory to write. Default: `site/` next to the target.", show_default=False),
    link: bool = typer.Option(False, "--link", help="Symlink bundle folders into the site instead of copying them (local previews of large data)."),
):
    """Write a folder you can upload to any static host.

    From `site.yaml`: builds every dataset listed under `config:` whose data or yaml changed, copies the
    viewer into `OUT`, places every bundle at `OUT/<id>/` (or points at `data_url`), and writes `OUT/datasets.json`
    from the yaml and the bundles' manifests: names, descriptions, platforms, counts, thumbnails, paper links,
    tags and placeholder cards. From a folder of bundles: the same without any settings. Preview with
    `spatialscape serve OUT`.
    """
    from .site import build_site, build_site_from_config

    target = target.expanduser()
    if target.is_file():
        out_dir = build_site_from_config(target, out, link=link, log=typer.echo)
    elif target.is_dir():
        out_dir = build_site(out or target.resolve().parent / "site", [target], link=link, log=typer.echo)
    else:
        raise FileNotFoundError(str(target))
    typer.echo(f"site ready: {out_dir}\n  preview: spatialscape serve {out_dir}\n  deploy:  upload the folder to GitHub Pages, Cloudflare Pages, Netlify, S3 + CloudFront, or any static host")


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


def _describe(e: BaseException) -> str:
    """One readable message per error class; the traceback stays behind SPATIALSCAPE_DEBUG=1."""
    from pydantic import ValidationError
    from yaml import YAMLError

    if isinstance(e, ValidationError):
        lines = [f"{'.'.join(str(x) for x in err['loc']) or '<root>'}: {err['msg']}" for err in e.errors()]
        return "the yaml is not valid:\n  " + "\n  ".join(lines)
    if isinstance(e, YAMLError):
        return f"the yaml could not be parsed: {e}"
    if isinstance(e, FileNotFoundError):
        return f"file not found: {e.filename or e}"
    if isinstance(e, KeyError) and e.args:
        return str(e.args[0])
    if isinstance(e, (ValueError, OSError)):
        return str(e)
    return f"{type(e).__name__}: {e}"


def main(argv: list[str] | None = None) -> None:
    """Console entry point: run the Typer app and turn expected failures into one-line errors."""
    import os
    import sys

    try:
        app(args=argv, standalone_mode=False, prog_name="spatialscape")
    except typer.Exit as e:
        sys.exit(e.exit_code)
    except typer.Abort:
        typer.secho("aborted", fg="red", err=True)
        sys.exit(130)
    except Exception as e:
        # usage errors (Typer ships its own click, so match by shape rather than class)
        if hasattr(e, "show") and hasattr(e, "exit_code"):
            e.show()  # type: ignore[attr-defined]
            sys.exit(e.exit_code)  # type: ignore[attr-defined]
        if os.environ.get("SPATIALSCAPE_DEBUG"):
            raise
        typer.secho(f"error: {_describe(e)}", fg="red", err=True)
        typer.secho("set SPATIALSCAPE_DEBUG=1 for the full traceback", dim=True, err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
