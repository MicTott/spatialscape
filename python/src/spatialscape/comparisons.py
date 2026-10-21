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
from .manifest import ComparisonInfo, MetaKey, PopulationInfo, Sample

Log = Callable[[str], None]

COMPARISONS_RECIPE = 1
TABLE_SUFFIXES = (".csv", ".tsv", ".txt", ".parquet")
PSEUDOBULK_CHUNK = 1024

# Column names recognised for each role, tried in order (case-insensitive). The first table-specific spellings are
# DESeq2 / limma / edgeR / Seurat FindMarkers / pyDESeq2 / scanpy rank_genes_groups.
RESULT_ROLES: dict[str, list[str]] = {
    "gene": ["gene", "genes", "gene_name", "symbol", "gene_symbol", "feature", "features", "names", "gene_id", "gene_ids", "ensembl_id", "ensembl"],
    "effect": ["log2FoldChange", "logFC", "avg_log2FC", "log2fc", "log2_fold_change", "logfoldchanges", "estimate", "beta", "coef", "effect"],
    "p": ["pvalue", "p_value", "P.Value", "p_val", "PValue", "pvals", "pval", "p"],
    "padj": ["padj", "adj.P.Val", "FDR", "p_val_adj", "pvals_adj", "q_value", "qvalue", "fdr", "p_adj", "adj_p", "qval"],
    "mean": ["baseMean", "AveExpr", "logCPM", "base_mean", "avg_expr", "mean_expression", "mean"],
}
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


@dataclass
class LoadedComparison:
    results: pd.DataFrame  # columns gene, effect, [p], [padj], [mean]; one row per gene
    columns: dict[str, str]  # role -> source column
    pseudobulk: pd.DataFrame | None  # index: gene; columns: replicate ids
    replicates: pd.DataFrame | None  # columns id, group, [subject]
    notes: list[str] = field(default_factory=list)


def load_tables(spec: ComparisonSpec, union: set[str] | None = None) -> LoadedComparison:
    """Read the three tables and recognise their columns. With the bundle's gene `union`, the gene column that
    matches it best wins among the candidates (a symbol column over an Ensembl id column, say)."""
    notes: list[str] = []
    df = read_table(spec.results)
    if df.empty:
        raise ValueError(f"comparison {spec.id}: {spec.results} is empty")
    cols = map_columns(df, RESULT_ROLES, spec.columns.results, what=f"comparison {spec.id} results")
    cands = gene_candidates(df, cols)
    if not cands:
        raise ValueError(f"comparison {spec.id}: no gene column in {spec.results.name}; name it with `columns: {{ results: {{ gene: <column> }} }}`")
    if "gene" not in spec.columns.results and union is not None and len(cands) > 1:
        scored = sorted(cands, key=lambda c: -df[c].astype(str).isin(union).sum())
        if scored[0] != cands[0]:
            notes.append(f"gene names from {scored[0]!r} ({int(df[scored[0]].astype(str).isin(union).sum()):,} match the bundle; {cands[0]!r} matches {int(df[cands[0]].astype(str).isin(union).sum()):,})")
        cands = scored
    cols["gene"] = cands[0]
    if "effect" not in cols:
        raise ValueError(f"comparison {spec.id}: no effect column (log2FoldChange, logFC, avg_log2FC, ...) in {spec.results.name}; name it with `columns: {{ results: {{ effect: <column> }} }}`")
    if "p" not in cols and "padj" not in cols:
        raise ValueError(f"comparison {spec.id}: no p-value column (pvalue, P.Value, p_val, padj, FDR, ...) in {spec.results.name}; name one with `columns: {{ results: {{ padj: <column> }} }}`")
    res = pd.DataFrame({"gene": df[cols["gene"]].astype(str).str.strip(), "effect": pd.to_numeric(df[cols["effect"]], errors="coerce")})
    for role in ("p", "padj", "mean"):
        if role in cols:
            res[role] = pd.to_numeric(df[cols[role]], errors="coerce")
    res = res[(res["gene"] != "") & (res["gene"] != "nan") & res["effect"].notna()]
    dup = res["gene"].duplicated()
    if dup.any():
        notes.append(f"{int(dup.sum()):,} repeated gene names in {spec.results.name}: the first row of each is kept")
        res = res[~dup]
    res = res.iloc[bh_sorted_order(res)].reset_index(drop=True)

    pb = None
    if spec.pseudobulk is not None:
        raw = read_table(spec.pseudobulk)
        gcol = find_column(raw, RESULT_ROLES["gene"]) or str(raw.columns[0])
        pb = raw.set_index(raw[gcol].astype(str).str.strip()).drop(columns=[gcol])
        pb = pb.apply(pd.to_numeric, errors="coerce")
        pb = pb[~pb.index.duplicated()]
        pb.columns = [str(c) for c in pb.columns]
        missing = int((~res["gene"].isin(pb.index)).sum())
        if missing:
            notes.append(f"{missing:,} genes of the results have no row in {spec.pseudobulk.name}: their replicate values are blank")

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
    return LoadedComparison(results=res, columns=cols, pseudobulk=pb, replicates=reps, notes=notes)


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


@dataclass
class ResolvedComparison:
    spec: ComparisonSpec
    loaded: LoadedComparison
    groups: list[str]
    split: str | None
    link: str | None
    replicates: list[dict]  # {id, group, subject, samples}
    notes: list[str]


def resolve_comparison(spec: ComparisonSpec, loaded: LoadedComparison, samples: list[Sample], meta: list[MetaKey]) -> ResolvedComparison:
    """Settle groups, the split key, the replicate rows and their sections from the tables and the samples' metadata."""
    notes = list(loaded.notes)
    spatial = [s for s in samples if s.kind != "embedding"]
    rep_ids: list[str] = list(loaded.replicates["id"]) if loaded.replicates is not None else (list(loaded.pseudobulk.columns) if loaded.pseudobulk is not None else [])
    link, linked = link_replicates(rep_ids, spatial, spec.link, meta)
    if spec.link and link is None and rep_ids:
        raise ValueError(f"comparison {spec.id}: no sample has a `meta.{spec.link}` equal to a replicate id ({', '.join(rep_ids[:5])}{', ...' if len(rep_ids) > 5 else ''})")
    rows: list[dict] = []
    if loaded.replicates is not None:
        for _, r in loaded.replicates.iterrows():
            rows.append({"id": r["id"], "group": r["group"], "subject": r["subject"], "samples": linked.get(r["id"], [])})
    elif rep_ids:
        # no sheet: the group is what the linked sections say under the split key
        split_guess = spec.split or (find_split_key(spec.groups, meta) if spec.groups else None)
        if split_guess is None and meta:
            # the key under which linked sections take the fewest distinct values per replicate, most across them
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
    groups = list(spec.groups or [])
    seen: list[str] = []
    for r in rows:
        if r["group"] not in seen:
            seen.append(r["group"])
    if not groups:
        groups = seen
        if groups:
            notes.append(f"groups in order of appearance: {', '.join(groups)}; set `groups:` to choose the order (the contrast is the last against the first)")
    else:
        extra = [g for g in seen if g not in groups]
        if extra:
            raise ValueError(f"comparison {spec.id}: replicate group{'s' if len(extra) != 1 else ''} {', '.join(extra)} not in `groups: {groups}`")
    if not groups:
        raise ValueError(f"comparison {spec.id}: set `groups:` (e.g. [control, stress]); there is no replicate sheet or pseudobulk table to read them from")
    split = spec.split or find_split_key(groups, meta)
    if spec.split and spec.split not in {k.id for k in meta}:
        raise ValueError(f"comparison {spec.id}: `split: {spec.split}` is not a sample meta key (known: {', '.join(k.id for k in meta) or 'none'})")
    unlinked = [r["id"] for r in rows if not r["samples"]]
    if rows and unlinked:
        notes.append(f"{len(unlinked)} of {len(rows)} replicates have no section to focus ({', '.join(unlinked[:4])}{', ...' if len(unlinked) > 4 else ''})")
    return ResolvedComparison(spec=spec, loaded=loaded, groups=groups, split=split, link=link, replicates=rows, notes=notes)


# ---------------------------------------------------------------- fingerprint and plan
def comparison_fingerprint(spec: ComparisonSpec, cfg: DatasetConfig, samples_sig: dict[str, str]) -> dict:
    inputs = {str(p): _stat(p) for p in (spec.results, spec.pseudobulk, spec.replicates) if p is not None}
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


def write_comparison(out: Path, spec: ComparisonSpec, samples: list[Sample], meta: list[MetaKey], union: set[str], log: Log = print) -> ComparisonInfo:
    """Read, resolve and write one comparison; returns its manifest entry."""
    loaded = load_tables(spec, union)
    rc = resolve_comparison(spec, loaded, samples, meta)
    res = loaded.results
    d = Path(out) / "comparisons" / spec.id
    tmp = d.with_name(d.name + ".tmp")
    if tmp.exists():
        import shutil

        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    genes = res["gene"].tolist()
    measured = res["gene"].isin(union).to_numpy()
    unmeasured = [int(i) for i in np.flatnonzero(~measured)]
    doc = {
        "genes": genes,
        "effect": _json_floats(res["effect"]),
        "p": _json_floats(res["p"]) if "p" in res else None,
        "padj": _json_floats(res["padj"]) if "padj" in res else None,
        "mean": _json_floats(res["mean"]) if "mean" in res else None,
        "unmeasured": unmeasured,
    }
    (tmp / "results.json").write_text(json.dumps(doc, separators=(",", ":")))
    n_rep = len(rc.replicates)
    if loaded.pseudobulk is not None and n_rep:
        import zarr
        from zarr.codecs import BloscCodec

        ids = [r["id"] for r in rc.replicates]
        mat = loaded.pseudobulk.reindex(index=genes, columns=ids).to_numpy(dtype=np.float32)
        arr = zarr.create_array(
            store=str(tmp / "pseudobulk.zarr"), shape=mat.shape, chunks=(min(PSEUDOBULK_CHUNK, max(1, mat.shape[0])), max(1, mat.shape[1])), dtype="float32", compressors=[BloscCodec(cname="zstd", clevel=5)], fill_value=float("nan")
        )
        arr[:] = mat
    info = ComparisonInfo(
        id=spec.id,
        name=spec.name or spec.id.replace("_", " "),
        description=spec.description,
        path=f"comparisons/{spec.id}",
        groups=rc.groups,
        units=spec.units,
        population=PopulationInfo(field=spec.population.field, value=spec.population.value) if spec.population else None,
        split=rc.split,
        link=rc.link,
        nGenes=len(genes),
        nReplicates=n_rep,
        nUnmatched=len(unmeasured),
        hasP="p" in res,
        hasPadj="padj" in res,
        hasMean="mean" in res,
        hasPseudobulk=loaded.pseudobulk is not None and n_rep > 0,
    )
    (tmp / "comparison.json").write_text(
        json.dumps(
            {
                **info.model_dump(mode="json"),
                "replicates": rc.replicates,
                "columns": loaded.columns,
                "sources": {k: str(getattr(spec, k).name) for k in ("results", "pseudobulk", "replicates") if getattr(spec, k) is not None},
                "n": {"genes": len(genes), "matched": int(measured.sum()), "unmatched": len(unmeasured)},
            },
            indent=1,
        )
    )
    if d.exists():
        import shutil

        shutil.rmtree(d)
    tmp.rename(d)
    log(f"[comparison {spec.id}] {len(genes):,} genes ({len(unmeasured):,} not in the bundle), {n_rep} replicates in {len(rc.groups)} groups" + (f", split by {rc.split}" if rc.split else ""))
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
