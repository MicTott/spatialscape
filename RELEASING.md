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

## The DOI

Zenodo gives two DOIs: one for each version, and a concept DOI that always points at the latest. The concept DOI is
[10.5281/zenodo.24376035](https://doi.org/10.5281/zenodo.24376035); the first archived version is 1.0.0. `CITATION.cff`, the badge and
citation line in `README.md`, and the citing section of `docs/index.md` carry the concept DOI, so they need no change
at a release. Cite a version's own DOI only when the exact version matters; Zenodo lists them on the record's page.

Zenodo archives a release only if the repository was switched on there before the GitHub Release was published. If a
release is missed, delete that Release on GitHub (keep the tag) and publish a new one from the same tag.

After a release, in `spatialscape-examples`: raise the pinned version in `requirements.txt`.
