"""Dataset-level categorical vocabularies: stable codes + colors across samples and platforms."""
from __future__ import annotations

import colorsys
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import FieldSpec
from .manifest import Vocabulary

NA_LABEL = "NA"
NA_COLOR = "#c8c8c8"

# Tableau 20 + a few; stable, print-friendly
QUALITATIVE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf", "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5", "#c49c94",
    "#f7b6d2", "#dbdb8d", "#9edae5", "#393b79", "#637939", "#8c6d31", "#843c39", "#7b4173",
]


def _golden_color(i: int) -> str:
    h = (i * 0.618033988749895) % 1.0
    s = 0.55 + 0.35 * ((i * 7) % 3) / 2
    v = 0.75 + 0.2 * ((i * 11) % 2)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def load_palette(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    with open(path) as fh:
        raw: dict[str, Any] = json.load(fh)
    out: dict[str, dict[str, str]] = {}
    flat: dict[str, str] = {}
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict):
            out[k] = {str(a): str(b) for a, b in v.items()}
        elif isinstance(v, str):
            flat[k] = v
    if flat:
        out["_flat"] = flat
    return out


MAX_CATEGORIES = 65_535  # codes are uint16


def _label(c) -> str:
    """A category label as text: integral numbers without a trailing .0, so an int column in one sample and a
    float column (NaN forced it) in another meet in the same category."""
    if isinstance(c, (float, np.floating)):
        return str(int(c)) if np.isfinite(c) and float(c).is_integer() else str(c)
    return str(c)


def _label_strings(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s.dtype) and not pd.api.types.is_bool_dtype(s.dtype):
        v = pd.to_numeric(s, errors="coerce")
        return v.map(lambda x: None if pd.isna(x) else _label(float(x))).astype("string")
    return s.astype("string")


class VocabRegistry:
    """Append-only registry: codes never change once assigned, so a rebuilt sample stays consistent with the others."""

    def __init__(
        self,
        fields: list[FieldSpec],
        palette: dict[str, dict[str, str]] | None = None,
        existing: dict[str, Vocabulary] | None = None,
    ):
        self.fields = {f.id: f for f in fields}
        self.palette = palette or {}
        self.vocabs: dict[str, dict[str, Any]] = {}
        for vid, v in (existing or {}).items():
            self.vocabs[vid] = {
                "categories": list(v.categories),
                "colors": list(v.colors),
                "aliases": dict(v.aliases),
            }
        for f in fields:
            if f.type != "categorical":
                continue
            vid = f.vocabulary or f.id
            v = self.vocabs.setdefault(vid, {"categories": [], "colors": [], "aliases": {}})
            v["aliases"].update(f.aliases)
            v.setdefault("_palette_key", f.palette_key or vid)
            for c in f.categories or []:
                self._add(vid, c)

    def declare(self, f: FieldSpec) -> None:
        """Register a field discovered at build time (idempotent)."""
        if f.id in self.fields:
            return
        self.fields[f.id] = f
        if f.type == "categorical":
            vid = f.vocabulary or f.id
            v = self.vocabs.setdefault(vid, {"categories": [], "colors": [], "aliases": {}})
            v["aliases"].update(f.aliases)
            v.setdefault("_palette_key", f.palette_key or vid)

    def adopt_manifest_fields(self, manifest, only: set[str] | None = None) -> None:
        """Keep fields that an existing bundle already declares (e.g. auto-discovered ones); `only` restricts the ids."""
        for mf in manifest.fields:
            if mf.id in self.fields or (only is not None and mf.id not in only):
                continue
            if mf.type == "categorical":
                self.declare(FieldSpec(id=mf.id, name=mf.name, type="categorical", vocabulary=mf.vocabulary, description=mf.description))
            else:
                self.declare(FieldSpec(id=mf.id, name=mf.name, type="continuous", range=mf.range, colormap=mf.colormap, description=mf.description))

    def recolor_from_palette(self) -> int:
        """Re-derive the color of every existing label that the palette names, keeping codes. Returns how many changed."""
        changed = 0
        for vid, v in self.vocabs.items():
            key = v.get("_palette_key", vid)
            keys = [k.strip() for k in str(key).split(",")] + [vid, "_flat"]
            for i, label in enumerate(v["categories"]):
                if label == NA_LABEL:
                    continue
                for pk in keys:
                    pal = self.palette.get(pk)
                    if pal and label in pal:
                        if v["colors"][i] != pal[label]:
                            v["colors"][i] = pal[label]
                            changed += 1
                        break
        return changed

    def vocab_id(self, field_id: str) -> str:
        f = self.fields[field_id]
        return f.vocabulary or f.id

    def _color_for(self, vid: str, label: str, index: int) -> str:
        if label == NA_LABEL:
            return NA_COLOR
        key = self.vocabs[vid].get("_palette_key", vid)
        keys = [k.strip() for k in str(key).split(",")] + [vid, "_flat"]
        for pk in keys:
            pal = self.palette.get(pk)
            if pal and label in pal:
                return pal[label]
        if index < len(QUALITATIVE):
            return QUALITATIVE[index]
        return _golden_color(index)

    def hint_colors(self, field_id: str, values: pd.Series, colors) -> None:
        """Colours an object carries for a column (`uns["<col>_colors"]`, one per category) become the palette of
        the field's vocabulary where the palette says nothing yet; labels already coded keep their colour."""
        if colors is None or not isinstance(values.dtype, pd.CategoricalDtype):
            return
        cols = [str(c) for c in list(colors)]
        cats = [str(c) for c in values.cat.categories]
        if len(cols) != len(cats):
            return
        vid = self.vocab_id(field_id)
        key = str(self.vocabs.get(vid, {}).get("_palette_key", vid)).split(",")[0].strip()
        pal = self.palette.setdefault(key, {})
        for label, color in zip(cats, cols, strict=True):
            if color and label not in pal:
                pal[label] = color

    def _add(self, vid: str, label: str) -> int:
        v = self.vocabs[vid]
        cats = v["categories"]
        if label in cats:
            return cats.index(label)
        if len(cats) >= MAX_CATEGORIES:
            raise ValueError(f"vocabulary {vid!r}: more than {MAX_CATEGORIES:,} categories across samples")
        cats.append(label)
        v["colors"].append(self._color_for(vid, label, len(cats) - 1))
        return len(cats) - 1

    def encode(self, field_id: str, values: pd.Series) -> np.ndarray:
        vid = self.vocab_id(field_id)
        aliases = self.vocabs[vid]["aliases"]
        s = values
        if not isinstance(s.dtype, pd.CategoricalDtype):
            s = _label_strings(s).astype("category")
        labels = [aliases.get(_label(c), _label(c)) for c in s.cat.categories]
        if len(labels) > MAX_CATEGORIES:
            raise ValueError(f"field {field_id!r}: {len(labels):,} categories (at most {MAX_CATEGORIES:,}); map a coarser column, or leave this one out of `fields:`")
        # preserve source category order for first-seen appends
        code_map = np.empty(len(labels) + 1, dtype=np.uint16)
        for i, lab in enumerate(labels):
            code_map[i] = self._add(vid, lab)
        code_map[-1] = self._add(vid, NA_LABEL) if (s.cat.codes < 0).any() else 0
        src = s.cat.codes.to_numpy().astype(np.int64)
        src[src < 0] = len(labels)
        return code_map[src]

    def to_manifest(self) -> dict[str, Vocabulary]:
        return {
            vid: Vocabulary(categories=v["categories"], colors=v["colors"], aliases=v["aliases"])
            for vid, v in self.vocabs.items()
        }
