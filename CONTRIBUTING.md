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

Install the commit hook once so lint and tests run before every commit: `python/.venv/bin/pre-commit install`.

```bash
python/.venv/bin/python -m pytest python/tests && python/.venv/bin/ruff check python
npm test && npm run e2e
```

## The viewer inside the package

`spatialscape serve` and `spatialscape site build` use a copy of the built viewer at `python/src/spatialscape/_app` (gitignored). Refresh it after app changes with `npm run build && python/.venv/bin/python python/scripts/bundle_app.py`; the release workflow does this before building the wheel, so published packages always carry the matching viewer.

## Docs

`npm run docs:dev` serves the VitePress site from `docs/`; `npm run docs:build` writes `docs/.vitepress/dist`. The Pages workflow publishes it under `/docs/`.

The CLI reference (`docs/reference/cli/`) is generated from the Typer app's own help strings by `python/scripts/gen_cli_docs.py` (`npm run docs:gen`). Edit help text in `python/src/spatialscape/cli.py` and examples in the generator, then re-run it and commit the regenerated pages; the Pages workflow regenerates them as well, so they can never drift from `--help`.

## Where things live

See `docs/reference/architecture.md`. The bundle format is specified in `docs/reference/format.md`; changes to it must bump `formatVersion`
in both `python/src/spatialscape/manifest.py` and `app/src/data/manifest.ts` and keep them in sync.

## Pull requests

Keep the viewer data-driven: anything dataset-specific belongs in `dataset.yaml`, not in the app. Add a test for CLI
changes and extend the Playwright smoke test for viewer changes that affect loading or rendering.
