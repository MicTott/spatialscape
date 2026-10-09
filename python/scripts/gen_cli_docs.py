"""Generate the CLI reference pages for the docs site from the Typer app itself.

    python/.venv/bin/python python/scripts/gen_cli_docs.py

Writes docs/reference/cli/index.md, one page per command, and sidebar.json used by the VitePress config.
Help strings in spatialscape/cli.py are the single source of truth; examples live in EXAMPLES below.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import typer.main

from spatialscape.cli import app

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "reference" / "cli"

EXAMPLES: dict[str, list[tuple[str, str]]] = {
    "init": [
        ("Xenium donors in sibling folders", 'spatialscape init "xenium/*/adata.zarr" --platform xenium --id amygdala --name "Human amygdala" -o dataset.yaml'),
        ("Two patterns, one config", 'spatialscape init "visium/*/outs" "xenium/*/adata.zarr" --platform visium -o dataset.yaml'),
    ],
    "plan": [("Check what a build would do", "spatialscape plan dataset.yaml")],
    "inspect": [
        ("An h5ad written from R", "spatialscape inspect Br2743.h5ad"),
        ("A SpatialData store with several tables", "spatialscape inspect store.zarr --table cells"),
    ],
    "build": [
        ("Standard build", "spatialscape build dataset.yaml -o bundles/amygdala"),
        ("For GitHub Pages or other hosts without Range support", "spatialscape build dataset.yaml -o site/examples/demo --no-shard"),
    ],
    "add-sample": [
        ("Rebuild one donor after fixing its coordinates", "spatialscape add-sample dataset.yaml -o bundles/amygdala --sample vis_Br2743"),
        ("Fail instead of silently extending a vocabulary", "spatialscape add-sample dataset.yaml -o bundles/amygdala --sample xen_new --no-allow-vocab-append"),
    ],
    "refresh": [("After renaming fields or changing the palette", "spatialscape refresh dataset.yaml -o bundles/amygdala")],
    "outlines": [
        ("All spatial samples, all categorical fields", "spatialscape outlines dataset.yaml -o bundles/amygdala"),
        ("Finer outlines for one Xenium donor", "spatialscape outlines dataset.yaml -o bundles/amygdala --sample xen_Br9280 --field domain --smooth-um 80 --min-feature-um 150"),
    ],
    "thumbnails": [("Lead with a particular section", "spatialscape thumbnails bundles/amygdala --hero vis_Br8325")],
    "validate": [
        ("Before upload", "spatialscape validate bundles/amygdala"),
        ("After upload", "spatialscape validate https://data.example.org/amygdala"),
    ],
    "serve": [
        ("Open everything under a folder in the viewer", "spatialscape serve bundles --open"),
        ("Reachable from another machine on the network", "spatialscape serve bundles --host 0.0.0.0 --port 8787"),
        ("Preview a site written by `site build`", "spatialscape serve site"),
    ],
    "site build": [
        ("Viewer + bundles in one folder, ready to upload", "spatialscape site build bundles/my_atlas bundles/other -o site --title \"Our lab's data\""),
        ("Bundles already on R2 / S3; the site only carries the viewer and the registry", "spatialscape site build bundles/my_atlas -o site --data-url https://data.example.org"),
        ("Local preview of large bundles without copying them", "spatialscape site build bundles/my_atlas -o site --link && spatialscape serve site"),
    ],
    "synth": [("Make inputs, build them, serve them", "spatialscape synth demo-src && spatialscape build demo-src/dataset.yaml -o bundles/demo && spatialscape serve bundles")],
}
RELATED: dict[str, list[str]] = {
    "init": ["plan", "inspect", "build"],
    "plan": ["init", "build"],
    "inspect": ["init"],
    "build": ["validate", "add-sample", "refresh", "serve"],
    "add-sample": ["build", "refresh"],
    "refresh": ["add-sample", "thumbnails"],
    "outlines": ["build"],
    "thumbnails": ["refresh"],
    "validate": ["build", "serve"],
    "serve": ["site build", "validate"],
    "site build": ["serve", "build"],
    "synth": ["build"],
}
GUIDE_LINKS: dict[str, tuple[str, str]] = {
    "init": ("Writing dataset.yaml", "/guide/dataset-yaml"),
    "plan": ("Writing dataset.yaml", "/guide/dataset-yaml"),
    "inspect": ("Preparing your data", "/guide/preparing-data"),
    "build": ("Building and validating", "/guide/building"),
    "add-sample": ("Building and validating", "/guide/building#incremental-workflows"),
    "refresh": ("Building and validating", "/guide/building#incremental-workflows"),
    "outlines": ("Using the viewer: outlines", "/guide/viewer#outlines"),
    "thumbnails": ("Registry and site bar", "/guide/registry"),
    "validate": ("Hosting", "/guide/hosting"),
    "serve": ("Getting started", "/guide/getting-started"),
    "site build": ("Publish your own site", "/guide/publish"),
    "synth": ("Getting started", "/guide/getting-started#try-it-in-two-minutes"),
}


def is_arg(p) -> bool:
    return p.param_type_name == "argument"


def is_opt(p) -> bool:
    return p.param_type_name == "option"


def md_inline(s: str) -> str:
    """Help strings use backticks already; just escape table pipes."""
    return (s or "").replace("|", "\\|").replace("\n", " ")


def type_name(p) -> str:
    t = p.type
    if is_opt(p) and p.is_flag:
        return "flag"
    name = getattr(t, "name", str(t)).upper()
    if name in ("TEXT", "STR", "STRING"):
        name = "text"
    elif name in ("INTEGER",):
        name = "int"
    elif name in ("FLOAT",):
        name = "float"
    elif name in ("PATH",):
        name = "path"
    else:
        name = name.lower()
    return name + (", repeatable" if p.multiple else "")


def default_str(p) -> str:
    if p.required:
        return "*required*"
    d = p.default
    if is_opt(p) and p.is_flag:
        return "`off`" if not d else "`on`"
    if d is None or d == () or d == []:
        return "—"
    if callable(d):
        return "—"
    return f"`{d}`"


def usage(cmd_name: str, cmd) -> str:
    parts = [f"spatialscape {cmd_name}"]
    for p in cmd.params:
        if is_arg(p):
            nm = p.human_readable_name.upper()
            parts.append(f"<{nm}>" + ("..." if p.nargs == -1 else "") if p.required else f"[{nm}]")
    if any(is_opt(p) for p in cmd.params):
        parts.append("[OPTIONS]")
    return " ".join(parts)


def page(cmd_name: str, cmd) -> str:
    doc = (cmd.help or "").strip()
    summary, _, rest = doc.partition("\n\n")
    rest = re.sub(r"\n(?!\n)", " ", rest).strip()
    args = [p for p in cmd.params if is_arg(p)]
    opts = [p for p in cmd.params if is_opt(p) and p.name != "help"]
    out = [f"# `spatialscape {cmd_name}`", "", summary, ""]
    if rest:
        out += [rest, ""]
    out += ["## Usage", "", "```bash", usage(cmd_name, cmd), "```", ""]
    if args:
        out += ["## Arguments", "", "| Argument | Type | Default | Description |", "|---|---|---|---|"]
        for p in args:
            out.append(f"| `{p.human_readable_name.upper()}` | {type_name(p)} | {default_str(p)} | {md_inline(getattr(p, 'help', '') or '')} |")
        out.append("")
    if opts:
        out += ["## Options", "", "| Option | Type | Default | Description |", "|---|---|---|---|"]
        for p in opts:
            names = ", ".join(f"`{o}`" for o in (p.opts + p.secondary_opts))
            out.append(f"| {names} | {type_name(p)} | {default_str(p)} | {md_inline(p.help or '')} |")
        out.append("")
    ex = EXAMPLES.get(cmd_name, [])
    if ex:
        out += ["## Examples", ""]
        for title, code in ex:
            out += [f"**{title}**", "", "```bash", code, "```", ""]
    rel = RELATED.get(cmd_name, [])
    g = GUIDE_LINKS.get(cmd_name)
    if rel or g:
        out += ["## See also", ""]
        for r in rel:
            out.append(f"- [`spatialscape {r}`](./{r.replace(' ', '-')})")
        if g:
            out.append(f"- Guide: [{g[0]}]({g[1]})")
        out.append("")
    return "\n".join(out)


def main() -> None:
    group = typer.main.get_command(app)
    assert hasattr(group, "commands"), "expected a command group"
    OUT.mkdir(parents=True, exist_ok=True)
    commands: dict[str, object] = {}
    for n, cmd in group.commands.items():
        if hasattr(cmd, "commands"):  # nested group such as `site`
            for sub, subcmd in cmd.commands.items():
                commands[f"{n} {sub}"] = subcmd
        else:
            commands[n] = cmd
    names = [n for n in EXAMPLES if n in commands]  # documented order
    names += [n for n in commands if n not in names]
    rows = []
    sidebar = []
    for n in names:
        cmd = commands[n]
        slug = n.replace(" ", "-")
        (OUT / f"{slug}.md").write_text(page(n, cmd))
        summary = (cmd.help or "").strip().partition("\n\n")[0]
        rows.append(f"| [`{n}`](./{slug}) | {md_inline(summary)} |")
        sidebar.append({"text": n, "link": f"/reference/cli/{slug}"})
    index = [
        "# CLI commands",
        "",
        "The `spatialscape` command converts data into viewer bundles and checks them. Every command is also available as `sscape <command>`, and `spatialscape <command> --help` prints the same information as these pages.",
        "",
        "```bash",
        "pip install spatialscape",
        "spatialscape --help",
        "```",
        "",
        "| Command | Purpose |",
        "|---|---|",
        *rows,
        "",
        "## Typical sequence",
        "",
        "```bash",
        'spatialscape init "data/*/adata.zarr" --platform xenium --id my_atlas -o dataset.yaml',
        "spatialscape plan dataset.yaml",
        "spatialscape build dataset.yaml -o bundles/my_atlas",
        "spatialscape serve bundles --port 8787",
        "# ... upload bundles/my_atlas ...",
        "spatialscape validate https://data.example.org/my_atlas",
        "```",
        "",
        "## Exit codes",
        "",
        "`build` and `validate` exit with status 1 when validation reports problems, so they can gate a deployment script. Every other command exits 0 on success and raises on error.",
        "",
        "::: tip Generated reference",
        "These pages are generated from the CLI's own help text by `python/scripts/gen_cli_docs.py`. If a page and `--help` ever disagree, `--help` is right and the generator needs re-running.",
        ":::",
        "",
    ]
    (OUT / "index.md").write_text("\n".join(index))
    (OUT / "sidebar.json").write_text(json.dumps(sidebar, indent=2))
    print(f"wrote {len(names)} command pages to {OUT}")


if __name__ == "__main__":
    main()
