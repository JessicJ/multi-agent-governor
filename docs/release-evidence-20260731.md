# Release candidate evidence — 2026-07-31

This record covers the local `0.2.1` open-source release candidate. It records
reproducible engineering checks, not a claim that the adaptive policy is
generally effective.

## Source and evaluation boundary

- Project license: MIT.
- Python package version: `0.2.1`.
- Codex plugin version: `0.2.1+codex.20260730085745`.
- Core package runtime dependencies: none.
- Frozen `pilot-v2` historical batch: 7 real tasks, 21 real arms, 49 Agents,
  and 5,555,865 total tokens.
- Batch conclusion: `descriptive_only`, `claim_allowed: false`,
  `engineering_result: inconclusive`.
- The preregistration file
  `evals/pilot-v2-validation.json` deliberately retains its original
  `preregistered_not_run` state. It is an immutable pre-run artifact; execution
  status and results are recorded separately under
  `evals/results/pilot-v2-validation-20260731/`.

## Local validation

The following checks passed from the repository root:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m magov.eval_cli validate \
  evals/pilot_manifest.json --workspace .
python -m compileall -q src tests \
  plugins/multi-agent-governor/skills/multi-agent-governor/scripts tools
python tools/check_markdown_links.py .
git diff --check
```

Results:

- 87 unit and release tests passed.
- Manifest status was `valid`: 12 tasks, including 8 historical tasks and 4
  injected engineering fixtures.
- All selected Python files compiled.
- All six repository YAML files parsed successfully.
- All repository-local targets in 37 Markdown files resolved.
- No tracked symlinks, generated evaluation runs, build outputs, distribution
  outputs, egg metadata, or bytecode were found.
- A targeted scan found no private-key headers or common AWS, GitHub, OpenAI,
  or Google credential formats outside ignored raw evaluation runs.

The official Codex plugin and Skill validators also passed:

```bash
python /path/to/plugin-creator/scripts/validate_plugin.py \
  plugins/multi-agent-governor
python /path/to/skill-creator/scripts/quick_validate.py \
  plugins/multi-agent-governor/skills/multi-agent-governor
```

## Distribution validation

Both `multi_agent_governor-0.2.1.tar.gz` and
`multi_agent_governor-0.2.1-py3-none-any.whl` were built with `build 1.5.0`.
The following checks passed:

- `twine 7.0.0` metadata validation for both archives;
- the repository distribution checker, including PEP 639
  `License-Expression: MIT`, legal notices, community files, plugin files, and
  evaluation evidence;
- confirmation that evaluation assets are absent from the runtime wheel;
- installation of the wheel without dependencies into a new Python 3.12
  virtual environment;
- `magov --help`, `magov-eval --help`, `pip check`, a scripted `pilot-v2`
  end-to-end run, and event-log replay from that environment;
- all 87 tests from a freshly extracted source distribution.

The first source-distribution smoke test exposed that `.github` community and
workflow files were missing from the archive. `MANIFEST.in` and the
distribution checker were strengthened, the archives were rebuilt, and the
source-distribution suite then passed. This failed attempt is not counted as a
passing release gate.

## Remote verification

Commit `e575164d74d541b8c934869ab029039f7c4bd713` was pushed to the public
`main` branch after the local checks above passed. The resulting remote
verification established:

- [CI run 30599473474](https://github.com/JessicJ/multi-agent-governor/actions/runs/30599473474)
  passed all five supported Python versions and the distribution job.
- [CodeQL run 30599473478](https://github.com/JessicJ/multi-agent-governor/actions/runs/30599473478)
  passed Python analysis.
- `main` requires those seven checks, an up-to-date branch, one approving
  review, resolved review conversations, and linear history; force pushes and
  deletion are disabled. Administrators retain a recovery bypass.
- Dependabot alerts and security updates, private vulnerability reporting,
  secret scanning, push protection, and full-SHA GitHub Actions enforcement
  are enabled.
- The repository description and six discovery topics are configured.
- The Git marketplace snapshot was refreshed to `e575164`, and Codex plugin
  version `0.2.1+codex.20260730085745` was installed into the local plugin
  cache.

Remaining owner actions are to configure a social preview, smoke-test the
freshly installed plugin from a new Codex task, and—only after those checks—create
a signed immutable release tag and decide whether to publish the Python
package. No release tag or package publication was performed.
