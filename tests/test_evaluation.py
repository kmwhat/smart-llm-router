import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.evaluation import (
    BLIND_REVIEW_SCHEMA,
    build_promotion_decision,
    evaluate_assertions,
    load_golden_suite,
    run_golden_evaluation,
    validate_golden_suite,
)
from smart_llm_router.router import LLMResult, _append_ledger


class EvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.providers = (
            LLMProvider("qwen-free", "https://qwen.test/v1", "QWEN_KEY", ("qwen-plus-latest",), True, 1, "trial_quota"),
            LLMProvider("deepseek-direct-paid", "https://deepseek.test/v1", "DEEPSEEK_KEY", ("deepseek-v4-pro",), False, 2, "paid"),
        )
        self.settings = Settings(
            data_dir=self.root / "runtime",
            providers=self.providers,
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )

    def _suite(self) -> dict:
        return {
            "schema": "smart_llm_router.golden_suite.v1",
            "suite_id": "audit-test-v1",
            "task": "audit",
            "proposed_role": "audit",
            "proposed_quality_band": 2,
            "quality_target": "draft",
            "privacy": "external_allowed",
            "thresholds": {
                "min_cases": 3,
                "min_case_pass_rate": 1.0,
                "max_baseline_case_regression": 0.0,
                "max_candidate_cost_usd": 0.001,
                "max_call_cost_usd": 0.01,
                "min_health_samples": 3,
                "baseline_required": True,
                "independent_review_required": True,
                "min_candidate_review_pass_rate": 1.0,
                "min_candidate_win_or_tie_rate": 1.0,
                "max_candidate_losses": 0,
            },
            "rubric": ["Find the supplied risk without inventing facts."],
            "cases": [
                {
                    "id": f"case-{index}",
                    "prompt": "只输出 JSON",
                    "context": f"公开审计案例 {index}",
                    "assertions": [
                        {"type": "valid_json"},
                        {"type": "json_required_keys", "values": ["issues", "recommendations"]},
                    ],
                }
                for index in range(1, 4)
            ],
        }

    def test_suite_rejects_secret_fields(self) -> None:
        suite = self._suite()
        suite["api_key"] = "must-not-live-here"
        with self.assertRaisesRegex(ValueError, "secret field"):
            validate_golden_suite(suite)

    def test_assertions_accept_fenced_json_and_required_keys(self) -> None:
        results = evaluate_assertions(
            '```json\n{"issues": [], "recommendations": [], "decision": "pass"}\n```',
            [
                {"type": "valid_json"},
                {"type": "json_required_keys", "values": ["issues", "recommendations"]},
                {"type": "json_field_equals", "path": "decision", "value": "PASS"},
            ],
        )
        self.assertTrue(all(item["passed"] for item in results))

    def test_public_golden_suites_are_valid_and_have_five_cases(self) -> None:
        examples = Path(__file__).resolve().parents[1] / "examples" / "golden-sets"
        expected_tasks = {
            "audit-public-v1.json": "audit",
            "plan-public-v1.json": "plan",
            "execute-public-v1.json": "execute",
            "verify-public-v1.json": "verify",
            "qa-public-v1.json": "qa",
        }
        for filename, task in expected_tasks.items():
            with self.subTest(filename=filename):
                suite = load_golden_suite(examples / filename)
                self.assertEqual(suite["task"], task)
                self.assertEqual(suite["proposed_role"], task)
                self.assertEqual(len(suite["cases"]), 5)

    def test_golden_run_and_independent_review_can_pass_promotion_gate(self) -> None:
        suite_path = self.root / "suite.json"
        suite_path.write_text(json.dumps(self._suite(), ensure_ascii=False), encoding="utf-8")

        def fake_run(_settings: Settings, **kwargs: object) -> LLMResult:
            provider = str(kwargs["provider"])
            model = str(kwargs["model"])
            free = provider == "qwen-free"
            ledger_id = _append_ledger(
                self.settings,
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "event": "model_call",
                    "task": "audit",
                    "provider": provider,
                    "model": model,
                    "free": free,
                    "latency_s": 0.5,
                    "estimated_cost_usd": 0.0 if free else 0.0001,
                },
            )
            return LLMResult(
                provider=provider,
                model=model,
                content='{"issues": ["risk"], "recommendations": ["fix"]}',
                ledger_id=ledger_id,
            )

        env = {"QWEN_KEY": "test", "DEEPSEEK_KEY": "test"}
        with patch.dict(os.environ, env, clear=True):
            with patch("smart_llm_router.evaluation.run_llm_task", side_effect=fake_run):
                manifest = run_golden_evaluation(
                    self.settings,
                    suite_path=suite_path,
                    candidate_provider="qwen-free",
                    candidate_model="qwen-plus-latest",
                    baseline_provider="deepseek-direct-paid",
                    baseline_model="deepseek-v4-pro",
                    output_dir=self.root / "evaluations",
                    allow_paid=True,
                )

        report_path = Path(manifest["report_path"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        hold = build_promotion_decision(self.settings, report_path=report_path)
        self.assertEqual(hold["status"], "hold")
        self.assertIn("independent_review_missing", hold["reasons"])

        review = {
            "schema": BLIND_REVIEW_SCHEMA,
            "review_packet_id": report["review_packet_id"],
            "report_id": report["report_id"],
            "reviewer": {"type": "model", "model_family": "zhipu", "provider": "zhipu", "model": "glm-test"},
            "verdicts": [
                {
                    "case_id": case_id,
                    "winner": candidate_label,
                    "quality_a": "pass",
                    "quality_b": "pass",
                    "rationale": "candidate meets the rubric",
                }
                for case_id, candidate_label in report["blind_key"].items()
            ],
        }
        review_path = report_path.parent / "review.json"
        review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        decision = build_promotion_decision(self.settings, report_path=report_path, review_path=review_path)

        self.assertEqual(decision["status"], "pass")
        self.assertTrue(decision["eligible_for_explicit_role_band_registration"])
        self.assertFalse(decision["automatic_production_change"])
        self.assertEqual(decision["route_health"]["health_samples"], 3)

    def test_paid_preflight_happens_before_candidate_calls(self) -> None:
        suite_path = self.root / "suite.json"
        suite_path.write_text(json.dumps(self._suite(), ensure_ascii=False), encoding="utf-8")
        with patch.dict(os.environ, {"QWEN_KEY": "test", "DEEPSEEK_KEY": "test"}, clear=True):
            with patch("smart_llm_router.evaluation.run_llm_task") as run:
                with self.assertRaisesRegex(ValueError, "allow-paid"):
                    run_golden_evaluation(
                        self.settings,
                        suite_path=suite_path,
                        candidate_provider="qwen-free",
                        candidate_model="qwen-plus-latest",
                        baseline_provider="deepseek-direct-paid",
                        baseline_model="deepseek-v4-pro",
                        allow_paid=False,
                    )
        run.assert_not_called()

    def test_failed_candidate_skips_paid_baseline(self) -> None:
        suite_path = self.root / "suite.json"
        suite_path.write_text(json.dumps(self._suite(), ensure_ascii=False), encoding="utf-8")

        def invalid_candidate(_settings: Settings, **kwargs: object) -> LLMResult:
            provider = str(kwargs["provider"])
            self.assertEqual(provider, "qwen-free")
            ledger_id = _append_ledger(
                self.settings,
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "event": "model_call",
                    "task": "audit",
                    "provider": provider,
                    "model": str(kwargs["model"]),
                    "latency_s": 0.5,
                    "estimated_cost_usd": 0.0,
                },
            )
            return LLMResult(provider=provider, model=str(kwargs["model"]), content="not-json", ledger_id=ledger_id)

        with patch.dict(os.environ, {"QWEN_KEY": "test", "DEEPSEEK_KEY": "test"}, clear=True):
            with patch("smart_llm_router.evaluation.run_llm_task", side_effect=invalid_candidate) as run:
                manifest = run_golden_evaluation(
                    self.settings,
                    suite_path=suite_path,
                    candidate_provider="qwen-free",
                    candidate_model="qwen-plus-latest",
                    baseline_provider="deepseek-direct-paid",
                    baseline_model="deepseek-v4-pro",
                    output_dir=self.root / "evaluations",
                    allow_paid=True,
                )

        report = json.loads(Path(manifest["report_path"]).read_text(encoding="utf-8"))
        self.assertEqual(run.call_count, 3)
        self.assertIsNone(report["baseline"])
        self.assertEqual(report["baseline_status"], "skipped_candidate_hard_gate")

    def test_call_failure_stops_remaining_candidate_cases(self) -> None:
        suite_path = self.root / "suite.json"
        suite_path.write_text(json.dumps(self._suite(), ensure_ascii=False), encoding="utf-8")
        with patch.dict(os.environ, {"QWEN_KEY": "test", "DEEPSEEK_KEY": "test"}, clear=True):
            with patch("smart_llm_router.evaluation.run_llm_task", side_effect=RuntimeError("429 quota")) as run:
                manifest = run_golden_evaluation(
                    self.settings,
                    suite_path=suite_path,
                    candidate_provider="qwen-free",
                    candidate_model="qwen-plus-latest",
                    baseline_provider="deepseek-direct-paid",
                    baseline_model="deepseek-v4-pro",
                    output_dir=self.root / "evaluations",
                    allow_paid=True,
                )

        report = json.loads(Path(manifest["report_path"]).read_text(encoding="utf-8"))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(report["candidate"]["results"][1]["error"], "skipped_after_route_failure")
        self.assertEqual(report["baseline_status"], "skipped_candidate_hard_gate")

    def test_hard_gate_failure_skips_unnecessary_blind_review(self) -> None:
        report = {
            "schema": "smart_llm_router.golden_report.v1",
            "report_id": "ger_failed",
            "suite_id": "audit-test-v1",
            "task": "audit",
            "proposed_role": "audit",
            "proposed_quality_band": 2,
            "thresholds": {
                "min_cases": 3,
                "min_case_pass_rate": 0.8,
                "max_baseline_case_regression": 0.0,
                "max_candidate_cost_usd": 0.001,
                "min_health_samples": 3,
                "baseline_required": True,
                "independent_review_required": True,
            },
            "candidate": {
                "provider": "qwen-free",
                "model": "qwen-plus-latest",
                "model_family": "qwen",
                "free": True,
                "billing_class": "trial_quota",
                "case_count": 3,
                "successful_calls": 2,
                "passed_cases": 0,
                "case_pass_rate": 0.0,
                "total_estimated_cost_usd": 0.0,
                "unknown_cost_calls": 0,
            },
            "baseline": {
                "provider": "deepseek-direct-paid",
                "model": "deepseek-v4-pro",
                "model_family": "deepseek",
                "case_count": 3,
                "successful_calls": 3,
                "passed_cases": 3,
                "case_pass_rate": 1.0,
                "total_estimated_cost_usd": 0.001,
            },
        }
        for _ in range(3):
            _append_ledger(
                self.settings,
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "event": "model_call",
                    "task": "audit",
                    "provider": "qwen-free",
                    "model": "qwen-plus-latest",
                    "latency_s": 0.5,
                    "estimated_cost_usd": 0.0,
                },
            )
        report_path = self.root / "failed-report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")

        decision = build_promotion_decision(self.settings, report_path=report_path)

        self.assertEqual(decision["status"], "hold")
        self.assertNotIn("independent_review_missing", decision["reasons"])
        self.assertEqual(decision["review"], {"status": "skipped", "reason": "hard_gate_failure", "cost_avoided": True})


if __name__ == "__main__":
    unittest.main()
