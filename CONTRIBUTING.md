# Contributing

## Setup

```bash
git clone https://github.com/mictott/spatialscape && cd spatialscape
python3 -m venv python/.venv && python/.venv/bin/pip install -e "python[dev]"
npm install
```

## Run

```bash
python/.venv/bin/spatialscape synth /tmp/synth && python/.venv/bin/spatialscape build /tmp/synth/dataset.yaml -o examples/synthetic
python/.venv/bin/spatialscape serve examples --port 8787   # terminal 1
npm run dev                                                  # terminal 2 -> http://127.0.0.1:5173/?d=http://127.0.0.1:8787/synthetic
```

## Test

```bash
python/.venv/bin/python -m pytest python/tests && python/.venv/bin/ruff check python
npm test && npm run e2e
```

## Where things live

See `docs/architecture.md`. The bundle format is specified in `docs/format.md`; changes to it must bump `formatVersion`
in both `python/src/spatialscape/manifest.py` and `app/src/data/manifest.ts` and keep them in sync.

## Pull requests

Keep the viewer data-driven: anything dataset-specific belongs in `dataset.yaml`, not in the app. Add a test for CLI
changes and extend the Playwright smoke test for viewer changes that affect loading or rendering.
