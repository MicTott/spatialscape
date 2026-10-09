#!/usr/bin/env bash
# New-user walkthrough: from a SpatialExperiment saved as .rds to a local site, using only the spatialscape CLI.
#
#   cd /path/to/your/project
#   bash walkthrough_from_spe.sh [spe.rds] [dataset_id] [colData columns, comma-separated]
#
# Defaults are the LIBD amygdala Visium object. Everything is written under ./spatialscape/ in the current
# folder: data/ (converted inputs), dataset.yaml, bundles/ (what the viewer streams), site/ (what you upload).
# Delete that folder to start over. Steps whose outputs exist are skipped; FORCE=1 redoes them.
#
#   SPATIALSCAPE_WHEEL=...   wheel to install (until the package is on PyPI)
#   NO_SERVE=1               do not start the viewer at the end
#   TIDY=0                   keep the automatic field names instead of applying the explicit mapping
#
# Memory: convert holds the R object in memory (about 14 GB for the 2 GB amygdala object).
set -euo pipefail

SPE=${1:-Vitessce_app/spe_amy_shinyapp.rds}
ID=${2:-amygdala_visium}
COLS=${3:-BS_k16_Semisupervised_wAI,sum_umi,sum_gene,expr_chrM_ratio}
WHEEL=${SPATIALSCAPE_WHEEL:-/Users/michael.totty/Documents/Web/spatialscape/python/dist/spatialscape-0.1.0-py3-none-any.whl}
PALETTE=${PALETTE:-Vitessce_app/build/handoff/palette.json}
OUT=spatialscape
VENV=.venv-spatialscape
PORT=${PORT:-8787}

bold()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
say()   { printf '\033[2m%s\033[0m\n' "$*"; }
run()   { printf '\033[36m$ %s\033[0m\n' "$*"; local t0=$SECONDS; "$@"; say "   (${1##*/} ${2:-} took $((SECONDS - t0))s)"; }
have()  { [ -e "$1" ] && [ -z "${FORCE:-}" ]; }

[ -f "$SPE" ] || { echo "no such file: $SPE (run this from your project folder, or pass the path)"; exit 1; }

bold "0. Where things will go"
say "project : $(pwd)"
say "object  : $SPE"
say "outputs : $(pwd)/$OUT/{data,dataset.yaml,bundles,site}"

bold "1. Python environment with the spatialscape CLI"
if have "$VENV/bin/spatialscape"; then
  say "reusing $VENV"
else
  run python3 -m venv "$VENV"
  run "$VENV/bin/pip" install --quiet "$WHEEL"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
run spatialscape --version

bold "2. What is in the object"
run spatialscape inspect "$SPE"

bold "3. Convert the R object into build inputs (one folder per sample)"
if have "$OUT/data/visium"; then
  say "already converted: $OUT/data/visium (FORCE=1 to redo)"
else
  run spatialscape convert "$SPE" -o "$OUT/data/visium" --assay logcounts --cols "$COLS"
fi

bold "4. Describe the dataset"
if have "$OUT/dataset.yaml"; then
  say "already described: $OUT/dataset.yaml (FORCE=1 to rewrite)"
else
  run spatialscape init "$OUT/data/visium/*/adata.h5ad" --platform visium --id "$ID" --name "Human amygdala Visium" -o "$OUT/dataset.yaml"
  if [ "${TIDY:-1}" = "1" ] && [ -f "$PALETTE" ]; then
    say "replacing 'fields: auto' with explicit names, shared QC units and the paper's palette"
    "$VENV/bin/python" - "$OUT/dataset.yaml" "$PALETTE" <<'PY'
import sys, yaml, os
path, palette = sys.argv[1], sys.argv[2]
doc = yaml.safe_load(open(path))
doc["palette"] = os.path.relpath(os.path.abspath(palette), os.path.dirname(os.path.abspath(path)))
doc["default_color"] = {"field": "domain"}
doc["fields"] = [{"id": "domain", "name": "Spatial domain", "type": "categorical", "palette_key": "visium_semisupervised"},
                 {"id": "total_counts", "name": "Total counts", "type": "continuous"},
                 {"id": "detected_genes", "name": "Detected genes", "type": "continuous"},
                 {"id": "mito_percent", "name": "Mito %", "type": "continuous"}]
doc["platforms"]["visium"]["fields"] = {"domain": "BS_k16_Semisupervised_wAI", "total_counts": "sum_umi", "detected_genes": "sum_gene",
                                        "mito_percent": {"column": "expr_chrM_ratio", "scale": 100}}
order = ["id", "name", "description", "default_gene", "default_color", "palette", "layout", "fields", "platforms", "samples"]
doc = {k: doc[k] for k in order if k in doc} | {k: v for k, v in doc.items() if k not in order}
yaml.safe_dump(doc, open(path, "w"), sort_keys=False, width=200)
PY
  fi
fi
say "--- $OUT/dataset.yaml ---"; cat "$OUT/dataset.yaml"; say "-------------------------"
run spatialscape plan "$OUT/dataset.yaml"

bold "5. Build the bundle (validates itself, renders thumbnails)"
if have "$OUT/bundles/$ID/manifest.json"; then
  say "already built: $OUT/bundles/$ID (FORCE=1 to rebuild)"
else
  run spatialscape build "$OUT/dataset.yaml" -o "$OUT/bundles/$ID" -q
fi
run spatialscape validate "$OUT/bundles/$ID"

bold "6. Assemble the site to upload"
run spatialscape site build "$OUT/bundles" -o "$OUT/site" --title "Human amygdala"

bold "7. Open it"
say "bundle : $(du -sh "$OUT/bundles/$ID" | cut -f1) in $OUT/bundles/$ID"
say "site   : $(du -sh "$OUT/site" | cut -f1) in $OUT/site   (upload this folder as-is, or serve it: spatialscape serve $OUT/site)"
if [ -n "${NO_SERVE:-}" ]; then
  say "NO_SERVE set; to look at it: $VENV/bin/spatialscape serve $OUT/bundles --open"
else
  if (command -v lsof >/dev/null && lsof -ti tcp:"$PORT" >/dev/null 2>&1); then
    echo "port $PORT is busy; stop that server or run with PORT=8790"; exit 1
  fi
  say "starting the viewer; Ctrl-C stops it"
  run spatialscape serve "$OUT/bundles" --port "$PORT" --open
fi
