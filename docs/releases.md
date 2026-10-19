# Release procedures

The package uses `.github/workflows/release.yaml`, PyPI Trusted Publishing and
the GitHub environment `pypi`. The publisher identity is organization
`outside-labs`, repository `headless_spreadsheets`, workflow `release.yaml`,
environment `pypi`. No long-lived PyPI secret is needed.

1. Merge the selected work with fresh passing checks. Confirm a clean main,
   matching package/public API versions, changelog and current limitations.
2. Run `uv run --frozen python scripts/check_distribution.py --tag v0.1.0`.
   It checks wheel/source allowlists, source bytes, MIT metadata/license,
   `py.typed`, empty runtime requirements, RECORD hashes, source rebuild parity
   and the full suite in independent installed environments outside the checkout.
3. Ensure the `pypi` deployment policy permits the exact intended release tag.
   The initial environment permits only `v0.1.0`; later versions need a new
   deliberately selected tag policy. Match the pending/existing PyPI publisher
   identity to the values above.
4. Tag the verified main commit and push that tag. The workflow reuses the
   platform test matrix and distribution verification, checks tag/version and
   main ancestry, and uploads only the exact verified wheel/source pair.
5. A separate job, after all checks pass, downloads that pair and publishes
   inside `pypi` with job-local `id-token: write`. Its action has no checkout or
   application code execution step. Action references are immutable revisions.
6. Download `release-distributions` from the successful run. Compare SHA256 hashes
   to PyPI JSON and actual downloaded registry bytes. Install the released
   version uncached in a fresh environment and run the suite/examples there.
7. Create the matching GitHub release and attach the same verified pair. Record
   source SHA, tag, run URLs and hashes on the release issue. Mark selected scope
   Done and retain later decision tasks.

Released files and tags are immutable. Do not delete/recreate a release version,
overwrite a tag or substitute a new build after verification. If publishing
fails, diagnose the exact identity/environment error and retain the verified
artifacts. Account-side configuration changes may require the package owner.

Primary references: [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
and [uv GitHub integration](https://docs.astral.sh/uv/guides/integration/github/).
