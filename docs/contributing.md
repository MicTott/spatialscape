# Contributing

The full guide lives in [`CONTRIBUTING.md`](https://github.com/MicTott/spatialscape/blob/main/CONTRIBUTING.md) in the repository. The short version:

```bash
git clone https://github.com/MicTott/spatialscape && cd spatialscape
python3 -m venv python/.venv && python/.venv/bin/pip install -e "python[dev]"
npm install
python/.venv/bin/pre-commit install      # ruff + pytest + tsc before each commit
```

Run the app with `npm run dev` and the data server with `python/.venv/bin/spatialscape serve examples --port 8787`. Tests: `pytest python/tests`, `npm test`, `npm run e2e`. Docs: `npm run docs:dev`; the CLI reference pages are generated with `npm run docs:gen` from the help strings in `cli.py`, so edit those rather than the pages.

Keep the viewer data-driven: anything dataset-specific belongs in `dataset.yaml`, not in the app. Changes to the bundle format bump `formatVersion` in both the Python and TypeScript models.
