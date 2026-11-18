# Releasing

A release is a tag. Pushing `v<version>` runs `.github/workflows/release.yml`, which tests, builds the wheel with the
viewer inside, publishes it to PyPI and creates the GitHub Release. Zenodo archives every GitHub Release of a
repository it is linked to and gives it a DOI, so the DOI needs no step of its own once the link exists.

## Once, before the first archived release

1. Sign in at <https://zenodo.org> with the GitHub account that owns the repository.
2. Profile menu, *GitHub*, and switch `MicTott/spatialscape` on. A release published before this is not archived.
3. Optional: add your ORCID to the creator in `.zenodo.json` (`"orcid": "0000-0000-0000-0000"`) and to the author in
   `CITATION.cff` (`orcid: "https://orcid.org/0000-0000-0000-0000"`).

Zenodo reads `.zenodo.json` for the record's title, authors, licence and links. GitHub reads `CITATION.cff` for its
"Cite this repository" button. Keep the two in step.

## Each release

1. The version, in one place: `python/src/spatialscape/__init__.py`. The docs and the package follow it.
2. `CITATION.cff`: `version` and `date-released`.
3. `CHANGELOG.md` and `docs/changelog.md`: the release's heading and date.
4. Check: `npm test`, `python/.venv/bin/python -m pytest python/tests`, `npm run docs:build`.
5. Commit, push `main`, wait for the three workflows.
6. Tag and push the tag:

   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

7. The release workflow may wait for approval of its `pypi` environment on GitHub. Approve it.
8. Confirm: the version on <https://pypi.org/project/spatialscape/>, the GitHub Release, and the new record on Zenodo.

## After the first DOI exists

Zenodo gives two DOIs: one for the version, and a concept DOI that always points at the latest. Cite the concept DOI
unless the exact version matters.

1. `CITATION.cff`: add `doi: <concept DOI>`.
2. `README.md` and `docs/index.md`: add the Zenodo badge and the DOI to the citation line.
3. `spatialscape-examples`: raise the pinned version in `requirements.txt`.

These changes go out with the next release; the DOI of the release just made cannot be written into that release.
