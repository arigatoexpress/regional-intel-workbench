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
        self.assertNotIn("runs-on: ${{ fromJSON(vars.SAPPHIRE_RUNNER) }}", text)
        self.assertNotIn("macos-latest", text)
        self.assertNotIn("windows-latest", text)


if __name__ == "__main__":
    unittest.main()
