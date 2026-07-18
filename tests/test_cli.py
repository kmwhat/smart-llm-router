import unittest

from smart_llm_router.cli import build_parser


class CliTests(unittest.TestCase):
    def test_credential_catalog_is_a_global_option(self) -> None:
        args = build_parser().parse_args(["--credential-catalog", "/tmp/catalog", "providers"])
        self.assertEqual(args.credential_catalog, "/tmp/catalog")
        self.assertEqual(args.command, "providers")

    def test_frontier_role_and_ark_discovery_commands_parse(self) -> None:
        role = build_parser().parse_args([
            "task",
            "plan it",
            "--task",
            "plan",
            "--quality-target",
            "frontier",
            "--max-cost-usd",
            "0.05",
        ])
        discovery = build_parser().parse_args(["discover-ark", "--limit", "20"])
        self.assertEqual(role.task, "plan")
        self.assertEqual(role.quality_target, "frontier")
        self.assertEqual(discovery.command, "discover-ark")

    def test_workflow_commands_parse(self) -> None:
        plan = build_parser().parse_args(["workflow-plan", "contract.json", "--output-dir", "artifacts"])
        check = build_parser().parse_args(["workflow-check", "contract.json", "checkpoint.json"])
        self.assertEqual(plan.command, "workflow-plan")
        self.assertEqual(check.command, "workflow-check")

    def test_route_stats_command_parses_task_and_window(self) -> None:
        args = build_parser().parse_args(["route-stats", "--task", "audit", "--limit", "250"])
        self.assertEqual(args.command, "route-stats")
        self.assertEqual(args.task, "audit")
        self.assertEqual(args.limit, 250)

    def test_golden_eval_and_promotion_commands_parse(self) -> None:
        golden = build_parser().parse_args([
            "golden-eval",
            "suite.json",
            "--provider",
            "groq-free",
            "--model",
            "qwen/qwen3.6-27b",
            "--baseline-provider",
            "deepseek-direct-paid",
            "--baseline-model",
            "deepseek-v4-pro",
            "--allow-paid",
        ])
        promotion = build_parser().parse_args(["promotion-check", "report.json", "--review", "review.json"])
        self.assertEqual(golden.command, "golden-eval")
        self.assertTrue(golden.allow_paid)
        self.assertEqual(promotion.command, "promotion-check")


if __name__ == "__main__":
    unittest.main()
