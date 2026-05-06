from __future__ import annotations

import unittest
from pathlib import Path

PRECOMMIT = Path(__file__).resolve().parents[1] / ".pre-commit-config.yaml"


class PreCommitConfigTests(unittest.TestCase):
    def test_precommit_mirrors_documented_local_checks(self) -> None:
        text = PRECOMMIT.read_text(encoding="utf-8")

        self.assertIn("id: ruff-check", text)
        self.assertIn("entry: uv run ruff check app/ tests/", text)
        self.assertIn("id: ruff-format-check", text)
        self.assertIn("entry: uv run ruff format --check app/ tests/", text)
        self.assertIn("id: mypy", text)
        self.assertIn("entry: uv run mypy app/ tests/", text)
        self.assertIn("id: pytest", text)
        self.assertIn("entry: uv run python -m pytest tests/ -v", text)


if __name__ == "__main__":
    unittest.main()
