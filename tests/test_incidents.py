import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.incidents import read_route_incidents, write_route_incident
from smart_llm_router.router import LLMChoice, RouteState, _cooldown_for_error, _record_failure


class RouteIncidentTests(unittest.TestCase):
    def test_incident_is_deidentified_and_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            row = write_route_incident(
                Path(tmp), provider="gemini-frontier-paid", model="gemini-2.5-pro",
                task="plan", failure_class="unavailable_model", status_code=404,
                error="GET https://example.test/chat/completions Bearer secret-value",
                billing_class="paid",
            )
            self.assertEqual(row["secret_values_persisted"], False)
            stored = json.loads(Path(row["incident_path"]).read_text())
            self.assertNotIn("secret-value", json.dumps(stored))
            self.assertEqual(read_route_incidents(Path(tmp))[0]["status_code"], 404)

    def test_404_route_cooldown_is_long_enough_to_quarantine_stale_model(self) -> None:
        self.assertGreaterEqual(_cooldown_for_error(RuntimeError("404 Not Found"), 1).days, 29)

    def test_record_failure_writes_incident_without_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                data_dir=Path(tmp), providers=(), timeout=1, empty_pool_refresh_timeout=1,
                empty_pool_refresh_limit=1,
            )
            provider = LLMProvider("doubao-frontier-paid", "https://ark.test/v1", "ARK_API_KEY", ("seed",), False, 1, "paid")
            choice = LLMChoice(provider, "seed")
            states: dict[str, RouteState] = {}
            with patch.dict("os.environ", {"ARK_API_KEY": "secret"}, clear=False):
                _record_failure(settings, choice, states, RuntimeError("Client error 404 for https://ark.test/v1/chat/completions"))
            rows = read_route_incidents(Path(tmp))
            self.assertEqual(rows[0]["failure_class"], "unavailable_model")
            self.assertTrue(states["doubao-frontier-paid/seed"].unavailable_until)


if __name__ == "__main__":
    unittest.main()
