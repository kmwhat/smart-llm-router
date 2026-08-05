import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.cli import build_parser, main


class CliTests(unittest.TestCase):
    def test_package_launcher_binds_staged_source_with_external_venv(self) -> None:
        tool_root = Path(__file__).resolve().parents[1]
        package_launcher = tool_root.parent / "bin" / "smart-llm-router"
        launcher = (
            package_launcher if package_launcher.is_file() else tool_root / "bin" / "smart-llm-router"
        )
        env = dict(os.environ)
        env.update({"SMART_LLM_PYTHON": sys.executable, "PYTHONPATH": ""})
        result = subprocess.run(
            [str(launcher), "--version"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.stdout.strip(), "smart-llm-router 0.8.4")

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

    def test_task_parses_runtime_workflow_budget(self) -> None:
        args = build_parser().parse_args([
            "task", "audit it", "--paid", "--max-cost-usd", "0.01",
            "--workflow-id", "wf-1", "--workflow-max-cost-usd", "0.02",
            "--workflow-stage", "audit",
        ])
        self.assertEqual(args.workflow_id, "wf-1")
        self.assertEqual(args.workflow_max_cost_usd, 0.02)
        self.assertEqual(args.workflow_stage, "audit")

    def test_task_cli_rejects_nonfinite_budget_ceilings_before_settings_or_send(self) -> None:
        cases = []
        for value in ("nan", "inf", "-inf"):
            cases.append(["smart-llm-router", "task", "audit", "--paid", "--max-cost-usd", value])
            cases.append([
                "smart-llm-router", "task", "audit", "--paid", "--max-cost-usd", "0.01",
                "--workflow-id", "wf-cli", "--workflow-max-cost-usd", value,
            ])
        for argv in cases:
            with self.subTest(argv=argv), patch.object(sys, "argv", argv), patch.object(
                sys, "stderr", io.StringIO()
            ), patch(
                "smart_llm_router.cli.load_settings"
            ) as load_settings, patch("smart_llm_router.cli.run_llm_task") as send:
                with self.assertRaises(SystemExit):
                    main()
                load_settings.assert_not_called()
                send.assert_not_called()

    def test_task_parses_qwen_thinking_controls(self) -> None:
        args = build_parser().parse_args([
            "task", "research", "--thinking-mode", "enabled",
            "--thinking-budget-tokens", "800",
            "--final-answer-reserve-tokens", "400",
        ])
        self.assertEqual(args.thinking_mode, "enabled")
        self.assertEqual(args.thinking_budget_tokens, 800)
        self.assertEqual(args.final_answer_reserve_tokens, 400)

    def test_route_stats_command_parses_task_and_window(self) -> None:
        args = build_parser().parse_args(["route-stats", "--task", "audit", "--limit", "250"])
        self.assertEqual(args.command, "route-stats")
        self.assertEqual(args.task, "audit")
        self.assertEqual(args.limit, 250)

    def test_credential_status_defaults_to_free_remote_families(self) -> None:
        args = build_parser().parse_args(["credential-status", "--timeout", "3"])
        self.assertEqual(args.command, "credential-status")
        self.assertEqual(args.families, "openrouter,qwen,nvidia,groq")
        self.assertEqual(args.timeout, 3)

    def test_transcript_correction_defaults_to_general_domain(self) -> None:
        args = build_parser().parse_args(["transcript-correct", "transcript.txt"])
        self.assertEqual(args.domain, "general")
        self.assertFalse(args.paid_main)

    def test_execution_commands_default_to_no_paid_authorization(self) -> None:
        task = build_parser().parse_args(["task", "run it"])
        remote_asr = build_parser().parse_args(["remote-transcribe", "audio.wav", "--provider", "zhipu"])
        embed = build_parser().parse_args(["embed", "text"])
        rerank = build_parser().parse_args(["rerank", "candidate", "--query", "query"])
        self.assertFalse(task.paid)
        self.assertFalse(remote_asr.allow_paid)
        self.assertFalse(embed.allow_paid)
        self.assertFalse(rerank.allow_paid)

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

    def test_adapter_lifecycle_command_parses_evidence_files(self) -> None:
        args = build_parser().parse_args(
            [
                "adapter-lifecycle",
                "adapter.json",
                "transition.json",
                "--promotion-decision",
                "promotion.json",
                "--output",
                "receipt.json",
                "--state-dir",
                "runtime/adapters",
            ]
        )
        self.assertEqual(args.command, "adapter-lifecycle")
        self.assertEqual(args.promotion_decision, "promotion.json")
        self.assertEqual(args.state_dir, "runtime/adapters")


if __name__ == "__main__":
    unittest.main()
