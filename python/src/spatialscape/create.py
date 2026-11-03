"""The Create page: a browser page over `init`, `build` and `serve` for data on the machine the server runs on.

`spatialscape create [PROJECT]` serves the viewer with this service switched on. The page browses the server's
filesystem (paths, never uploads), asks for an inspection of the chosen objects or folders (what `init` works out:
platform, annotations, expression layers, samples, images and layer files), lets the user tick and rename, shows the
yaml those choices make, and builds it: the yaml is written to PROJECT/<id>.yaml and the bundle to
PROJECT/bundles/<id>, which the same server lists in its gallery. Everything the page does the CLI can do with the
file it wrote. State lives in this process: inspections by token, builds by job id, both forgotten on restart.
"""

from __future__ import annotations

import copy
import json
import os
import platform as _platform
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Log = Any

PLATFORMS = ["visium", "visium_hd", "xenium", "merfish", "codex", "other"]
OBJECT_SUFFIXES = {".rds", ".rda", ".rdata", ".h5ad"}
TABLE_SUFFIXES = {".csv", ".tsv", ".parquet"}


def login_node_guard() -> str | None:
    """A message when this looks like a cluster login node: a scheduler is installed and we are not inside a job.
    Builds there get killed and annoy everyone; SPATIALSCAPE_ALLOW_LOGIN_NODE=1 says you know better."""
    if os.environ.get("SPATIALSCAPE_ALLOW_LOGIN_NODE"):
        return None
    scheduler = shutil.which("sbatch") or shutil.which("qsub")
    if scheduler and not (os.environ.get("SLURM_JOB_ID") or os.environ.get("PBS_JOBID") or os.environ.get("JOB_ID")):
        return (
            f"{_platform.node()} looks like a cluster login node (a scheduler is installed and this is not a job). "
            "Builds here are killed and slow everyone down: start `spatialscape create` on a compute node "
            "(for example `srun --pty --mem=16G bash`, then forward its port), or set SPATIALSCAPE_ALLOW_LOGIN_NODE=1."
        )
    return None


# ---------------------------------------------------------------- browsing
def _kind(p: Path) -> tuple[str, str]:
    """(kind, hint) of a directory entry: object (an .rds / .h5ad / AnnData Zarr), store (SpatialData or
    spatialproteomics), table (a results table), folder, or file."""
    name = p.name.lower()
    if p.is_dir():
        from .proteomics import is_spatialproteomics
        from .sdata import elements, is_spatialdata

        if is_spatialdata(p):
            els = elements(p)
            parts = [f"{len(v)} {k}" for k, v in els.items() if v]
            return "store", "SpatialData store: " + ", ".join(parts)
        if is_spatialproteomics(p):
            return "store", "spatialproteomics object"
        if (p / ".zattrs").exists() or (p / "zarr.json").exists():
            return "object", "AnnData Zarr" if (p / "obs").is_dir() else "Zarr group"
        if (p / "experiment.xenium").exists() or (p / "cell_feature_matrix.h5").exists():
            return "folder", "Xenium output folder (pick its .h5ad, or convert the matrix first)"
        if (p / "spatial" / "scalefactors_json.json").exists():
            return "folder", "SpaceRanger output folder"
        return "folder", ""
    suffix = p.suffix.lower()
    if suffix in OBJECT_SUFFIXES:
        return "object", {"rds": "R object", "rda": "R data file", "rdata": "R data file", "h5ad": "AnnData"}[suffix[1:]]
    if suffix in TABLE_SUFFIXES or name.endswith((".csv.gz", ".tsv.gz")):
        return "table", "results table (one row per gene) or a layer table"
    return "file", ""


def browse(path: str | None, project: Path) -> dict[str, Any]:
    """One folder's entries, hidden ones left out, folders first; the roots the page offers as starting points."""
    home = Path.home()
    p = Path(path).expanduser() if path else project
    if not p.exists():
        raise FileNotFoundError(str(p))
    p = p.resolve()
    if p.is_file():
        p = p.parent
    entries = []
    try:
        children = sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))
    except PermissionError:
        children = []
    for c in children:
        if c.name.startswith("."):
            continue
        try:
            kind, hint = _kind(c)
            size = c.stat().st_size if c.is_file() else None
        except OSError:
            continue
        entries.append({"name": c.name, "path": str(c), "kind": kind, "hint": hint, "size": size})
    roots = [{"name": "project", "path": str(project)}, {"name": "home", "path": str(home)}]
    for extra in (Path("/Volumes"), Path("/dcs04"), Path("/data"), Path("/scratch")):
        if extra.is_dir():
            roots.append({"name": extra.name, "path": str(extra)})
    return {"path": str(p), "parent": str(p.parent) if p.parent != p else None, "entries": entries, "roots": roots}


# ---------------------------------------------------------------- inspections
@dataclass
class Inspection:
    token: str
    paths: list[str]
    dataset_id: str
    name: str
    entries: list[Any]  # init.EntryMenu
    comparisons: list[Any]  # init.ComparisonMenu
    created: float = field(default_factory=time.time)


def _column_rows(e) -> list[dict[str, Any]]:
    """The annotation choices of one entry: mapped columns on, alternatives and the rest off, each with its id,
    kind, a note, and what the page needs to describe it in words (level names, ranges, missing values)."""
    from .init import field_id

    m = e.menu
    detail = {c.name: c for c in getattr(e, "columns", [])}

    def describe(col: str) -> dict[str, Any]:
        c = detail.get(col)
        if c is None:
            return {"levels": 0, "examples": [], "lo": None, "hi": None, "named": True, "na": 0}
        return {"levels": c.levels, "examples": list(c.examples), "lo": c.lo, "hi": c.hi, "named": c.named, "na": c.na}

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fid, v in m.mapped.items():
        col = v if isinstance(v, str) else v["column"]
        rows.append({"id": fid, "column": col, "kind": m.kinds.get(fid, "categorical"), "note": "", "on": True, "scale": None if isinstance(v, str) else v.get("scale"), **describe(col)})
        seen.add(col)
    for fid, c in m.alternatives:
        if c.name in seen:
            continue
        rows.append({"id": field_id(c.name), "column": c.name, "kind": "continuous" if c.kind == "numeric" else "categorical", "note": f"another candidate for {fid}", "on": False, "scale": None, **describe(c.name)})
        seen.add(c.name)
    for c in m.unmapped:
        if c.name in seen:
            continue
        rows.append({"id": field_id(c.name), "column": c.name, "kind": "continuous" if c.kind == "numeric" else "categorical", "note": "", "on": False, "scale": None, **describe(c.name)})
        seen.add(c.name)
    return rows


def describe_entry(e) -> dict[str, Any]:
    return {
        "source": e.source,
        "source_note": e.source_note,
        "r_object": e.r_object,
        "embedding": e.embedding,
        "platform": e.platform,
        "platform_note": e.platform_note,
        "n_obs": e.n_obs,
        "samples": e.samples,
        "sample_col": e.sample_col,
        "assay": e.assay,
        "assays": e.assays,
        "layer": getattr(e, "layer", None) or "X",
        "layers": ["X", *e.layers],
        "embedding_key": e.embedding_key,
        "embeddings": e.embeddings,
        "table": e.table,
        "region": e.region,
        "regions": e.regions,
        "store_note": e.store_note,
        "sections": list(e.sections) if e.sections else None,
        "layer_files": e.layer_files,
        "fragments": e.fragments,
        "columns": _column_rows(e),
        "meta": [{"column": c, "note": note, "on": False} for c, note in e.meta_candidates],
        "skipped": e.menu.skipped,
        "object_class": e.object_class,
        "n_vars": e.n_vars,
        "found": [{"present": p, "title": t, "detail": d} for p, t, d in e.found],
    }


def describe_comparison(c) -> dict[str, Any]:
    return {"source": c.source, "id": c.id, "name": c.name, "kind": c.kind, "n_rows": c.n_rows, "columns": c.columns, "facet": c.facet, "groups": c.groups}


def apply_choices(entries: list[Any], choices: dict[str, Any]) -> tuple[list[Any], dict[str, str]]:
    """Copies of the entries with the page's choices applied: per entry (by index) platform, assay or layer,
    embedding, region and the annotation and metadata columns switched on; dataset-wide the display names. The
    original entries are untouched, so a change of mind re-renders from the same inspection."""
    from .init import Menu

    out = []
    names: dict[str, str] = {str(k): str(v) for k, v in (choices.get("names") or {}).items() if str(v).strip()}
    per = {int(k): v for k, v in (choices.get("entries") or {}).items()}
    for i, e0 in enumerate(entries):
        e = copy.deepcopy(e0)
        ch = per.get(i) or {}
        if "platform" in ch and not e.embedding and ch["platform"] in PLATFORMS:
            e.platform = ch["platform"]
            e.platform_note = "chosen"
        if ch.get("assay") and e.r_object:
            e.assay = str(ch["assay"])
        if ch.get("layer") and not e.r_object:
            e.layer = None if ch["layer"] == "X" else str(ch["layer"])
        if ch.get("embedding") and e.embedding and e.r_object:
            e.embedding_key = str(ch["embedding"])
        if ch.get("region") and e.regions is not None:
            e.region = str(ch["region"])
        if "columns" in ch:
            rows = _column_rows(e0)
            by_col = {r["column"]: r for r in rows}
            m = Menu(skipped=list(e0.menu.skipped))
            for pick in ch["columns"]:
                col = str(pick.get("column", ""))
                r = by_col.get(col)
                if r is None or not pick.get("on", True):
                    continue
                fid = str(pick.get("id") or r["id"]).strip() or r["id"]
                m.mapped[fid] = col if r.get("scale") is None else {"column": col, "scale": r["scale"]}
                m.kinds[fid] = r["kind"]
                m.notes[fid] = r["note"]
            e.menu = m
        if "meta" in ch:
            e.meta_chosen = [str(c) for c in ch["meta"] if any(c == cand for cand, _ in e0.meta_candidates)]
        out.append(e)
    return out, names


class CreateService:
    def __init__(self, project: Path):
        self.project = Path(project).resolve()
        self.bundles = self.project / "bundles"
        self.inspections: dict[str, Inspection] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    # ---- what the page asks
    def ping(self) -> dict[str, Any]:
        from . import __version__

        return {"create": True, "host": _platform.node(), "project": str(self.project), "bundles": str(self.bundles), "home": str(Path.home()), "guard": login_node_guard(), "version": __version__}

    def browse(self, path: str | None) -> dict[str, Any]:
        return browse(path, self.project)

    def inspect(self, paths: list[str], *, platform: str | None, table: str | None, dataset_id: str | None, name: str | None) -> dict[str, Any]:
        from .init import build_menu

        if not paths:
            raise ValueError("choose at least one object, folder or file")
        if platform is not None and platform not in PLATFORMS and platform != "snrnaseq":
            raise ValueError(f"unknown platform {platform!r}")
        lines: list[str] = []
        res = build_menu(paths, base=self.project, dataset_id=dataset_id, name=name, platform=platform, table=table, log=lines.append)
        token = uuid.uuid4().hex[:12]
        ins = Inspection(token=token, paths=list(paths), dataset_id=res.dataset_id, name=res.name, entries=res.entries, comparisons=res.comparisons)
        with self.lock:
            self.inspections[token] = ins
            for k in [k for k, v in self.inspections.items() if time.time() - v.created > 6 * 3600]:
                del self.inspections[k]
        return {**self.render(token, {}), "token": token, "log": lines, "entries": [describe_entry(e) for e in res.entries], "comparisons": [describe_comparison(c) for c in res.comparisons]}

    def render(self, token: str, choices: dict[str, Any]) -> dict[str, Any]:
        from .init import render_dataset_yaml

        ins = self._inspection(token)
        entries, names = apply_choices(ins.entries, choices)
        dataset_id = str(choices.get("id") or ins.dataset_id).strip() or ins.dataset_id
        name = str(choices.get("name") or ins.name).strip() or ins.name
        from .config import check_path_id

        check_path_id(dataset_id, "dataset id")
        text = render_dataset_yaml(dataset_id=dataset_id, name=name, entries=entries, comparisons=ins.comparisons, names=names)
        return {"id": dataset_id, "name": name, "yaml": text, "yaml_path": str(self.project / f"{dataset_id}.yaml"), "bundle": str(self.bundles / dataset_id)}

    def build(self, token: str, choices: dict[str, Any]) -> dict[str, Any]:
        guard = login_node_guard()
        if guard:
            raise PermissionError(guard)
        r = self.render(token, choices)
        yaml_path = Path(r["yaml_path"])
        self.project.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(r["yaml"])
        job_id = uuid.uuid4().hex[:10]
        job: dict[str, Any] = {"id": job_id, "status": "running", "lines": [f"wrote {yaml_path}"], "yaml": str(yaml_path), "bundle": r["bundle"], "dataset_id": r["id"], "error": None, "started": time.time(), "finished": None}
        with self.lock:
            self.jobs[job_id] = job
        threading.Thread(target=self._run, args=(job, yaml_path), daemon=True, name=f"create-build-{job_id}").start()
        return {"job": job_id, **{k: job[k] for k in ("yaml", "bundle", "dataset_id")}}

    def job(self, job_id: str, since: int = 0) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            lines = job["lines"][since:]
            return {"id": job_id, "status": job["status"], "lines": lines, "next": since + len(lines), "error": job["error"], "yaml": job["yaml"], "bundle": job["bundle"], "dataset_id": job["dataset_id"], "seconds": round((job["finished"] or time.time()) - job["started"], 1)}

    # ---- internals
    def _inspection(self, token: str) -> Inspection:
        with self.lock:
            ins = self.inspections.get(token)
        if ins is None:
            raise KeyError("this inspection is no longer held (the server restarted); read the data again")
        return ins

    def _run(self, job: dict[str, Any], yaml_path: Path) -> None:
        from .build import build_bundle
        from .config import load_config

        def log(msg: str) -> None:
            with self.lock:
                job["lines"].append(str(msg))

        try:
            cfg = load_config(yaml_path)
            res = build_bundle(cfg, Path(job["bundle"]), log=log)
            n = sum(1 for a in res.plan.actions if a.build)
            log(f"built {job['bundle']}: {n} sample(s) built")
            status = "done"
        except Exception as e:  # the page shows the message; the full traceback goes to the server's terminal
            import traceback

            traceback.print_exc()
            with self.lock:
                job["error"] = f"{type(e).__name__}: {e}"
            status = "error"
        with self.lock:
            job["status"] = status
            job["finished"] = time.time()


# ---------------------------------------------------------------- HTTP glue (used by serve.RangeCORSHandler)
def handle(service: CreateService, method: str, route: str, query: dict[str, str], body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
    """Dispatch one /_api/create request: (status, JSON document)."""
    try:
        if method == "GET" and route == "ping":
            return 200, service.ping()
        if method == "GET" and route == "browse":
            return 200, service.browse(query.get("path") or None)
        if method == "GET" and route.startswith("jobs/"):
            return 200, service.job(route[len("jobs/") :], int(query.get("from", "0") or 0))
        body = body or {}
        if method == "POST" and route == "inspect":
            return 200, service.inspect([str(p) for p in body.get("paths") or []], platform=body.get("platform") or None, table=body.get("table") or None, dataset_id=body.get("id") or None, name=body.get("name") or None)
        if method == "POST" and route == "render":
            return 200, service.render(str(body.get("token") or ""), body.get("choices") or {})
        if method == "POST" and route == "build":
            return 200, service.build(str(body.get("token") or ""), body.get("choices") or {})
        return 404, {"error": f"no such route {route!r}"}
    except FileNotFoundError as e:
        return 404, {"error": f"not found: {e}"}
    except KeyError as e:
        return 404, {"error": str(e).strip("'")}
    except PermissionError as e:
        return 403, {"error": str(e)}
    except (ValueError, TypeError) as e:
        return 400, {"error": str(e)}
    except Exception as e:  # anything else is reported to the page, with the traceback on the terminal
        import traceback

        traceback.print_exc()
        return 500, {"error": f"{type(e).__name__}: {e}"}


def dumps(doc: dict[str, Any]) -> bytes:
    return json.dumps(doc, default=str).encode()
