from __future__ import annotations

import re
import unittest
from pathlib import Path


WORKFLOW_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"
USES_PATTERN = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)")
FULL_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")


class GitHubActionsSecurityTests(unittest.TestCase):
    def test_remote_actions_are_pinned_to_full_commit_shas(self) -> None:
        failures: list[str] = []

        for workflow in sorted((*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml"))):
            for line_number, line in enumerate(workflow.read_text().splitlines(), start=1):
                match = USES_PATTERN.match(line)
                if not match:
                    continue

                action_ref = match.group(1)
                if action_ref.startswith("./") or action_ref.startswith("docker://"):
                    continue

                _, separator, revision = action_ref.rpartition("@")
                if not separator or not FULL_SHA_PATTERN.fullmatch(revision):
                    failures.append(f"{workflow.name}:{line_number}: {action_ref}")

        self.assertEqual(
            failures,
            [],
            "Remote GitHub Actions must use a full 40-character commit SHA:\n"
            + "\n".join(failures),
        )


if __name__ == "__main__":
    unittest.main()
