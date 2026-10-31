"""`spatialscape init`: write a dataset.yaml that doubles as a menu of what the data contains.

One `samples:` entry per argument (an R object, or a glob of AnnData files). Inside each entry `fields:` maps
the columns that look like spatial domains, cell types and the usual QC metrics; every other column is listed
as a comment with its type, so adding one means uncommenting a line. Dataset settings that are optional are
present as comments too. The file builds as written.
"""
from __future__ import annotations

import glob as _glob
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .comparisons import RESULT_ROLES, gene_candidates, is_table, map_columns, read_table
from .config import _sample_folder, is_r_object
from .discover import SKIP_COLUMNS, field_id, is_textual

Log = Callable[[str], None]

PLATFORM_LABEL = {"visium": "Visium", "visium_hd": "Visium HD", "xenium": "Xenium", "merfish": "MERFISH", "codex": "CODEX", "snrnaseq": "snRNA-seq", "other": "Sample"}
PLATFORM_PREFIX = {"visium": "vis", "visium_hd": "hd", "xenium": "xen", "merfish": "mer", "codex": "cdx", "snrnaseq": "sn", "other": "smp"}
GENERIC_STORE_NAMES = {"adata", "data", "sample", "outs", "table", "sdata", "spe", "sce"}
# tables an imaging platform writes next to its matrix (Xenium Ranger names): the yaml key, what it gives, the cost
LAYER_FILES = {
    "cell_boundaries.parquet": ("polygons", "cell shapes", "cell shapes; a nucleus_boundaries.parquet next to it is compared automatically"),
    "transcripts.parquet": ("molecules", "transcripts", "transcripts, drawn once zoomed in: 170-400 MB per section; delete the line to leave them out"),
}
IMAGING_PLATFORMS = {"xenium", "merfish", "codex", "other"}
FIELD_NAMES = {"domain": "Spatial domain", "celltype": "Cell type", "total_counts": "Total counts", "detected_genes": "Detected genes", "mito_percent": "Mito %"}
MAX_MENU_LEVELS = 60
DOMAIN_RE = re.compile(r"domain|cluster|bayesspace|precast|banksy|layer|leiden|louvain|^bs_|_k\d+", re.I)
CELLTYPE_RE = re.compile(r"cell_?type|first_type|annot|label|class|azimuth", re.I)
QC_RE = {
    "total_counts": re.compile(r"^(sum_umi|total_counts|total_umi|sum|n_counts|ncount_\w+|transcript_counts|nCount_\w+)$", re.I),
    "detected_genes": re.compile(r"^(sum_gene|detected|detected_genes|n_genes|n_genes_by_counts|nfeature_\w+|nFeature_\w+)$", re.I),
    "mito_percent": re.compile(r"^(expr_chrM_ratio|subsets_Mito_percent|pct_counts_mt|percent\.mt|pct_mt|mito_percent|percent_mito|mt_frac|pct_mito|mito_frac)$", re.I),
}
EMBEDDING_PREFERENCE = ("UMAP", "umap", "X_umap", "UMAP-HARMONY", "UMAP_HARMONY", "UMAP.HARMONY")
ARRAY_COLUMNS = {"array_row", "array_col", "in_tissue"}  # SpaceRanger's spot / bin grid
CELL_COLUMNS = {"transcript_counts", "cell_area", "nucleus_area", "nucleus_count", "segmentation_method"}  # Xenium's cells.csv
SAMPLE_COLUMN_RE = re.compile(r"^(sample_id|sample|sample_name|section|section_id|capture_area|slide|library_id|batch)$", re.I)
AREA_COLUMN_RE = re.compile(r"^(capture_area|capture_areas|slide|library_id|array)$", re.I)  # several Visium arrays stitched into one sample
VISIUM_MAX_OBS = 20_000  # a Visium capture area holds 4,992 spots (6.5 mm) or 14,336 (11 mm); more is HD bins or cells
VISIUM_ARRAY = (128, 224)  # array_row / array_col never exceed one 11 mm array; Visium HD bins run to hundreds or thousands
COORDINATE_NOTE = {
    "visium": "full-resolution pixels; microns from the spot spacing (100 um) when `build` runs",
    "visium_hd": "full-resolution pixels; set `microns: { microns_per_unit: <SpaceRanger microns_per_pixel> }`",
    "xenium": "taken as microns",
    "merfish": "taken as microns",
    "codex": "pixels of the scan; set `microns: { microns_per_unit: <um per pixel> }`",
    "snrnaseq": "the 2-D embedding, rescaled to a fixed extent",
    "other": "taken as microns; set `microns:` otherwise",
}
GUIDE = "https://mictott.github.io/spatialscape/docs/guide/changes"


# ---------------------------------------------------------------- what the columns are
@dataclass
class Column:
    name: str
    kind: str  # categorical | numeric | boolean | text | empty
    levels: int = 0
    examples: list[str] = field(default_factory=list)
    lo: float | None = None
    hi: float | None = None
    named: bool = True  # categorical: labels are words (CeA, L1) rather than bare cluster numbers
    na: int = 0  # missing values (shown as NA in the viewer)

    @property
    def note(self) -> str:
        base = self._note
        return f"{base}; {self.na:,} NA" if self.na and self.kind in ("categorical", "numeric") else base

    @property
    def _note(self) -> str:
        if self.kind == "categorical":
            if self.levels > MAX_MENU_LEVELS:
                return f"{self.levels} levels (too many for a legend)"
            more = ", ..." if self.levels > len(self.examples) else ""
            return f"{self.levels} levels: {', '.join(self.examples)}{more}"
        if self.kind == "numeric":
            return f"numeric {_g(self.lo)}..{_g(self.hi)}"
        if self.kind == "boolean":
            return "true/false"
        if self.kind == "text":
            return "text, unique per cell"
        return "empty"


def _g(v: float | None) -> str:
    if v is None or not np.isfinite(v):
        return "?"
    return f"{v:,.0f}" if float(v).is_integer() and abs(v) < 1e12 else f"{v:.3g}"


def describe_columns(obs: pd.DataFrame) -> list[Column]:
    out: list[Column] = []
    n = len(obs)
    for col in obs.columns:
        s = obs[col]
        name = str(col)
        na = int(s.isna().sum())
        if str(s.dtype) in ("bool", "boolean"):
            out.append(Column(name, "boolean", na=na))
        elif is_textual(s):
            vals = s.dropna().astype(str)
            k = int(vals.nunique())
            if k == 0:
                out.append(Column(name, "empty"))
            elif k >= n and n > 10:
                out.append(Column(name, "text"))
            else:
                ex = [v if len(v) <= 18 else v[:17] + "…" for v in vals.unique()[:4]]
                numeric_labels = vals.str.fullmatch(r"-?\d+(\.\d+)?").mean()
                out.append(Column(name, "categorical", levels=k, examples=ex, named=bool(numeric_labels < 0.5), na=na))
        elif pd.api.types.is_numeric_dtype(s):
            v = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
            finite = v[np.isfinite(v)]
            na = int(v.size - finite.size)
            if not finite.size:
                out.append(Column(name, "empty"))
                continue
            k = len(np.unique(finite))
            # integer cluster ids (BayesSpace, Leiden from R) are labels, not measurements
            if 2 <= k <= MAX_MENU_LEVELS and np.all(finite == np.rint(finite)) and (DOMAIN_RE.search(name) or CELLTYPE_RE.search(name)):
                ex = [str(int(x)) for x in np.unique(finite)[:4]]
                out.append(Column(name, "categorical", levels=k, examples=ex, named=False, na=na))
            else:
                out.append(Column(name, "numeric", lo=float(finite.min()), hi=float(finite.max()), na=na))
        else:
            out.append(Column(name, "empty"))
    return out


# ---------------------------------------------------------------- which ones to map
@dataclass
class Menu:
    mapped: dict[str, str | dict] = field(default_factory=dict)  # field id -> column, or {column, scale}
    kinds: dict[str, str] = field(default_factory=dict)  # field id -> categorical | continuous
    notes: dict[str, str] = field(default_factory=dict)  # field id -> note on the column
    alternatives: list[tuple[str, Column]] = field(default_factory=list)  # other candidates for domain / celltype
    unmapped: list[Column] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def suggest_fields(columns: list[Column], *, skip: set[str] | None = None) -> Menu:
    """Map one domain-like and one cell-type-like categorical column (2..60 levels), the three usual QC metrics
    by name, and nothing else; everything else is listed as a comment. Among several candidates the last one
    whose labels are names (not bare cluster numbers) wins: later columns are usually the curated, relabelled
    ones. With no domain or cell type at all, every small categorical column is mapped under its own id."""
    skip = set(skip or ())
    menu = Menu()
    used: set[str] = set()
    cols: list[Column] = []
    for c in columns:
        if c.name in skip or SKIP_COLUMNS.match(c.name):
            menu.skipped.append(c.name)
        else:
            cols.append(c)
    cats = [c for c in cols if c.kind == "categorical" and 2 <= c.levels <= MAX_MENU_LEVELS]
    for fid, rx in (("domain", DOMAIN_RE), ("celltype", CELLTYPE_RE)):
        hits = [c for c in cats if rx.search(c.name) and c.name not in used]
        if not hits:
            continue
        named = [c for c in hits if c.named]
        pick = named[-1] if named else hits[0]
        menu.mapped[fid] = pick.name
        menu.kinds[fid] = "categorical"
        menu.notes[fid] = pick.note
        used.add(pick.name)
        for alt in hits:
            if alt is not pick:
                menu.alternatives.append((fid, alt))
                used.add(alt.name)
    if "domain" not in menu.mapped and "celltype" not in menu.mapped:
        for c in cats:
            fid = field_id(c.name)
            if fid in menu.mapped:
                continue
            menu.mapped[fid] = c.name
            menu.kinds[fid] = "categorical"
            menu.notes[fid] = c.note
            used.add(c.name)
    nums = [c for c in cols if c.kind == "numeric"]
    for fid, rx in QC_RE.items():
        hit = next((c for c in nums if rx.match(c.name) and c.name not in used), None)
        if hit is None:
            continue
        says_percent = re.search(r"percent|pct|perc", hit.name, re.I) is not None
        ratio = fid == "mito_percent" and not says_percent and (re.search(r"ratio|frac", hit.name, re.I) is not None or (hit.hi is not None and hit.hi <= 1.0))
        menu.mapped[fid] = {"column": hit.name, "scale": 100} if ratio else hit.name
        menu.kinds[fid] = "continuous"
        menu.notes[fid] = hit.note + (" -> shown as percent" if ratio else "")
        used.add(hit.name)
    menu.unmapped = [c for c in cols if c.name not in used]
    return menu


# ---------------------------------------------------------------- what the data looks like
def guess_platform(
    columns: list[str], n_obs: int, *, spatial: bool, array_extent: tuple[float, float] | None = None, n_areas: int = 1
) -> tuple[str, str | None]:
    """The platform a file most likely came from, and the evidence (None when nothing said anything and the
    answer is the default). SpaceRanger's grid columns mean Visium when the array coordinates fit one Visium
    array or the spots split into capture areas of Visium size (stitched donors), and Visium HD when the grid
    is larger or there are more observations than a capture area holds; Xenium's cell metrics mean cells;
    otherwise Visium. `array_extent` is (max array_row, max array_col); `n_areas` the number of capture areas."""
    if not spatial:
        return "snrnaseq", "no spatial coordinates"
    cols = {str(c).lower() for c in columns}
    grid = sorted(cols & ARRAY_COLUMNS)
    if grid:
        g = ", ".join(grid)
        if n_areas > 1 and n_obs / n_areas <= VISIUM_MAX_OBS:
            return "visium", f"{g} columns; {n_areas} capture areas of {n_obs / n_areas:,.0f} spots"
        if array_extent is not None:
            r, c = array_extent
            if r <= VISIUM_ARRAY[0] and c <= VISIUM_ARRAY[1]:
                return "visium", f"{g} columns, array {r:.0f} x {c:.0f} fits one Visium array"
            return "visium_hd", f"{g} columns, array {r:.0f} x {c:.0f} is larger than one Visium array (stitched Visium without a capture_area column: set visium)"
        if n_obs > VISIUM_MAX_OBS:
            return "visium_hd", f"{g} columns and {n_obs:,} observations, more than a Visium capture area holds"
        return "visium", f"{g} columns"
    cells = sorted(cols & CELL_COLUMNS)
    if len(cells) >= 2:
        return "xenium", f"{', '.join(cells)} columns"
    if n_obs > VISIUM_MAX_OBS:
        return "xenium", f"{n_obs:,} observations and no array_row / array_col: cells, not spots (Visium HD cells: set visium_hd)"
    return "visium", None


def grid_evidence(obs: pd.DataFrame) -> dict:
    """What `guess_platform` wants to know about SpaceRanger grids: the array extent and the number of capture areas."""
    out: dict = {}
    if "array_row" in obs.columns and "array_col" in obs.columns:
        r = pd.to_numeric(obs["array_row"], errors="coerce").max()
        c = pd.to_numeric(obs["array_col"], errors="coerce").max()
        if np.isfinite(r) and np.isfinite(c):
            out["array_extent"] = (float(r), float(c))
    for col in obs.columns:
        if AREA_COLUMN_RE.match(str(col)):
            out["n_areas"] = max(out.get("n_areas", 1), int(obs[col].nunique(dropna=True)))
    return out


def constant_columns(obs: pd.DataFrame, sample_col: str | None, *, skip: set[str] | None = None) -> list[tuple[str, str]]:
    """Columns that hold one value per sample and several across samples (condition, sex, age group): sample-level
    properties, offered as `meta:` rather than as annotations. With no sample column the frame is one sample, and
    a column with a single value is the candidate."""
    skip = set(skip or ())
    out: list[tuple[str, str]] = []
    groups = obs.groupby(sample_col, observed=True) if sample_col and sample_col in obs.columns else None
    for col in obs.columns:
        name = str(col)
        if name == sample_col or name in skip or SKIP_COLUMNS.match(name):
            continue
        s = obs[col]
        if not (is_textual(s) or pd.api.types.is_numeric_dtype(s)):
            continue
        vals = [str(v) for v in pd.unique(s.dropna().astype(str))]
        if groups is not None:
            if not len(vals) or len(vals) > MAX_MENU_LEVELS or len(vals) < 2 or int(groups[col].nunique(dropna=True).max()) > 1:
                continue
            out.append((name, f"constant within each sample: {_join(vals, 4)}"))
        elif len(vals) == 1 and len(s) > 1:
            out.append((name, f"one value in this file: {vals[0]}"))
    return out


def sections_in(obs: pd.DataFrame) -> tuple[str, list[str]] | None:
    """A column that splits one file into several sections (sample_id, capture_area, ...), with its values."""
    for col in obs.columns:
        if SAMPLE_COLUMN_RE.match(str(col)):
            vals = [str(v) for v in pd.unique(obs[col].dropna().astype(str))]
            if 2 <= len(vals) <= MAX_MENU_LEVELS:
                return str(col), vals
    return None


# ---------------------------------------------------------------- one entry per argument
@dataclass
class EntryMenu:
    source: str  # path or glob, relative to the yaml
    source_note: str
    r_object: bool
    embedding: bool
    platform: str
    id_tpl: str
    name_tpl: str
    group_tpl: str
    menu: Menu
    samples: list[str] = field(default_factory=list)
    assay: str | None = None
    assays: list[str] = field(default_factory=list)
    fragments: dict[str, str] = field(default_factory=dict)  # Seurat: run -> fragment file recorded in the object
    sample_col: str | None = None
    embedding_key: str | None = None
    embeddings: list[str] = field(default_factory=list)
    table: str | None = None
    platform_note: str = ""  # how the platform was chosen: given, guessed from ..., or the default
    layers: list[str] = field(default_factory=list)  # other layers in the file (files only)
    sections: tuple[str, list[str]] | None = None  # one file that holds several sections: (column, values)
    n_obs: int | None = None
    meta_candidates: list[tuple[str, str]] = field(default_factory=list)  # obs columns constant within a sample: (column, note)
    layer_files: dict[str, str] = field(default_factory=dict)  # yaml key -> path template of a layer table found next to the matrix

    @property
    def assumed(self) -> list[str]:
        """What `init` took for granted about this entry, one line each, for the terminal."""
        plat = f"{self.platform} ({self.platform_note})" if self.platform_note else self.platform
        if self.embedding:
            coords = COORDINATE_NOTE["snrnaseq"]
        else:
            coords = COORDINATE_NOTE.get(self.platform, COORDINATE_NOTE["other"])
        if self.r_object:
            expr = f"assay {self.assay}" + (f" (also: {', '.join(a for a in self.assays if a != self.assay)})" if len(self.assays) > 1 else "")
        else:
            expr = "X" + (f" (layers not drawn: {', '.join(self.layers)})" if self.layers else "")
        expr += "; counts are log-normalized by build, anything else is taken as already log-normalized"
        out = [f"platform: {plat}", f"coordinates: {coords}", f"expression: {expr}"]
        m = self.menu
        if m.mapped:
            parts = []
            for fid, v in m.mapped.items():
                col = v if isinstance(v, str) else v["column"]
                note = m.notes.get(fid, "")
                levels = re.match(r"(\d+ levels)", note)
                na = re.search(r"([\d,]+ NA)$", note)
                extra = ", ".join(x for x in ((levels.group(1) if levels else ""), (na.group(1) if na else "")) if x)
                parts.append(f"{fid} <- {col}" + (f" ({extra})" if extra else ""))
            out.append("annotations: " + ", ".join(parts))
        else:
            out.append("annotations: none mapped (every column is listed as a comment)")
        if self.sections:
            col, vals = self.sections
            out.append(f"sections: {len(vals)} in one file ({col}: {_join(vals, 4)}), drawn as one sample; `subset:` splits them")
        if self.layer_files:
            what = {key: name for name, (key, _w, _n) in LAYER_FILES.items()}
            out.append("layers: " + ", ".join(f"{LAYER_FILES[what[k]][1]} from {what[k]}" for k in self.layer_files))
        if self.meta_candidates:
            out.append("sample metadata: " + ", ".join(c for c, _ in self.meta_candidates[:6]) + (", ..." if len(self.meta_candidates) > 6 else "") + " look constant within each sample; listed as a `# meta:` line to split the view by")
        return out


@dataclass
class ComparisonMenu:
    """One `comparisons:` entry proposed from a results table."""

    source: str  # path relative to the yaml
    id: str
    name: str
    columns: dict[str, str]  # role -> column taken
    n_rows: int
    groups: list[str] | None  # from a `<case>_vs_<reference>` file name
    other_columns: list[str]
    kind: str = "contrast"  # markers: every level of the facet column against the rest
    facet: str | None = None  # the column whose levels are separate contrasts
    n_levels: int = 0

    @property
    def assumed(self) -> list[str]:
        taken = ", ".join(f"{role} <- {col}" for role, col in self.columns.items())
        out = [f"{'markers' if self.kind == 'markers' else 'comparison'} {self.id}: {taken}{'' if 'effect' in self.columns else '; a ranked list, kept in file order'}; {self.n_rows:,} rows"]
        if self.facet:
            out.append(f"levels: {self.n_levels} of {self.facet!r}" + (", each against the rest" if self.kind == "markers" else ", one contrast each"))
        if self.kind == "markers":
            return out
        out.append(f"groups: {', '.join(self.groups)} (from the file name; the contrast is the last against the first)" if self.groups else "groups: not in the file name; set `groups:` or give a replicate sheet")
        out.append("replicate values: none yet; add `pseudobulk:` (genes x replicates) for the dots per mouse or donor")
        return out


VS_RE = re.compile(r"(?i)(?:^|[^a-z0-9])([a-z0-9]+)[_.-]?vs[_.-]?([a-z0-9]+)(?:$|[^a-z0-9])")


def _table_entry(path: Path, base: Path, log: Log) -> ComparisonMenu:
    from .comparisons import detect_facet

    df = read_table(path)
    cols = map_columns(df, RESULT_ROLES, {}, what=str(path.name))
    cands = gene_candidates(df, cols)
    stem = path.name.rsplit(".", 1)[0]
    facet = detect_facet(df, cands[0], None, markers="marker" in stem.lower()) if cands else None
    stats = "effect" in cols and ("p" in cols or "padj" in cols)
    if not cands or (not stats and facet is None):
        raise ValueError(f"{path.name} does not look like a results table: it needs a gene column, an effect column (log2FoldChange, logFC, avg_log2FC, ...) and a p-value column (pvalue, padj, FDR, ...), or a cluster column next to the genes for a marker list; columns: {', '.join(map(str, df.columns))}")
    cols["gene"] = cands[0]
    kind = "markers" if facet is not None and (not stats or "marker" in stem.lower()) else "contrast"
    taken = {role: cols[role] for role in ("gene", "effect", "p", "padj", "mean", "pct_in", "pct_out") if role in cols and cols[role] != facet}
    cid = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("_").lower() or "comparison"
    m = VS_RE.search(stem)
    groups = [m.group(2), m.group(1)] if m and kind == "contrast" else None  # stress_vs_control -> [control, stress]
    name = f"{m.group(1).capitalize()} vs {m.group(2)}" if m and kind == "contrast" else stem.replace("_", " ")
    n_levels = int(df[facet].nunique()) if facet else 0
    log(f"{path.name}: {len(df):,} rows; " + ", ".join(f"{r} <- {c}" for r, c in taken.items()) + ("" if stats else "; a ranked list, kept in file order") + (f"; {n_levels} levels of {facet!r}" if facet else ""))
    return ComparisonMenu(source=_rel(path, base), id=cid, name=name, columns=taken, n_rows=len(df), groups=groups, other_columns=[str(c) for c in df.columns if str(c) not in taken.values() and str(c) != facet], kind=kind, facet=facet, n_levels=n_levels)


def _comparison_lines(c: ComparisonMenu) -> list[str]:
    L: list[str] = []
    L.append(f"  - id: {_ystr(c.id)}")
    if c.kind == "markers":
        L.append(_pad("    kind: markers", "each level against the rest; no replicates, no split"))
    L.append(f"    name: {_ystr(c.name)}")
    L.append(_pad(f"    results: {_ystr(c.source)}", f"{c.n_rows:,} rows; " + (", ".join(f"{r} <- {col}" for r, col in c.columns.items()) or "a ranked list, kept in file order")))
    if c.facet:
        L.append(_pad(f"    facet: {{ column: {_ystr(c.facet)} }}", f"{c.n_levels} levels, one contrast each; add `field: <annotation>` when its categories are not matched on their own"))
    if c.kind == "markers":
        L.append(_pad('    # description: "Wilcoxon, each cluster against the rest"', "shown verbatim in the panel"))
        if c.other_columns:
            L.append(f"    # other columns in the table: {_join(c.other_columns, 6)}")
        return L
    if c.groups:
        L.append(_pad(f"    groups: [{', '.join(_ystr(g) for g in c.groups)}]", "from the file name; the contrast is the last against the first"))
    else:
        L.append(_pad("    # groups: [control, case]", "plotting and pane order; the contrast is the last against the first"))
    L.append(_pad("    # pseudobulk: de/pseudobulk.csv", "genes x replicates (first column the gene): the dots per mouse or donor"))
    L.append(_pad("    # replicates: de/replicates.csv", "one row per replicate: id, group, subject; needed when the samples' meta cannot supply them"))
    L.append(_pad('    # description: "limma-voom on per-mouse pseudobulk, ~ condition + sex; positive effect = higher in the last group"', "shown verbatim in the panel"))
    L.append(_pad("    # units: log2 CPM", "axis label of the replicate values"))
    L.append(_pad("    # population: { field: celltype, value: D1 MSN }", "the cells the test was fit in; selecting the comparison filters the map to them"))
    L.append(_pad("    # split: condition", "the sample meta key whose levels are the groups (found by matching when left out)"))
    if c.other_columns:
        L.append(f"    # other columns in the table: {_join(c.other_columns, 6)}")
    return L


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name))


def _rel(path: str | Path, base: Path) -> str:
    return os.path.relpath(os.path.abspath(os.path.expanduser(str(path))), base)


def _join(names: list[str], k: int = 6) -> str:
    if len(names) <= k + 1:
        return ", ".join(names)
    return ", ".join(names[:k]) + f", ... ({len(names)} in all)"


def _r_entry(path: Path, platform: str | None, base: Path, log: Log) -> EntryMenu:
    from .rds import read_experiment

    log(f"reading {path} (the whole object is parsed; about as long as loading it in R)")
    x = read_experiment(path)
    cols = describe_columns(x.obs)
    assay = next((k for k in ("logcounts", "data") if k in x.assays), next(iter(x.assays)))
    if x.class_name == "SpatialExperiment" and x.spatial is not None:
        sample_col = "sample_id"
        if sample_col in x.obs.columns:
            samples = [str(v) for v in pd.unique(x.obs[sample_col].astype(str))]
            note = f"{x.class_name}, {len(samples)} sample{'s' if len(samples) != 1 else ''}: {_join(samples)} (one sample per {sample_col})"
        else:
            samples = []
            note = f"{x.class_name}, {x.n_obs:,} cells; no sample_id column: set sample_col below"
            log(f"warning: {path.name} has no `sample_id` column; set `sample_col:` in the yaml to the column that separates samples")
        plat, plat_note = _platform_choice(platform, x.obs, spatial=True)
        prefix, label = PLATFORM_PREFIX.get(plat, plat[:3]), PLATFORM_LABEL.get(plat, plat)
        meta_c = constant_columns(x.obs, sample_col) if len(samples) > 1 else []
        return EntryMenu(
            source=_rel(path, base), source_note=note, r_object=True, embedding=False, platform=plat,
            id_tpl=f"{prefix}_{{name}}", name_tpl=f"{{name}} ({label})", group_tpl="{name}",
            menu=suggest_fields(cols, skip={sample_col, *(c for c, _ in meta_c)}), samples=[_safe(s) for s in samples],
            assay=assay, assays=list(x.assays), sample_col=sample_col, platform_note=plat_note, n_obs=x.n_obs, meta_candidates=meta_c,
        )
    from .convert import pick_embedding

    emb = pick_embedding(x.reduced_dims)
    stem = _safe(path.stem)
    note = f"{x.class_name}, {x.n_obs:,} cells; embedding {emb or 'none found'} -> obsm/X_umap"
    if x.feature_sets:
        note += "; also " + ", ".join(f"{fs.name} as {fs.prefix.strip()} features" for fs in x.feature_sets)
    return EntryMenu(
        source=_rel(path, base), source_note=note, r_object=True, embedding=True, platform="snrnaseq",
        id_tpl=f"sn_{stem}", name_tpl=f"snRNA-seq ({stem})", group_tpl="snRNA-seq",
        menu=suggest_fields(cols), samples=[stem], assay=assay, assays=list(x.assays),
        embedding_key=emb, embeddings=list(x.reduced_dims), fragments={f.run: f.path for f in x.fragments},
        platform_note="no spatialCoords in the object", n_obs=x.n_obs,
    )


def _platform_choice(given: str | None, obs: pd.DataFrame, *, spatial: bool) -> tuple[str, str]:
    if given:
        return given, "given"
    plat, why = guess_platform(list(obs.columns), len(obs), spatial=spatial, **grid_evidence(obs))
    return plat, f"guessed from {why}" if why else "the default; nothing in the columns said otherwise"


def layer_files_near(path: Path) -> dict[str, str]:
    """Boundary and transcript tables in the matrix file's folder or the one above, as `{dir}` templates so a glob
    entry finds each match's own: yaml key -> path."""
    d = path if path.is_dir() and not (path / ".zattrs").exists() and not (path / "zarr.json").exists() else path.parent
    out: dict[str, str] = {}
    for folder, prefix in ((d, "{dir}"), (d.parent, "{dir}/..")):
        for name, (key, _what, _note) in LAYER_FILES.items():
            if key not in out and (folder / name).is_file():
                out[key] = f"{prefix}/{name}"
    return out


def _glob_entry(pattern: str, platform: str | None, table: str | None, base: Path, log: Log) -> EntryMenu:
    from .readers import peek

    matches = sorted(_glob.glob(os.path.expanduser(pattern), recursive=True))
    cols: list[Column] = []
    layers: list[str] = []
    sections = None
    n_obs = None
    meta_c: list[tuple[str, str]] = []
    layer_files: dict[str, str] = {}
    if matches:
        layer_files = layer_files_near(Path(matches[0]))
        pk = peek(Path(matches[0]), table)
        cols = describe_columns(pk.obs)
        layers = list(pk.layers)
        n_obs = len(pk.obs)
        plat, plat_note = _platform_choice(platform, pk.obs, spatial="spatial" in pk.obsm)
        if plat != "snrnaseq":
            sections = sections_in(pk.obs)
        if sections is None and len(matches) > 1:
            meta_c = constant_columns(pk.obs, None)  # one sample per file: a single-valued column is a sample property
    else:
        log(f"warning: {pattern!r} matches nothing right now; the fields menu is empty and ids come from the files present at build time")
        plat, plat_note = (platform, "given") if platform else ("visium", "the default; no file to look at yet")
    embedding = plat == "snrnaseq"
    if sections:
        col, vals = sections
        log(f"warning: {Path(matches[0]).name} holds {len(vals)} sections ({col}: {_join(vals, 4)}); one entry draws them as one sample. To split them, list the file once per section with `subset: {{ column: {col}, values: [{vals[0]}] }}`")
    # `{name}` is the parent folder (right for `<sample>/adata.h5ad`); `{stem}` is the file or store name
    # (right for `samples/<sample>.h5ad`). Pick whichever carries the sample name.
    stems = {Path(m).name.split(".")[0].lower() for m in matches}
    var = "{name}" if matches and stems <= GENERIC_STORE_NAMES else "{stem}"
    names = [_sample_folder(Path(m)).name if var == "{name}" else Path(m).name.split(".")[0] for m in matches]
    note = "one sample per match; {name} = parent folder, {stem} = file or store name" + (f"; now {len(matches)}: {_join(names, 4)}" if matches else "; matches nothing yet")
    prefix, label = PLATFORM_PREFIX.get(plat, plat[:3]), PLATFORM_LABEL.get(plat, plat)
    return EntryMenu(
        source=_rel(pattern, base), source_note=note, r_object=False, embedding=embedding, platform=plat,
        id_tpl=f"{prefix}_{var}", name_tpl=f"{var} ({label})", group_tpl="snRNA-seq" if embedding else var,
        menu=suggest_fields(cols, skip={c for c, _ in meta_c}), samples=names, table=table, platform_note=plat_note, layers=layers, sections=sections, n_obs=n_obs,
        meta_candidates=meta_c, layer_files=layer_files if plat != "snrnaseq" else {},
    )


# ---------------------------------------------------------------- rendering
YAML_PLAIN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_ ./()+%-]*[A-Za-z0-9_.)%]")
YAML_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~"}


def _ystr(s: str) -> str:
    """A YAML scalar: plain when it is unambiguous, double-quoted otherwise (templates, colons, hashes)."""
    plain = (len(s) == 1 and s.isalnum()) or (YAML_PLAIN.fullmatch(s) is not None and ": " not in s and " #" not in s)
    if plain and s.lower() not in YAML_RESERVED:
        try:  # numbers, dates, octal: YAML would type them, so they need quotes
            if yaml.safe_load(s) == s:
                return s
        except yaml.YAMLError:
            pass
    return json.dumps(s, ensure_ascii=False)


def _pad(text: str, comment: str, width: int = 44) -> str:
    if not comment:
        return text
    return f"{text:<{width}} # {comment}" if len(text) < width else f"{text}   # {comment}"


def _entry_lines(e: EntryMenu) -> list[str]:
    L: list[str] = []
    L.append(_pad(f"  - {'path' if e.r_object else 'glob'}: {_ystr(e.source)}", e.source_note))
    others = ", ".join(p for p in ("visium", "visium_hd", "xenium", "merfish") if p != e.platform)
    L.append(_pad(f"    platform: {e.platform}", "" if e.embedding else f"{e.platform_note}; or {others}"))
    if e.embedding:
        L.append("    kind: embedding")
        if not e.r_object:
            L.append(_pad("    coords: obsm/X_umap", "the 2-D embedding to draw"))
    if e.table:
        L.append(f"    table: {_ystr(e.table)}")
    if e.r_object:
        others = [a for a in e.assays if a != e.assay]
        L.append(_pad(f"    assay: {_ystr(e.assay or 'logcounts')}", f"drawn as expression; also in the object: {', '.join(others)}" if others else "drawn as expression"))
        if e.embedding:
            others = [k for k in e.embeddings if k != e.embedding_key]
            L.append(_pad(f"    # embedding: {e.embedding_key or 'UMAP'}", "reducedDims entry to draw" + (f"; also: {', '.join(others)}" if others else "")))
        else:
            L.append(_pad(f"    # sample_col: {e.sample_col or 'sample_id'}", "colData column that splits the object into samples"))
            L.append(_pad("    # microns: { microns_per_unit: 0.2525 }", "Visium HD: SpaceRanger's microns_per_pixel. Visium is inferred from the spot spacing"))
    id_note = "" if e.embedding else ("{name} = the sample_id value" if e.r_object else "")
    L.append(_pad(f"    id: {_ystr(e.id_tpl)}", id_note))
    L.append(f"    name: {_ystr(e.name_tpl)}")
    L.append(f"    group: {_ystr(e.group_tpl)}")
    notes = {key: note for _name, (key, _what, note) in LAYER_FILES.items()}
    for key, tpl in e.layer_files.items():
        L.append(_pad(f"    {key}: {{ path: {_ystr(tpl)} }}", notes[key]))
    if not e.layer_files and not e.r_object and not e.embedding and e.platform in IMAGING_PLATFORMS:
        L.append(_pad("    # polygons: { path: cell_boundaries.parquet, id_column: cell_id, x_column: vertex_x, y_column: vertex_y }", "cell shapes from a long table (Parquet, CSV or TSV)"))
        L.append(_pad("    # molecules: { path: transcripts.parquet, feature_column: feature_name, x_column: x_location, y_column: y_location }", "transcripts; column names per platform in the imaging-based guide"))
    m = e.menu
    if m.mapped:
        L.append(_pad("    fields:", "field id: column. Delete a line to hide an annotation, uncomment one to add it"))
        for fid, v in m.mapped.items():
            val = _ystr(v) if isinstance(v, str) else f"{{ column: {_ystr(v['column'])}, scale: {v['scale']:g} }}"
            L.append(_pad(f"      {fid}: {val}", m.notes.get(fid, "")))
        for fid, c in m.alternatives:
            L.append(_pad(f"      # {fid}: {_ystr(c.name)}", f"alternative; {c.note}"))
        for c in m.unmapped:
            L.append(_pad(f"      # {field_id(c.name)}: {_ystr(c.name)}", c.note))
    else:
        L.append(_pad("    # fields:", "uncomment this line and the columns to show as annotations"))
        for c in m.unmapped:
            L.append(_pad(f"    #   {field_id(c.name)}: {_ystr(c.name)}", c.note))
    if e.meta_candidates:
        inner = ", ".join(f"{field_id(c)}: {{ column: {_ystr(c)} }}" for c, _ in e.meta_candidates[:4])
        L.append(_pad(f"    # meta: {{ {inner} }}", "sample-level properties (one value per sample); the viewer splits the canvas by them"))
        for c, note in e.meta_candidates:
            L.append(f"    #   {field_id(c)}: {note}")
    if m.skipped:
        L.append(f"    # not listed: {', '.join(m.skipped)} (ids and layout columns)")
    if e.sections:
        col, vals = e.sections
        L.append(_pad(f"    # subset: {{ column: {_ystr(col)}, values: [{_ystr(vals[0])}] }}", f"this file holds {len(vals)} sections ({_join(vals, 4)}); one entry per section splits them"))
    if e.fragments:
        L.append(_pad("    # tracks:", "genome tracks from the fragment files the object was built from (paths as recorded in it)"))
        L.append("    #   fragments:")
        for run, path in e.fragments.items():
            L.append(f"    #     {_ystr(run)}: {_ystr(path)}")
        L.append(_pad("    #   sample_column: fragment_run", "written by the converter from the object's Fragment records"))
        L.append("    #   barcode_column: fragment_barcode")
        first_cat = next((fid for fid, kind in e.menu.kinds.items() if kind == "categorical"), "<a categorical field>")
        L.append(_pad(f"    #   by: [{first_cat}]", "one track per category"))
        L.append("    #   genome: hg38")
    return L


def _pretty(fid: str) -> str:
    if fid in FIELD_NAMES:
        return FIELD_NAMES[fid]
    s = re.sub(r"[_\.]+", " ", fid).strip()
    return s[:1].upper() + s[1:]


def render_dataset_yaml(*, dataset_id: str, name: str, entries: list[EntryMenu], comparisons: list[ComparisonMenu] | None = None) -> str:
    fields: dict[str, str] = {}
    for e in entries:
        for fid, kind in e.menu.kinds.items():
            fields.setdefault(fid, kind)
    color_field = next((f for f in ("domain", "celltype") if f in fields), next((f for f, k in fields.items() if k == "categorical"), None))
    spatial = [e for e in entries if not e.embedding]
    thumb = f"{spatial[0].id_tpl.replace('{name}', spatial[0].samples[0]).replace('{stem}', spatial[0].samples[0])}" if spatial and spatial[0].samples else "<sample id>"
    L = [
        "# dataset.yaml for spatialscape. Lines starting with # are optional settings; uncomment them to use them.",
        f"# What to edit for which change: {GUIDE}",
        f"id: {_ystr(dataset_id)}",
        f"name: {_ystr(name)}",
        "# description: One sentence for the gallery card.",
        _pad("# default_gene: SNAP25", "gene shown on open (default: the most variable gene)"),
        _pad(f"default_color: {{ field: {color_field} }}" if color_field else "# default_color: { field: domain }", "annotation shown on open; or { gene: SNAP25 }"),
        _pad("# palette: colors.json", '{ "domain": { "L1": "#F0027F", ... } }; a field uses it through palette_key'),
        _pad(f"# thumbnail_sample: {thumb}", "section drawn on the gallery card (default: the first)"),
        _pad("layout: { mode: grid }", "or strip; gutter_fraction: 0.1 spaces sections out"),
        "",
    ]
    if fields:
        L += [
            "# Annotation names. Each id is mapped to a column under samples below. Add palette_key (block in the palette",
            "# file), aliases (merge spellings: { AI: IA }) or categories (a fixed order) to an entry when you need them.",
            "fields:",
        ]
        L += [f"  - {{ id: {fid}, name: {_ystr(_pretty(fid))}, type: {kind} }}" for fid, kind in fields.items()]
    else:
        L += [
            "# Annotation names, once some columns are mapped under samples below:",
            "# fields:",
            "#   - { id: domain, name: Spatial domain, type: categorical, palette_key: domain }",
        ]
    cands: dict[str, None] = {}
    for e in entries:
        for c, _ in e.meta_candidates:
            cands.setdefault(field_id(c), None)
    if cands:
        L += [
            "# Sample metadata keys (names and level order), once `meta:` is set under samples below:",
            "# meta:",
            *[f"#   - {{ id: {k}, name: {_ystr(_pretty(k))} }}" for k in cands],
        ]
    L += ["", "samples:"]
    for e in entries:
        L += _entry_lines(e)
    if comparisons:
        L += ["", _pad("comparisons:", "differential expression fit upstream, linked to the sections; see the guide")]
        for c in comparisons:
            L += _comparison_lines(c)
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- the command
@dataclass
class MenuResult:
    out: Path
    dataset_id: str
    entries: list[EntryMenu]
    comparisons: list[ComparisonMenu] = field(default_factory=list)

    @property
    def samples(self) -> list[str]:
        return [s for e in self.entries for s in e.samples]

    @property
    def mapped(self) -> list[str]:
        seen: dict[str, None] = {}
        for e in self.entries:
            for fid in e.menu.mapped:
                seen.setdefault(fid, None)
        return list(seen)

    @property
    def commented(self) -> int:
        return sum(len(e.menu.unmapped) + len(e.menu.alternatives) for e in self.entries)


def default_id(first: str) -> str:
    """A dataset id from the first argument: the R object's stem, or the folder a glob starts in."""
    if is_r_object(first) or is_table(first):
        base = Path(first).stem
    else:
        parts = Path(os.path.expanduser(first)).parts
        wild = next((i for i, x in enumerate(parts) if any(ch in x for ch in "*?[")), None)
        if wild is None:
            base = Path(first).name.split(".")[0]
        elif wild == 0:
            base = Path.cwd().name
        else:
            base = parts[wild - 1]
    return re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_").lower() or "my_dataset"


def write_menu(
    paths: list[str],
    *,
    out: Path | None = None,
    dataset_id: str | None = None,
    name: str | None = None,
    platform: str | None = None,
    table: str | None = None,
    log: Log = print,
) -> MenuResult:
    if platform is not None and platform not in PLATFORM_LABEL:
        raise ValueError(f"unknown platform {platform!r}; one of {', '.join(PLATFORM_LABEL)}")
    dataset_id = dataset_id or default_id(paths[0])
    name = name or (dataset_id.replace("_", " ")[:1].upper() + dataset_id.replace("_", " ")[1:])
    out = (Path(out) if out is not None else Path(f"{dataset_id}.yaml")).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    base = out.parent.resolve()
    entries: list[EntryMenu] = []
    comparisons: list[ComparisonMenu] = []
    for p in paths:
        if is_r_object(p):
            path = Path(p).expanduser()
            if not path.exists():
                raise FileNotFoundError(str(path))
            entries.append(_r_entry(path, platform, base, log))
        elif is_table(p):
            path = Path(p).expanduser()
            if not path.exists():
                raise FileNotFoundError(str(path))
            comparisons.append(_table_entry(path, base, log))
        else:
            entries.append(_glob_entry(p, platform, table, base, log))
    if not entries:
        raise ValueError("init needs at least one sample source (an R object or a glob of files) besides results tables")
    out.write_text(render_dataset_yaml(dataset_id=dataset_id, name=name, entries=entries, comparisons=comparisons))
    return MenuResult(out=out, dataset_id=dataset_id, entries=entries, comparisons=comparisons)
