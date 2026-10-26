"""Comparisons: results of differential expression tests fit upstream (DESeq2, limma, edgeR, Seurat, pyDESeq2, ...),
with the replicate-level values behind them, written into the bundle so the viewer can link a gene's statistics to
the replicates and to the sections. Nothing statistical is computed here: the tables are read, their columns
recognised, their genes matched to the bundle, their replicates linked to samples through the samples' metadata,
and the result stored in a form the viewer reads in one request per table.

    comparisons/<id>/comparison.json   what it is: groups, replicates and their sections, counts, columns taken
    comparisons/<id>/results.json      column arrays (genes, effect, p, padj, mean), rows sorted by padj then |effect|
    comparisons/<id>/pseudobulk.zarr   float32 (genes, replicates) in results order, zstd, chunked by 1024 genes
    comparisons/<id>/build.json        fingerprint of the inputs and settings (rebuilt only when one changed)
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ComparisonSpec, DatasetConfig
from .fingerprint import _stat, read_sidecar
from .manifest import ComparisonInfo, FacetInfo, LevelInfo, MetaKey, PopulationInfo, Sample

Log = Callable[[str], None]

COMPARISONS_RECIPE = 3  # 2: every comparison is one or more levels under levels/<id>/; 3: + matrix.zarr (genes x levels)
LEVEL_TOKEN = "{level}"
MAX_LEVELS = 500
TABLE_SUFFIXES = (".csv", ".tsv", ".txt", ".parquet")
PSEUDOBULK_CHUNK = 1024

# Column names recognised for each role, tried in order (case-insensitive). The first table-specific spellings are
# DESeq2 / limma / edgeR / Seurat FindMarkers / pyDESeq2 / scanpy rank_genes_groups.
RESULT_ROLES: dict[str, list[str]] = {
    "gene": ["gene", "genes", "gene_name", "symbol", "gene_symbol", "feature", "features", "names", "gene_id", "gene_ids", "ensembl_id", "ensembl"],
    "effect": ["log2FoldChange", "logFC", "avg_log2FC", "log2fc", "log2_fold_change", "logfoldchanges", "summary.logFC", "mean_logFC", "estimate", "beta", "coef", "effect"],
    "p": ["pvalue", "p_value", "P.Value", "p.value", "p_val", "PValue", "pvals", "pval", "p"],
    "padj": ["padj", "adj.P.Val", "FDR", "p_val_adj", "pvals_adj", "q_value", "qvalue", "fdr", "p_adj", "adj_p", "qval"],
    "mean": ["baseMean", "AveExpr", "logCPM", "base_mean", "avg_expr", "mean_expression", "avgExpr", "mean"],
    "pct_in": ["pct.1", "pct_in", "pct_nz_group", "pct.in", "pct_group", "pct_1"],
    "pct_out": ["pct.2", "pct_out", "pct_nz_reference", "pct.out", "pct_reference", "pct_2"],
    "score": ["scores", "score", "statistic", "auc", "stat", "t", "z", "Top"],
}
# Columns whose levels split a table into one contrast each. The strong names are taken as a facet whenever they
# are present; the weak ones only when gene names repeat (a plain DESeq2 table may carry a constant `contrast`).
FACET_STRONG = ["cluster", "clusters", "celltype", "cell_type", "cell type", "population", "domain"]
FACET_WEAK = ["group", "contrast", "comparison", "level", "ident"]
REPLICATE_ROLES: dict[str, list[str]] = {
    "id": ["id", "replicate", "sample", "sample_id", "sample_name", "subject", "donor", "mouse", "animal", "name"],
    "group": ["group", "condition", "treatment", "genotype", "diagnosis", "dx", "contrast", "arm"],
    "subject": ["subject", "donor", "mouse", "animal", "pair", "individual", "patient"],
}
UNNAMED = re.compile(r"^(|Unnamed: 0|X|\.\.\.1|index|rownames)$")  # how R's write.csv / pandas spell row names


def is_table(path: object) -> bool:
    return isinstance(path, (str, Path)) and str(path).lower().endswith(TABLE_SUFFIXES)


def read_table(path: Path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".tsv":
        return pd.read_csv(path, sep="\t")
    with open(path, newline="") as fh:
        head = fh.readline()
    sep = "\t" if head.count("\t") > head.count(",") else ","
    return pd.read_csv(path, sep=sep)


def find_column(df: pd.DataFrame, names: list[str]) -> str | None:
    """The first of `names` present in the frame, matched without regard to case."""
    lower = {str(c).lower(): str(c) for c in df.columns}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def map_columns(df: pd.DataFrame, roles: dict[str, list[str]], overrides: dict[str, str], *, what: str) -> dict[str, str]:
    """role -> column, from the overrides first and the recognised names next; an override that names no column is an error."""
    out: dict[str, str] = {}
    for role, names in roles.items():
        if role in overrides:
            col = overrides[role]
            if col not in df.columns:
                raise KeyError(f"{what}: column {col!r} (for {role}) is not in the table; columns: {', '.join(map(str, df.columns))}")
            out[role] = col
        else:
            hit = find_column(df, names)
            if hit is not None and hit not in out.values():
                out[role] = hit
    return out


def gene_candidates(df: pd.DataFrame, mapped: dict[str, str]) -> list[str]:
    """Columns that may hold gene names: the recognised ones, an unnamed first column (R row names), and, when
    nothing is named like a gene column, a first column that holds text."""
    out: list[str] = []
    if "gene" in mapped:
        out.append(mapped["gene"])
    lower = {str(c).lower(): str(c) for c in df.columns}
    for n in RESULT_ROLES["gene"]:
        if n.lower() in lower and lower[n.lower()] not in out:
            out.append(lower[n.lower()])
    first = str(df.columns[0])
    if first not in out and (UNNAMED.match(first) or (not out and not pd.api.types.is_numeric_dtype(df[df.columns[0]]))):
        out.append(first)
    return out


def bh_sorted_order(res: pd.DataFrame) -> np.ndarray:
    """Row order for the table: padj ascending (missing last), then p, then the larger |effect| first."""
    padj = res["padj"].to_numpy(dtype=float) if "padj" in res else np.full(len(res), np.nan)
    p = res["p"].to_numpy(dtype=float) if "p" in res else np.full(len(res), np.nan)
    eff = -np.abs(res["effect"].to_numpy(dtype=float))
    key = [np.nan_to_num(eff, nan=0.0), np.where(np.isnan(p), np.inf, p), np.where(np.isnan(padj), np.inf, padj)]
    return np.lexsort(key)


def level_paths(path: Path | str | None) -> dict[str, Path] | None:
    """A `{level}` template expanded against the files present: level -> path, sorted; None for a plain path."""
    if path is None or LEVEL_TOKEN not in str(path):
        return None
    head, tail = str(path).split(LEVEL_TOKEN, 1)
    out: dict[str, Path] = {}
    for m in sorted(glob.glob(glob.escape(head) + "*" + glob.escape(tail))):
        if m.startswith(head) and m.endswith(tail) and len(m) > len(head) + len(tail):
            out[m[len(head) : len(m) - len(tail)]] = Path(m)
    return out


def source_paths(spec: ComparisonSpec) -> list[Path]:
    """Every file a comparison reads, templates expanded."""
    out: list[Path] = []
    for p in (spec.results, spec.pseudobulk, spec.replicates):
        if p is None:
            continue
        lp = level_paths(p)
        out.extend(lp.values() if lp is not None else [Path(p)])
    return out


def detect_facet(df: pd.DataFrame, gene_col: str, given: str | None, *, markers: bool) -> str | None:
    """The column whose levels split the table, if any: the one named in the yaml, else a recognised name."""
    if given:
        if given not in df.columns:
            raise KeyError(f"facet column {given!r} is not in the table; columns: {', '.join(map(str, df.columns))}")
        return given
    repeats = bool(df[gene_col].duplicated().any())
    for n in FACET_STRONG + FACET_WEAK:
        c = find_column(df, [n])
        if c is None or c == gene_col:
            continue
        k = int(df[c].nunique(dropna=True))
        if not (1 <= k <= MAX_LEVELS):
            continue
        if markers or n in FACET_STRONG or repeats:
            return c
    return None


def slug(level: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", level).strip("_.")
    return s or "all"


@dataclass
class LoadedComparison:
    results: pd.DataFrame  # columns gene, [effect], [p], [padj], [mean], [pct_in], [pct_out], [score], level; sorted within level
    levels: list[str]  # level labels in table order ("" for a comparison without a facet)
    columns: dict[str, str]  # role -> source column ("facet" -> the facet column, or "{level}")
    pseudobulk: dict[str, pd.DataFrame] | None  # per level (the same frame for every level when one file was given)
    replicates: pd.DataFrame | None  # columns id, group, [subject]
    notes: list[str] = field(default_factory=list)


def _read_pseudobulk(path: Path) -> pd.DataFrame:
    raw = read_table(path)
    gcol = find_column(raw, RESULT_ROLES["gene"]) or str(raw.columns[0])
    pb = raw.set_index(raw[gcol].astype(str).str.strip()).drop(columns=[gcol])
    pb = pb.apply(pd.to_numeric, errors="coerce")
    pb = pb[~pb.index.duplicated()]
    pb.columns = [str(c) for c in pb.columns]
    return pb


def load_tables(spec: ComparisonSpec, union: set[str] | None = None) -> LoadedComparison:
    """Read the tables and recognise their columns. With the bundle's gene `union`, the gene column that matches it
    best wins among the candidates (a symbol column over an Ensembl id column, say). A `{level}` template reads one
    file per level; a facet column splits one file into levels; a markers table must have one or the other."""
    notes: list[str] = []
    markers = spec.kind == "markers"
    lp = level_paths(spec.results)
    if lp is not None:
        if not lp:
            raise ValueError(f"comparison {spec.id}: {spec.results} matches no file")
        frames = []
        for lvl, path in lp.items():
            f = read_table(path)
            f["__level__"] = lvl
            frames.append(f)
        df = pd.concat(frames, ignore_index=True)
        facet_col: str | None = "__level__"
        source = Path(str(spec.results)).name
    else:
        df = read_table(spec.results)
        facet_col = None
        source = spec.results.name
    if df.empty:
        raise ValueError(f"comparison {spec.id}: {source} is empty")
    cols = map_columns(df, RESULT_ROLES, spec.columns.results, what=f"comparison {spec.id} results")
    cands = gene_candidates(df, cols)
    if not cands:
        raise ValueError(f"comparison {spec.id}: no gene column in {source}; name it with `columns: {{ results: {{ gene: <column> }} }}`")
    if "gene" not in spec.columns.results and union is not None and len(cands) > 1:
        scored = sorted(cands, key=lambda c: -df[c].astype(str).isin(union).sum())
        if scored[0] != cands[0]:
            notes.append(f"gene names from {scored[0]!r} ({int(df[scored[0]].astype(str).isin(union).sum()):,} match the bundle; {cands[0]!r} matches {int(df[cands[0]].astype(str).isin(union).sum()):,})")
        cands = scored
    cols["gene"] = cands[0]
    if facet_col is None:
        try:
            facet_col = detect_facet(df, cols["gene"], spec.facet.column if spec.facet else None, markers=markers)
        except KeyError as e:
            raise KeyError(f"comparison {spec.id}: {e}") from None
    if markers and facet_col is None:
        raise ValueError(f"comparison {spec.id}: a markers table needs a column that says which cluster each gene marks (cluster, celltype, group, ...); name it with `facet: {{ column: <column> }}`")
    if not markers and "effect" not in cols:
        raise ValueError(f"comparison {spec.id}: no effect column (log2FoldChange, logFC, avg_log2FC, ...) in {source}; name it with `columns: {{ results: {{ effect: <column> }} }}`")
    if not markers and "p" not in cols and "padj" not in cols:
        raise ValueError(f"comparison {spec.id}: no p-value column (pvalue, P.Value, p_val, padj, FDR, ...) in {source}; name one with `columns: {{ results: {{ padj: <column> }} }}`")
    if facet_col is not None:
        cols["facet"] = LEVEL_TOKEN if facet_col == "__level__" else facet_col
        if facet_col in cols.values() and facet_col != cols["facet"]:
            pass
        for role in [r for r, c in cols.items() if c == facet_col and r not in ("facet",)]:
            del cols[role]  # a facet column named `group` is not a score
    res = pd.DataFrame({"gene": df[cols["gene"]].astype(str).str.strip()})
    for role in ("effect", "p", "padj", "mean", "pct_in", "pct_out", "score"):
        if role in cols:
            res[role] = pd.to_numeric(df[cols[role]], errors="coerce")
    res["level"] = df[facet_col].astype(str).str.strip() if facet_col is not None else ""
    res = res[(res["gene"] != "") & (res["gene"] != "nan")]
    if "effect" in res:
        res = res[res["effect"].notna()]
    dup = res.duplicated(["level", "gene"])
    if dup.any():
        notes.append(f"{int(dup.sum()):,} repeated gene names in {source}: the first row of each is kept")
        res = res[~dup]
    levels = list(dict.fromkeys(res["level"].tolist()))
    if len(levels) > MAX_LEVELS:
        raise ValueError(f"comparison {spec.id}: {len(levels)} levels of {cols['facet']!r}; is that the facet column? name it with `facet: {{ column: <column> }}`")
    parts = []
    for lvl in levels:
        part = res[res["level"] == lvl]
        if "effect" in part:
            part = part.iloc[bh_sorted_order(part)]  # else a ranked list: the file's own order
        parts.append(part)
    res = pd.concat(parts).reset_index(drop=True)

    pb: dict[str, pd.DataFrame] | None = None
    if spec.pseudobulk is not None:
        plp = level_paths(spec.pseudobulk)
        if plp is not None:
            pb = {lvl: _read_pseudobulk(path) for lvl, path in plp.items()}
            without = [lvl for lvl in levels if lvl not in pb]
            if without:
                notes.append(f"no pseudobulk file for level{'s' if len(without) != 1 else ''} {', '.join(without[:4])}{', ...' if len(without) > 4 else ''}: their dots are blank")
        else:
            one = _read_pseudobulk(spec.pseudobulk)
            pb = dict.fromkeys(levels, one)
        missing = sum(int((~res.loc[res["level"] == lvl, "gene"].isin(frame.index)).sum()) for lvl, frame in pb.items())
        if missing:
            notes.append(f"{missing:,} genes of the results have no row in the pseudobulk table{'s' if plp else ''}: their replicate values are blank")

    reps = None
    if spec.replicates is not None:
        raw = read_table(spec.replicates)
        rcols = map_columns(raw, REPLICATE_ROLES, spec.columns.replicates, what=f"comparison {spec.id} replicates")
        if "id" not in rcols:
            rcols["id"] = str(raw.columns[0])
        if "group" not in rcols:
            raise ValueError(f"comparison {spec.id}: no group column (group, condition, treatment, ...) in {spec.replicates.name}; name it with `columns: {{ replicates: {{ group: <column> }} }}`")
        reps = pd.DataFrame({"id": raw[rcols["id"]].astype(str).str.strip(), "group": raw[rcols["group"]].astype(str).str.strip()})
        reps["subject"] = raw[rcols["subject"]].astype(str).str.strip() if "subject" in rcols and rcols["subject"] != rcols["id"] else reps["id"]
        reps = reps[~reps["id"].duplicated()].reset_index(drop=True)
        cols.update({f"replicate_{k}": v for k, v in rcols.items()})
    return LoadedComparison(results=res, levels=levels, columns=cols, pseudobulk=pb, replicates=reps, notes=notes)


def find_split_key(groups: list[str], meta: list[MetaKey]) -> str | None:
    """The sample meta key whose levels contain every group, if one does."""
    for k in meta:
        if set(groups) <= set(k.levels):
            return k.id
    return None


def link_replicates(rep_ids: list[str], samples: list[Sample], link: str | None, meta: list[MetaKey]) -> tuple[str | None, dict[str, list[str]]]:
    """Which sections each replicate id has: the samples whose `meta[link]` equals it, else the sample with that id.
    Without `link`, the meta key that matches the most ids is taken (then the sample ids)."""
    keys = [link] if link else [k.id for k in meta]
    best: tuple[int, str | None] = (0, None)
    for k in keys:
        n = sum(1 for r in rep_ids if any(s.meta.get(k) == r for s in samples))
        if n > best[0]:
            best = (n, k)
    key = best[1]
    out: dict[str, list[str]] = {}
    for r in rep_ids:
        hits = [s.id for s in samples if key is not None and s.meta.get(key) == r]
        if not hits and any(s.id == r for s in samples):
            hits = [r]
        out[r] = hits
    return key, out


def canonical(level: str, field: str, fields: dict[str, list[str]], aliases: dict[str, dict[str, str]] | None) -> str | None:
    """The category a level stands for: itself, or what the field's aliases map it to; None when it is neither."""
    cats = fields.get(field, [])
    if level in cats:
        return level
    alt = (aliases or {}).get(field, {}).get(level)
    return alt if alt in cats else None


def infer_facet_field(levels: list[str], fields: dict[str, list[str]] | None, given: str | None, aliases: dict[str, dict[str, str]] | None = None) -> str | None:
    """The categorical field whose categories the levels are (through the field's aliases too): the one named, else
    the best match when at least half of the levels are among its categories."""
    if given:
        if fields is not None and given not in fields:
            raise ValueError(f"`facet.field: {given}` is not a categorical field of the dataset (known: {', '.join(sorted(fields)) or 'none'})")
        return given
    if not fields or not levels:
        return None
    hits = {f: sum(1 for lvl in levels if canonical(lvl, f, fields, aliases) is not None) for f in fields}
    best = max(hits, key=lambda f: hits[f])
    return best if hits[best] * 2 >= len(levels) else None


@dataclass
class ResolvedLevel:
    id: str  # folder name
    name: str  # the level's label ("all" without a facet)
    results: pd.DataFrame
    replicates: list[dict]  # {id, group, subject, samples}
    pseudobulk: pd.DataFrame | None
    population: PopulationInfo | None


@dataclass
class ResolvedComparison:
    spec: ComparisonSpec
    loaded: LoadedComparison
    groups: list[str]
    split: str | None
    link: str | None
    facet_field: str | None
    levels: list[ResolvedLevel]
    notes: list[str]

    @property
    def replicates(self) -> list[dict]:
        """The first level's replicate rows (every level's, for a comparison without a facet)."""
        return self.levels[0].replicates if self.levels else []


def _replicate_rows(spec: ComparisonSpec, loaded: LoadedComparison, rep_ids: list[str], linked: dict[str, list[str]], link: str | None, spatial: list[Sample], meta: list[MetaKey]) -> list[dict]:
    rows: list[dict] = []
    if loaded.replicates is not None:
        sheet = loaded.replicates[loaded.replicates["id"].isin(rep_ids)] if rep_ids else loaded.replicates
        for _, r in sheet.iterrows():
            rows.append({"id": r["id"], "group": r["group"], "subject": r["subject"], "samples": linked.get(r["id"], [])})
        return rows
    if not rep_ids:
        return rows
    # no sheet: the group is what the linked sections say under the split key
    split_guess = spec.split or (find_split_key(spec.groups, meta) if spec.groups else None)
    if split_guess is None and meta:
        split_guess = next((k.id for k in meta if k.id != link and len(k.levels) >= 2), None)
    for r in rep_ids:
        vals = sorted({s.meta.get(split_guess, "") for s in spatial if s.id in linked.get(r, []) and split_guess} - {""})
        if len(vals) != 1:
            raise ValueError(
                f"comparison {spec.id}: cannot tell which group replicate {r!r} belongs to "
                + (f"(its sections carry {len(vals)} values of {split_guess!r})" if vals else "(no section is linked to it)")
                + "; give a `replicates:` sheet with id and group columns"
            )
        rows.append({"id": r, "group": vals[0], "subject": r, "samples": linked[r]})
    return rows


def resolve_comparison(spec: ComparisonSpec, loaded: LoadedComparison, samples: list[Sample], meta: list[MetaKey], fields: dict[str, list[str]] | None = None, aliases: dict[str, dict[str, str]] | None = None) -> ResolvedComparison:
    """Settle groups, the split key, the replicate rows and their sections per level from the tables and the samples'
    metadata; `fields` (categorical field id -> categories) and `aliases` (field id -> {label: category}) link
    facet levels to an annotation."""
    notes = list(loaded.notes)
    markers = spec.kind == "markers"
    spatial = [s for s in samples if s.kind != "embedding"]
    faceted = "facet" in loaded.columns
    facet_field = infer_facet_field(loaded.levels, fields, spec.facet.field if spec.facet else None, aliases) if faceted else None
    if faceted and spec.facet and spec.facet.field is None and facet_field:
        notes.append(f"levels of {loaded.columns['facet']!r} are categories of {facet_field!r}: the map can be filtered to each")
    all_ids: list[str] = []
    if not markers:
        for lvl in loaded.levels:
            ids = list(loaded.replicates["id"]) if loaded.replicates is not None else (list(loaded.pseudobulk[lvl].columns) if loaded.pseudobulk and lvl in loaded.pseudobulk else [])
            all_ids.extend(i for i in ids if i not in all_ids)
    link, linked = link_replicates(all_ids, spatial, spec.link, meta)
    if spec.link and link is None and all_ids:
        raise ValueError(f"comparison {spec.id}: no sample has a `meta.{spec.link}` equal to a replicate id ({', '.join(all_ids[:5])}{', ...' if len(all_ids) > 5 else ''})")
    used: set[str] = set()
    levels: list[ResolvedLevel] = []
    seen_groups: list[str] = []
    for lvl in loaded.levels:
        sid = slug(lvl)
        while sid in used:
            sid += "_"
        used.add(sid)
        part = loaded.results[loaded.results["level"] == lvl].drop(columns=["level"]).reset_index(drop=True)
        pb = loaded.pseudobulk.get(lvl) if loaded.pseudobulk else None
        rows: list[dict] = []
        if not markers:
            ids = list(loaded.replicates["id"]) if loaded.replicates is not None else (list(pb.columns) if pb is not None else [])
            rows = _replicate_rows(spec, loaded, ids, linked, link, spatial, meta)
            for r in rows:
                if r["group"] not in seen_groups:
                    seen_groups.append(r["group"])
        cat = canonical(lvl, facet_field, fields, aliases) if facet_field and fields else None
        pop = PopulationInfo(field=facet_field, value=cat) if cat is not None else None
        levels.append(ResolvedLevel(id=sid, name=lvl or "all", results=part, replicates=rows, pseudobulk=pb, population=pop))
    if markers:
        unlinked_levels = [lv.name for lv in levels if facet_field and lv.population is None]
        if facet_field and unlinked_levels:
            notes.append(f"{len(unlinked_levels)} level{'s' if len(unlinked_levels) != 1 else ''} not among the categories of {facet_field!r} ({', '.join(unlinked_levels[:4])}{', ...' if len(unlinked_levels) > 4 else ''}): no map filter for them")
        return ResolvedComparison(spec=spec, loaded=loaded, groups=[], split=None, link=None, facet_field=facet_field, levels=levels, notes=notes)
    groups = list(spec.groups or [])
    if not groups:
        groups = seen_groups
        if groups:
            notes.append(f"groups in order of appearance: {', '.join(groups)}; set `groups:` to choose the order (the contrast is the last against the first)")
    else:
        extra = [g for g in seen_groups if g not in groups]
        if extra:
            raise ValueError(f"comparison {spec.id}: replicate group{'s' if len(extra) != 1 else ''} {', '.join(extra)} not in `groups: {groups}`")
    if not groups:
        raise ValueError(f"comparison {spec.id}: set `groups:` (e.g. [control, stress]); there is no replicate sheet or pseudobulk table to read them from")
    split = spec.split or find_split_key(groups, meta)
    if spec.split and spec.split not in {k.id for k in meta}:
        raise ValueError(f"comparison {spec.id}: `split: {spec.split}` is not a sample meta key (known: {', '.join(k.id for k in meta) or 'none'})")
    unlinked = sorted({r["id"] for lv in levels for r in lv.replicates if not r["samples"]})
    if all_ids and unlinked:
        notes.append(f"{len(unlinked)} of {len(all_ids)} replicates have no section to focus ({', '.join(unlinked[:4])}{', ...' if len(unlinked) > 4 else ''})")
    return ResolvedComparison(spec=spec, loaded=loaded, groups=groups, split=split, link=link, facet_field=facet_field, levels=levels, notes=notes)


# ---------------------------------------------------------------- fingerprint and plan
def comparison_fingerprint(spec: ComparisonSpec, cfg: DatasetConfig, samples_sig: dict[str, str]) -> dict:
    inputs = {str(p): _stat(p) for p in source_paths(spec)}
    fp = {
        "recipe": COMPARISONS_RECIPE,
        "spec": spec.model_dump(mode="json", exclude={"name", "description", "units"}),
        "inputs": inputs,
        "samples": samples_sig,  # replicates link through the samples' metadata and genes match the samples' union
        "meta": [m.model_dump(mode="json") for m in cfg.meta],
    }
    return json.loads(json.dumps(fp, sort_keys=True, default=str))


def why_stale_comparison(old: dict | None, new: dict) -> str | None:
    if old is None:
        return "new"
    if old == new:
        return None
    if old.get("recipe") != new["recipe"]:
        return "format changed"
    if old.get("inputs") != new["inputs"]:
        return "table changed"
    if old.get("samples") != new["samples"] or old.get("meta") != new["meta"]:
        return "samples changed"
    return "settings changed"


@dataclass
class ComparisonAction:
    spec: ComparisonSpec
    build: bool
    reason: str
    fingerprint: dict


def plan_comparisons(cfg: DatasetConfig, out: Path, samples_sig: dict[str, str], *, force: bool = False) -> tuple[list[ComparisonAction], list[str]]:
    """What a build would do to `comparisons/`: one action per entry, and the folders of entries the yaml dropped."""
    out = Path(out)
    actions: list[ComparisonAction] = []
    for spec in cfg.comparisons:
        fp = comparison_fingerprint(spec, cfg, samples_sig)
        d = out / "comparisons" / spec.id
        if force:
            reason: str | None = "forced"
        elif not (d / "comparison.json").exists():
            reason = "new"
        else:
            reason = why_stale_comparison(read_sidecar(d), fp)
        actions.append(ComparisonAction(spec, reason is not None, reason or "unchanged", fp))
    wanted = {c.id for c in cfg.comparisons}
    root = out / "comparisons"
    folders = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    return actions, [f for f in folders if f not in wanted]


# ---------------------------------------------------------------- writing
def _json_floats(a: pd.Series | None) -> list | None:
    if a is None:
        return None
    return [None if (isinstance(v, float) and math.isnan(v)) else float(v) for v in a.to_numpy(dtype=float)]


def _write_level(d: Path, lv: ResolvedLevel, union: set[str]) -> LevelInfo:
    d.mkdir(parents=True)
    res = lv.results
    genes = res["gene"].tolist()
    measured = res["gene"].isin(union).to_numpy()
    unmeasured = [int(i) for i in np.flatnonzero(~measured)]
    doc = {"genes": genes, "unmeasured": unmeasured}
    for role in ("effect", "p", "padj", "mean", "pct_in", "pct_out", "score"):
        doc[role] = _json_floats(res[role]) if role in res else None
    (d / "results.json").write_text(json.dumps(doc, separators=(",", ":")))
    n_rep = len(lv.replicates)
    has_pb = lv.pseudobulk is not None and n_rep > 0
    if has_pb:
        import zarr
        from zarr.codecs import BloscCodec

        ids = [r["id"] for r in lv.replicates]
        mat = lv.pseudobulk.reindex(index=genes, columns=ids).to_numpy(dtype=np.float32)
        arr = zarr.create_array(
            store=str(d / "pseudobulk.zarr"), shape=mat.shape, chunks=(min(PSEUDOBULK_CHUNK, max(1, mat.shape[0])), max(1, mat.shape[1])), dtype="float32", compressors=[BloscCodec(cname="zstd", clevel=5)], fill_value=float("nan")
        )
        arr[:] = mat
    key = "padj" if "padj" in res else "p" if "p" in res else None
    sig = int((res[key] < 0.05).sum()) if key else 0
    return LevelInfo(id=lv.id, name=lv.name, path=f"levels/{lv.id}", nGenes=len(genes), nSignificant=sig, nUnmatched=len(unmeasured), nReplicates=n_rep, hasPseudobulk=has_pb, population=lv.population)


def _write_matrix(d: Path, levels: list[ResolvedLevel], union: set[str]) -> dict:
    """genes x levels of the statistics, for the table that shows every level at once: matrix.json (the gene
    order, each gene's first level and whether a sample measures it) and matrix.zarr with one float32 array per
    statistic present (effect, padj, pct_in; rank always: 1-based position in the level's table), NaN where a
    level's table has no row for the gene."""
    import zarr
    from zarr.codecs import BloscCodec

    genes: list[str] = []
    index: dict[str, int] = {}
    for lv in levels:
        for g in lv.results["gene"]:
            if g not in index:
                index[g] = len(genes)
                genes.append(g)
    n, k = len(genes), len(levels)
    stats = {"rank": np.full((n, k), np.nan, dtype=np.float32)}
    for role in ("effect", "padj", "p", "pct_in", "pct_out"):
        if any(role in lv.results for lv in levels):
            stats[role] = np.full((n, k), np.nan, dtype=np.float32)
    for j, lv in enumerate(levels):
        rows = np.fromiter((index[g] for g in lv.results["gene"]), dtype=np.int64, count=len(lv.results))
        stats["rank"][rows, j] = np.arange(1, len(rows) + 1, dtype=np.float32)
        for role, arr in stats.items():
            if role != "rank" and role in lv.results:
                arr[rows, j] = lv.results[role].to_numpy(dtype=np.float32)
    group = zarr.create_group(store=str(d / "matrix.zarr"))
    for role, arr in stats.items():
        za = group.create_array(name=role, shape=arr.shape, chunks=(min(4096, max(1, n)), max(1, k)), dtype="float32", compressors=[BloscCodec(cname="zstd", clevel=5)], fill_value=float("nan"))
        za[:] = arr
    unmeasured = [i for i, g in enumerate(genes) if g not in union]
    (d / "matrix.json").write_text(json.dumps({"genes": genes, "levels": [lv.id for lv in levels], "stats": sorted(stats), "unmeasured": unmeasured}, separators=(",", ":")))
    return {"genes": n, "stats": sorted(stats)}


def write_comparison(out: Path, spec: ComparisonSpec, samples: list[Sample], meta: list[MetaKey], union: set[str], log: Log = print, fields: dict[str, list[str]] | None = None, aliases: dict[str, dict[str, str]] | None = None) -> ComparisonInfo:
    """Read, resolve and write one comparison; returns its manifest entry. `fields` maps every categorical field to
    its categories and `aliases` to its label aliases, so a facet's levels can be linked to an annotation."""
    loaded = load_tables(spec, union)
    rc = resolve_comparison(spec, loaded, samples, meta, fields, aliases)
    res = loaded.results
    d = Path(out) / "comparisons" / spec.id
    tmp = d.with_name(d.name + ".tmp")
    if tmp.exists():
        import shutil

        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    level_infos = [_write_level(tmp / "levels" / lv.id, lv, union) for lv in rc.levels]
    matrix = _write_matrix(tmp, rc.levels, union)
    rep_ids = {r["id"] for lv in rc.levels for r in lv.replicates}
    faceted = "facet" in loaded.columns
    info = ComparisonInfo(
        id=spec.id,
        kind=spec.kind,
        name=spec.name or spec.id.replace("_", " "),
        description=spec.description,
        path=f"comparisons/{spec.id}",
        groups=rc.groups,
        units=spec.units,
        population=PopulationInfo(field=spec.population.field, value=spec.population.value) if spec.population else None,
        split=rc.split,
        link=rc.link,
        facet=FacetInfo(column=loaded.columns["facet"], field=rc.facet_field) if faceted else None,
        levels=level_infos,
        nGenes=sum(lv.nGenes for lv in level_infos),
        nReplicates=len(rep_ids),
        nUnmatched=sum(lv.nUnmatched for lv in level_infos),
        hasEffect="effect" in res,
        hasP="p" in res,
        hasPadj="padj" in res,
        hasMean="mean" in res,
        hasPct="pct_in" in res or "pct_out" in res,
        hasScore="score" in res,
        hasPseudobulk=any(lv.hasPseudobulk for lv in level_infos),
        nMatrixGenes=matrix["genes"],
    )
    (tmp / "comparison.json").write_text(
        json.dumps(
            {
                **info.model_dump(mode="json"),
                "replicates": {lv.id: lv.replicates for lv in rc.levels},
                "columns": loaded.columns,
                "sources": {k: str(Path(str(getattr(spec, k))).name) for k in ("results", "pseudobulk", "replicates") if getattr(spec, k) is not None},
                "n": {"genes": info.nGenes, "matched": info.nGenes - info.nUnmatched, "unmatched": info.nUnmatched},
            },
            indent=1,
        )
    )
    if d.exists():
        import shutil

        shutil.rmtree(d)
    tmp.rename(d)
    what = f"{len(level_infos)} levels of {loaded.columns['facet']!r}, " if faceted else ""
    if spec.kind == "markers":
        log(f"[comparison {spec.id}] markers: {what}{info.nGenes:,} rows ({info.nUnmatched:,} genes not in the bundle)" + (f", levels linked to {rc.facet_field!r}" if rc.facet_field else ""))
    else:
        log(f"[comparison {spec.id}] {what}{info.nGenes:,} genes ({info.nUnmatched:,} not in the bundle), {info.nReplicates} replicates in {len(rc.groups)} groups" + (f", split by {rc.split}" if rc.split else ""))
    for n in rc.notes:
        log(f"[comparison {spec.id}] {n}")
    return info


def read_info(out: Path, cid: str) -> ComparisonInfo | None:
    p = Path(out) / "comparisons" / cid / "comparison.json"
    if not p.exists():
        return None
    try:
        return ComparisonInfo.model_validate_json(p.read_text())
    except Exception:
        return None


def samples_signature(fingerprints: dict[str, dict]) -> dict[str, str]:
    """A short hash per sample of its build fingerprint: comparisons depend on the samples' genes and metadata."""
    return {sid: hashlib.sha1(json.dumps(fp, sort_keys=True, default=str).encode()).hexdigest()[:16] for sid, fp in fingerprints.items()}
