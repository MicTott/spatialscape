#!/usr/bin/env bash
# One row of the build table: `spatialscape build` from a clean output folder under /usr/bin/time, then the bundle's
# bytes per store. Writes benchmarks/results/build-<name>.json and leaves the log beside it.
#   bash benchmarks/build_bench.sh <name> <dataset.yaml> [extra build args]
# Runs on macOS (`time -l`) or Linux (`time -v`). The output folder is a scratch location and is removed afterwards;
# the dataset's own bundle is not touched. The row names the machine, the commit and the exact command.
set -euo pipefail
cd "$(dirname "$0")/.."
name="${1:?name}"; yaml="${2:?dataset.yaml}"; shift 2
SS="${SPATIALSCAPE:-python/.venv/bin/spatialscape}"
PY="${PYTHON:-python/.venv/bin/python}"
out="${BENCH_OUT:-/tmp/spatialscape-bench}/$name"
rm -rf "$out"; mkdir -p "$out" benchmarks/results
log="benchmarks/results/build-$name.log"
cmd=("$SS" build "$yaml" -o "$out/bundle" "$@")
echo "# $(date -u +%FT%TZ) $(uname -m) $(hostname) commit $(git rev-parse --short HEAD) $("$SS" --version)" > "$log"
echo "# ${cmd[*]}" >> "$log"
if [ "$(uname)" = Darwin ]; then
  /usr/bin/time -l "${cmd[@]}" >> "$log" 2>&1
else
  /usr/bin/time -v "${cmd[@]}" >> "$log" 2>&1
fi
"$PY" benchmarks/bundle_size.py "$out/bundle" --json "$out/size.json" | tail -n +1 >> "$log"
"$PY" - "$name" "$yaml" "$log" "$out" <<'EOF'
import json, re, sys, platform, subprocess, datetime
from pathlib import Path
name, yaml, log, out = sys.argv[1:5]
text = Path(log).read_text()
def grab(pat, cast=float):
    m = re.search(pat, text, re.M)
    return cast(m.group(1)) if m else None
if platform.system() == "Darwin":
    wall = grab(r"^\s*([\d.]+) real"); user = grab(r"([\d.]+) user"); sys_ = grab(r"([\d.]+) sys")
    rss = grab(r"(\d+)\s+maximum resident set size", int)
else:
    def hms(s):
        p = [float(x) for x in s.split(":")]; return p[0]*3600+p[1]*60+p[2] if len(p) == 3 else p[0]*60+p[1]
    wall = grab(r"Elapsed \(wall clock\) time.*: ([\d:.]+)", hms); user = grab(r"User time \(seconds\): ([\d.]+)"); sys_ = grab(r"System time \(seconds\): ([\d.]+)")
    rss = grab(r"Maximum resident set size \(kbytes\): (\d+)", int); rss = rss * 1024 if rss else None
size = json.loads((Path(out) / "size.json").read_text())
cache = Path(out) / "bundle" / ".cache"
cache_bytes = sum(p.stat().st_size for p in cache.rglob("*") if p.is_file()) if cache.exists() else 0
mach = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip() if platform.system() == "Darwin" else platform.processor()
row = {
    "name": name, "yaml": yaml, "date": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
    "machine": {"cpu": mach, "system": platform.platform()},
    "command": text.splitlines()[1][2:],
    "wall_s": wall, "user_s": user, "sys_s": sys_, "max_rss_bytes": rss, "cache_bytes": cache_bytes,
    "samples": size["samples"], "nObs": size["nObs"], "molecules": size["molecules"],
    "bundle_bytes": size["total_bytes"], "bytes": size["bytes"], "bytes_per_cell": size["bytes_per_cell"], "bytes_per_molecule": size["bytes_per_molecule"],
    "built": grab(r"^built .*: (.*)$", str),
}
Path(f"benchmarks/results/build-{name}.json").write_text(json.dumps(row, indent=1))
print(f"{name}: {wall:.0f} s wall, {user:.0f} s user, {rss/1e9:.1f} GB peak RSS, bundle {size['total_bytes']/1e9:.2f} GB, cache {cache_bytes/1e9:.2f} GB")
EOF
rm -rf "$out"
