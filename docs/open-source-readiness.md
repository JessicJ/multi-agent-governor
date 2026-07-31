# Open source release readiness

This checklist defines “ready to open source” for Multi-Agent Governor. It is a
release gate, not a claim that the experimental policy has been proven
effective.

The checklist follows GitHub's
[community health guidance](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions),
the Python Packaging User Guide's
[project metadata guidance](https://packaging.python.org/en/latest/specifications/pyproject-toml/),
and OpenSSF Scorecard's
[supply-chain checks](https://scorecard.dev/).

## Local repository gates

- [x] OSI-compatible project license and third-party notices.
- [x] README with installation, runtime boundaries, and non-claims.
- [x] Contribution, support, governance, security, and conduct policies.
- [x] Structured issue forms and pull-request checklist.
- [x] CI across supported Python versions with read-only default permissions.
- [x] Third-party GitHub Actions pinned to reviewed full commit SHAs.
- [x] CodeQL workflow with minimal permissions.
- [x] Automated dependency update configuration.
- [x] Core package has no third-party runtime dependency.
- [x] Build both wheel and source distribution and validate package metadata.
- [x] Verify license and notice files are present in both distribution formats.
- [x] Add an English quick-start path for an international audience.
- [x] Complete the frozen real-task validation batch and publish an aggregate
      descriptive report.
- [x] Run final tests, compileall, manifest validation, package installation
      smoke tests, plugin/Skill validation, and `git diff --check`.
- [x] Confirm the tracked working tree is clean at a release candidate commit.

## GitHub settings that require repository-owner action

- [ ] Make CI a required status check for the default branch.
- [ ] Protect the default branch and require pull-request review.
- [ ] Enable Dependabot alerts and security updates.
- [ ] Enable private vulnerability reporting.
- [ ] Enable secret scanning and push protection where available.
- [ ] Configure repository description, topics, and social preview.
- [ ] Create a signed, immutable release tag after the local gates pass.

These settings cannot be proven by local files. The release report must list
them as external blockers until a repository owner verifies them.

## Evidence boundary

Public historical tasks validate isolation, accounting, stopping, and
descriptive behavior. They are not an unseen benchmark and cannot authorize a
claim that Governor is generally effective. Any effectiveness claim requires a
separately held-out evaluation set and the preregistered product guardrails.
