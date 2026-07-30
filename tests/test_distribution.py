from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import magov


ROOT = Path(__file__).resolve().parents[1]


class DistributionMetadataTests(unittest.TestCase):
    def test_plugin_and_marketplace_point_to_public_project(self) -> None:
        plugin = json.loads(
            (
                ROOT
                / "plugins"
                / "multi-agent-governor"
                / ".codex-plugin"
                / "plugin.json"
            ).read_text()
        )
        marketplace = json.loads(
            (ROOT / ".agents" / "plugins" / "marketplace.json").read_text()
        )

        self.assertEqual(plugin["name"], "multi-agent-governor")
        self.assertTrue(plugin["version"].startswith("0.2.1+codex."))
        self.assertEqual(magov.__version__, "0.2.1")
        self.assertEqual(
            plugin["repository"],
            "https://github.com/JessicJ/multi-agent-governor",
        )
        self.assertEqual(plugin["skills"], "./skills/")
        self.assertEqual(marketplace["name"], "multi-agent-governor")
        self.assertEqual(
            marketplace["plugins"][0]["source"]["path"],
            "./plugins/multi-agent-governor",
        )

    def test_skill_has_invocable_frontmatter_and_wrapper(self) -> None:
        skill_root = (
            ROOT
            / "plugins"
            / "multi-agent-governor"
            / "skills"
            / "multi-agent-governor"
        )
        contents = (skill_root / "SKILL.md").read_text()

        self.assertTrue(contents.startswith("---\n"))
        frontmatter = contents.split("\n---\n", 1)[0]
        self.assertIn("name: multi-agent-governor", frontmatter)
        self.assertIn("description:", frontmatter)
        self.assertTrue((skill_root / "agents" / "openai.yaml").is_file())
        self.assertTrue((skill_root / "scripts" / "run_governor.py").is_file())

    def test_upstream_license_files_match_fixed_revisions(self) -> None:
        expected_hashes = {
            "click-BSD-3-Clause.txt": (
                "9a8ad106a394e853bfe21f42f4e72d592819a22805d991b5f3275029292b658d"
            ),
            "more-itertools-MIT.txt": (
                "09f1c8c9e941af3e584d59641ea9b87d83c0cb0fd007eb5ef391a7e2643c1a46"
            ),
            "attrs-MIT.txt": (
                "882115c95dfc2af1eeb6714f8ec6d5cbcabf667caff8729f42420da63f714e9f"
            ),
            "pluggy-MIT.txt": (
                "d6b65e6c213a5d0b577911d34d6e5949b9f59d76c238c5071a2f3fc16cfb2606"
            ),
        }

        for filename, expected in expected_hashes.items():
            with self.subTest(filename=filename):
                actual = hashlib.sha256(
                    (ROOT / "LICENSES" / filename).read_bytes()
                ).hexdigest()
                self.assertEqual(actual, expected)

    def test_public_pilot_declares_runtime_isolated_truth(self) -> None:
        manifest = json.loads((ROOT / "evals" / "pilot_manifest.json").read_text())

        self.assertEqual(
            manifest["truth_visibility"],
            "repository_public_runtime_isolated",
        )
        self.assertEqual(len(manifest["tasks"]), 12)
        for task in manifest["tasks"]:
            self.assertTrue((ROOT / task["truth_path"]).is_file())

    def test_historical_tasks_materialize_exact_buggy_revisions(self) -> None:
        manifest = json.loads((ROOT / "evals" / "pilot_manifest.json").read_text())
        provenance = json.loads(
            (ROOT / "evals" / "historical_provenance.json").read_text()
        )
        provenance_by_task = {
            item["task_id"]: item for item in provenance["tasks"]
        }

        for task in manifest["tasks"]:
            if task["source"] != "historical":
                continue
            with self.subTest(task_id=task["task_id"]):
                source = provenance_by_task[task["task_id"]]
                self.assertEqual(
                    task["materialization_revision"],
                    source["original_buggy_revision"],
                )
                self.assertEqual(
                    task["test_command"],
                    (
                        "PYTHONPATH=src python -m pytest -q {hidden_test}"
                        if task["changed_files"][0].startswith("src/")
                        else "python -m pytest -q {hidden_test}"
                    ),
                )
                hidden_test = (
                    ROOT
                    / "evals"
                    / "tasks"
                    / task["task_id"]
                    / "hidden_test.py"
                )
                self.assertTrue(hidden_test.is_file())
                self.assertTrue(source["fix_subject"])
                self.assertTrue(source["forbidden_agent_hints"])

    def test_pilot_v2_validation_freezes_all_remaining_history(self) -> None:
        manifest = json.loads((ROOT / "evals" / "pilot_manifest.json").read_text())
        preregistration = json.loads(
            (ROOT / "evals" / "pilot-v2-validation.json").read_text()
        )
        historical = {
            task["task_id"]
            for task in manifest["tasks"]
            if task["source"] == "historical"
        }

        self.assertEqual(preregistration["status"], "preregistered_not_run")
        self.assertEqual(preregistration["development_task"], "python-pr-07")
        self.assertEqual(
            set(preregistration["evaluation_tasks"]),
            historical - {"python-pr-07"},
        )
        self.assertEqual(
            preregistration["task_order"],
            preregistration["evaluation_tasks"],
        )
        self.assertEqual(
            preregistration["arm_order"],
            ["fixed-1", "adaptive-max-4", "fixed-4"],
        )
        self.assertEqual(
            preregistration["runtime"]["policy_version"],
            "pilot-v2",
        )
        self.assertFalse(
            preregistration["runtime"]["allow_model_substitution"]
        )
        self.assertFalse(
            preregistration["result_boundary"]["claim_allowed"]
        )
        self.assertEqual(
            preregistration["result_boundary"]["engineering_result"],
            "inconclusive",
        )
        hard_total = sum(
            arm["max_total_tokens"] for arm in preregistration["arms"]
        ) * len(preregistration["evaluation_tasks"])
        self.assertEqual(
            preregistration["estimated_usage"]["hard_total_tokens"],
            hard_total,
        )


if __name__ == "__main__":
    unittest.main()
