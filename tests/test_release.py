from __future__ import annotations

import importlib.util
import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    tomllib = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "tools" / "check_distribution.py"
SPEC = importlib.util.spec_from_file_location("check_distribution", CHECKER_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)

LINK_CHECKER_PATH = ROOT / "tools" / "check_markdown_links.py"
LINK_SPEC = importlib.util.spec_from_file_location(
    "check_markdown_links", LINK_CHECKER_PATH
)
assert LINK_SPEC is not None and LINK_SPEC.loader is not None
LINK_CHECKER = importlib.util.module_from_spec(LINK_SPEC)
LINK_SPEC.loader.exec_module(LINK_CHECKER)


class OpenSourceReleaseTests(unittest.TestCase):
    def test_community_health_files_exist(self) -> None:
        required = (
            "CODE_OF_CONDUCT.md",
            "CONTRIBUTING.md",
            "GOVERNANCE.md",
            "MANIFEST.in",
            "README.en.md",
            "RELEASING.md",
            "SECURITY.md",
            "SUPPORT.md",
            "docs/architecture.md",
            ".github/ISSUE_TEMPLATE/bug_report.yml",
            ".github/ISSUE_TEMPLATE/feature_request.yml",
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/dependabot.yml",
            ".github/workflows/codeql.yml",
            "requirements/release.txt",
        )
        for relative_path in required:
            with self.subTest(path=relative_path):
                self.assertTrue((ROOT / relative_path).is_file())

    def test_package_metadata_uses_pep_639_license_fields(self) -> None:
        if tomllib is None:
            self.skipTest("tomllib is built in on Python 3.11 and newer")
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        project = data["project"]
        self.assertEqual(project["license"], "MIT")
        self.assertEqual(
            set(project["license-files"]),
            {"LICENSE", "LICENSES/*", "THIRD_PARTY_NOTICES.md"},
        )
        self.assertEqual(project["dependencies"], [])

    def test_ci_has_read_only_default_permissions_and_package_gate(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("python -m build", workflow)
        self.assertIn("python -m twine check dist/*", workflow)
        self.assertIn("python tools/check_distribution.py dist/*", workflow)
        self.assertIn("python tools/check_markdown_links.py .", workflow)
        self.assertIn("Test source distribution", workflow)
        self.assertIn(
            "PYTHONPATH=src python -m unittest discover -s tests -v", workflow
        )
        self.assertIn("magov plan examples/research_task.json", workflow)
        self.assertIn("magov plan examples/coupled_task.json", workflow)
        self.assertNotIn("uses: actions/checkout@v", workflow)
        self.assertNotIn("uses: actions/setup-python@v", workflow)

        codeql = (ROOT / ".github" / "workflows" / "codeql.yml").read_text()
        self.assertNotIn("uses: actions/checkout@v", codeql)
        self.assertNotIn("uses: github/codeql-action/init@v", codeql)
        self.assertNotIn("uses: github/codeql-action/analyze@v", codeql)

    def test_repository_markdown_links_resolve_locally(self) -> None:
        self.assertEqual(LINK_CHECKER.broken_local_links(ROOT), [])

    def test_markdown_link_checker_reports_file_and_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "valid [file](guide.md)\n"
                "missing [file](absent.md)\n"
                "escape [directory](..)\n"
            )
            (root / "guide.md").write_text("# Guide\n")
            self.assertEqual(
                LINK_CHECKER.broken_local_links(root),
                [
                    "README.md:2: missing absent.md",
                    "README.md:3: target escapes root ..",
                ],
            )

    def test_validation_batch_preserves_non_claim_boundary(self) -> None:
        result_root = ROOT / "evals" / "results" / "pilot-v2-validation-20260731"
        metadata = json.loads((result_root / "metadata.json").read_text())
        comparison = json.loads(
            (result_root / "comparison.real.json").read_text()
        )

        self.assertEqual(len(metadata["tasks"]), 7)
        self.assertEqual(metadata["combined_usage"]["actual_total_agents"], 49)
        self.assertEqual(metadata["combined_usage"]["total_tokens"], 5_555_865)
        for record in (metadata, comparison):
            self.assertEqual(record["status"], "descriptive_only")
            self.assertIs(record["claim_allowed"], False)
            self.assertEqual(record["engineering_result"], "inconclusive")
        self.assertEqual(comparison["paired_trials"], 7)
        self.assertEqual(comparison["adaptive_cap_censored_trials"], 0)

    def test_distribution_checker_accepts_complete_archives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = root / "example-1.0-py3-none-any.whl"
            sdist = root / "example-1.0.tar.gz"

            with zipfile.ZipFile(wheel, "w") as archive:
                for legal_file in CHECKER.REQUIRED_LEGAL_FILES:
                    archive.writestr(
                        f"example-1.0.dist-info/licenses/{legal_file}",
                        "license text",
                    )
                archive.writestr(
                    "example-1.0.dist-info/METADATA",
                    "Metadata-Version: 2.4\nLicense-Expression: MIT\n",
                )
                archive.writestr("example/__init__.py", "")

            source_root = root / "example-1.0"
            source_root.mkdir()
            for required_file in CHECKER.REQUIRED_SDIST_FILES:
                path = source_root / required_file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("license text")
            with tarfile.open(sdist, "w:gz") as archive:
                archive.add(source_root, arcname=source_root.name)

            CHECKER.validate_distribution(wheel)
            CHECKER.validate_distribution(sdist)


if __name__ == "__main__":
    unittest.main()
