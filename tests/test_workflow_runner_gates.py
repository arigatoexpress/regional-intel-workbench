from __future__ import annotations

import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


class WorkflowRunnerGateTests(unittest.TestCase):
    def test_ci_workflow_uses_sapphire_runner_gate(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        expected_runner = (
            "runs-on: ${{ fromJSON(vars.SAPPHIRE_RUNNER || "
            '\'["self-hosted","sapphire-disabled"]\') }}'
        )

        self.assertIn("if: ${{ vars.SAPPHIRE_RUNNER != '' }}", text)
        self.assertIn(expected_runner, text)
        self.assertIn("REGIONAL_INTEL_UI_SMOKE_ENABLED", text)
        self.assertIn("github.event_name == 'workflow_dispatch'", text)
        self.assertNotIn("runs-on: ${{ fromJSON(vars.SAPPHIRE_RUNNER) }}", text)
        self.assertNotIn("macos-latest", text)
        self.assertNotIn("windows-latest", text)

    def test_default_test_job_does_not_install_browsers(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")

        test_job, ui_job = text.split("  ui-smoke:", maxsplit=1)

        self.assertNotIn("playwright install", test_job)
        self.assertIn("playwright install", ui_job)


if __name__ == "__main__":
    unittest.main()
