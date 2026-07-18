from datetime import timedelta
import unittest

import httpx

from smart_llm_router.router import _cooldown_for_error


class RouterCooldownTests(unittest.TestCase):
    def test_uses_retry_after_header_for_rate_limits(self) -> None:
        request = httpx.Request("POST", "https://example.test/v1/chat/completions")
        response = httpx.Response(429, headers={"Retry-After": "90"}, request=request)
        exc = httpx.HTTPStatusError("rate limited", request=request, response=response)

        self.assertEqual(_cooldown_for_error(exc, 1), timedelta(seconds=90))

    def test_model_not_found_gets_long_cooldown(self) -> None:
        request = httpx.Request("POST", "https://example.test/v1/chat/completions")
        response = httpx.Response(404, request=request)
        exc = httpx.HTTPStatusError("model not found", request=request, response=response)

        self.assertEqual(_cooldown_for_error(exc, 1), timedelta(days=7))

    def test_retired_model_gets_long_cooldown(self) -> None:
        request = httpx.Request("POST", "https://example.test/v1/chat/completions")
        response = httpx.Response(410, request=request)
        exc = httpx.HTTPStatusError("model retired", request=request, response=response)

        self.assertEqual(_cooldown_for_error(exc, 1), timedelta(days=7))

    def test_timeout_stays_short_and_progressive(self) -> None:
        exc = TimeoutError("The read operation timed out")

        self.assertEqual(_cooldown_for_error(exc, 2), timedelta(minutes=20))


if __name__ == "__main__":
    unittest.main()
