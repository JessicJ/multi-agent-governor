# Release process

This project uses semantic versioning while the public API is experimental.
Release notes must distinguish implemented behavior from descriptive evaluation
evidence.

## Prepare a release candidate

1. Start from a reviewed commit on `main` with a clean working tree.
2. Update the package version in `pyproject.toml`, the plugin version in
   `plugins/multi-agent-governor/.codex-plugin/plugin.json`, and `CHANGELOG.md`.
3. Run the complete local release gate:

   ```bash
   PYTHONPATH=src python -m unittest discover -s tests -v
   PYTHONPATH=src python -m magov.eval_cli validate \
     evals/pilot_manifest.json --workspace .
   python -m compileall -q src tests \
     plugins/multi-agent-governor/skills/multi-agent-governor/scripts
   python tools/check_markdown_links.py .
   git diff --check

   python -m pip install --requirement requirements/release.txt
   python -m build
   python -m twine check dist/*
   python tools/check_distribution.py dist/*
   ```

4. Install the wheel into a new virtual environment and run both CLI help
   commands plus the scripted end-to-end example.
5. Validate the plugin manifest and Skill with the Codex plugin and Skill
   validators.
6. Confirm every experimental result still says:

   ```text
   status: descriptive_only
   claim_allowed: false
   engineering_result: inconclusive
   ```

7. Verify the repository-owner settings listed in
   [docs/open-source-readiness.md](docs/open-source-readiness.md).

## Publish

Create a signed, annotated tag only after the release candidate commit and
required CI checks pass. Prefer PyPI trusted publishing and a GitHub
environment with approval over long-lived upload tokens. Upload the wheel and
source distribution generated from the tagged commit, then attach the same
archives and checksums to the GitHub release.

After publication, install from the public index in a clean environment and
repeat the CLI smoke tests. Do not move or replace an existing release tag or
published archive; issue a new patch release for corrections.

Publishing, changing repository settings, creating tags, and pushing commits
are repository-owner actions and are intentionally not performed by the local
release gate.
