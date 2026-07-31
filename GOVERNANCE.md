# Governance

Multi-Agent Governor is a maintainer-led open source project.

## Roles

- **Contributors** propose issues, documentation, tests, evaluation tasks, and
  code changes.
- **Reviewers** provide technical and evaluation-integrity review.
- **Maintainers** have repository write access, merge changes, manage releases,
  and enforce the security policy and code of conduct.

Roles are earned through sustained, constructive contribution. Maintainers may
invite a contributor to take on review or maintenance responsibilities after
the contributor has demonstrated sound judgment and respect for project
boundaries.

## Decisions

Routine changes are decided through pull-request review. Maintainers seek
consensus, but the maintainer responsible for a release makes the final call
when consensus is not possible.

Changes to evaluation truth, scoring rules, policy thresholds, safety
boundaries, or public effectiveness claims require:

1. a written rationale;
2. tests and migration impact;
3. disclosure of whether existing results are invalidated;
4. maintainer approval before merge.

No maintainer may rewrite historical evidence or relax a preregistered
condition to improve a reported result.

## Releases

Maintainers publish releases from reviewed commits after CI, packaging,
license, and release-readiness checks pass. Release notes must distinguish
implemented capability from experimental or descriptive evidence.

## Amendments

Governance changes use the normal pull-request process and should be announced
in the changelog when they materially affect contributors or releases.
