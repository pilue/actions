import os
import sys
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import poll_status


# ---------------------------------------------------------------------------
# fetch_status
# ---------------------------------------------------------------------------


class TestFetchStatus(unittest.TestCase):
    def _mock_response(self, body):
        mock_resp = MagicMock()
        mock_resp.read.return_value = body.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def _mock_http_error(self, code, body="error"):
        exc = urllib.error.HTTPError(
            url="https://example.com",
            code=code,
            msg="Error",
            hdrs=None,
            fp=MagicMock(read=MagicMock(return_value=body.encode())),
        )
        return exc

    def test_returns_parsed_json_and_no_error(self):
        body = '{"status": "completed", "conclusion": "success"}'
        with patch("urllib.request.urlopen", return_value=self._mock_response(body)):
            data, error = poll_status.fetch_status(
                "https://example.com/status", "secret"
            )
        self.assertEqual(data["status"], "completed")
        self.assertIsNone(error)

    def test_returns_empty_dict_and_error_string_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=Exception("network error")):
            data, error = poll_status.fetch_status(
                "https://example.com/status", "secret"
            )
        self.assertEqual(data, {})
        self.assertIn("network error", error)

    def test_returns_empty_dict_and_http_error_string_on_4xx(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=self._mock_http_error(
                401, '{"error": "Invalid publish token"}'
            ),
        ):
            data, error = poll_status.fetch_status(
                "https://example.com/status", "secret"
            )
        self.assertEqual(data, {})
        self.assertIn("401", error)

    def test_returns_empty_dict_and_http_error_string_on_5xx(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=self._mock_http_error(
                500, '{"error": "Server misconfiguration"}'
            ),
        ):
            data, error = poll_status.fetch_status(
                "https://example.com/status", "secret"
            )
        self.assertEqual(data, {})
        self.assertIn("500", error)


# ---------------------------------------------------------------------------
# build_status_url
# ---------------------------------------------------------------------------


class TestBuildStatusUrl(unittest.TestCase):
    def test_url_contains_domain_and_since(self):
        url = poll_status.build_status_url(
            "example.pilue.co.uk", "2026-01-01T00:00:00Z"
        )
        self.assertIn("domain=example.pilue.co.uk", url)
        self.assertIn("since=2026-01-01T00%3A00%3A00Z", url)

    def test_url_base(self):
        url = poll_status.build_status_url("example.pilue.co.uk", "ts")
        self.assertTrue(url.startswith("https://api.davidcloud.co.uk/status"))


# ---------------------------------------------------------------------------
# run_poll_loop
# ---------------------------------------------------------------------------


class TestRunPollLoop(unittest.TestCase):
    def _make_fetch(self, responses):
        """Return a fetch_status mock that yields (data, error) tuples in sequence."""
        it = iter(responses)

        def _fetch(url, secret):
            try:
                resp = next(it)
                # Allow passing raw dicts as shorthand for (dict, None)
                if isinstance(resp, dict):
                    return resp, None
                return resp
            except StopIteration:
                return {}, None

        return _fetch

    def test_success_on_first_poll(self):
        responses = [{"status": "completed", "conclusion": "success"}]
        sleep_calls = []
        with patch.object(
            poll_status, "fetch_status", side_effect=self._make_fetch(responses)
        ):
            success, msg = poll_status.run_poll_loop(
                "example.pilue.co.uk",
                "ts",
                "secret",
                poll_interval=15,
                max_wait=60,
                _sleep=sleep_calls.append,
            )
        self.assertTrue(success)
        self.assertIn("succeeded", msg)
        self.assertEqual(sleep_calls, [])  # no sleep needed

    def test_failure_conclusion(self):
        responses = [{"status": "completed", "conclusion": "failure"}]
        with patch.object(
            poll_status, "fetch_status", side_effect=self._make_fetch(responses)
        ):
            success, msg = poll_status.run_poll_loop(
                "example.pilue.co.uk",
                "ts",
                "secret",
                _sleep=lambda x: None,
            )
        self.assertFalse(success)
        self.assertIn("conclusion: failure", msg)

    def test_waits_through_queued_then_in_progress_then_success(self):
        responses = [
            {"status": "queued"},
            {"status": "in_progress"},
            {"status": "completed", "conclusion": "success"},
        ]
        sleep_calls = []
        with patch.object(
            poll_status, "fetch_status", side_effect=self._make_fetch(responses)
        ):
            success, msg = poll_status.run_poll_loop(
                "example.pilue.co.uk",
                "ts",
                "secret",
                poll_interval=15,
                max_wait=300,
                _sleep=sleep_calls.append,
            )
        self.assertTrue(success)
        self.assertEqual(sleep_calls, [15, 15])  # slept twice before success

    def test_timeout(self):
        # Always return in_progress so it never completes
        with patch.object(
            poll_status, "fetch_status", return_value=({"status": "in_progress"}, None)
        ):
            success, msg = poll_status.run_poll_loop(
                "example.pilue.co.uk",
                "ts",
                "secret",
                poll_interval=10,
                max_wait=20,
                _sleep=lambda x: None,
            )
        self.assertFalse(success)
        self.assertIn("Timed out", msg)

    def test_http_error_fails_immediately(self):
        # A 4xx/5xx error should abort immediately, not retry
        responses = [({}, "HTTP 500: Server misconfiguration")]
        with patch.object(
            poll_status, "fetch_status", side_effect=self._make_fetch(responses)
        ):
            success, msg = poll_status.run_poll_loop(
                "example.pilue.co.uk",
                "ts",
                "secret",
                _sleep=lambda x: None,
            )
        self.assertFalse(success)
        self.assertIn("HTTP 500", msg)

    def test_http_401_fails_immediately(self):
        responses = [({}, "HTTP 401: Invalid publish token")]
        with patch.object(
            poll_status, "fetch_status", side_effect=self._make_fetch(responses)
        ):
            success, msg = poll_status.run_poll_loop(
                "example.pilue.co.uk",
                "ts",
                "secret",
                _sleep=lambda x: None,
            )
        self.assertFalse(success)
        self.assertIn("HTTP 401", msg)

    def test_transient_network_errors_allow_retries(self):
        # Two transient errors then success — should recover
        responses = [
            ({}, "Connection reset"),
            ({}, "Connection reset"),
            {"status": "completed", "conclusion": "success"},
        ]
        with patch.object(
            poll_status, "fetch_status", side_effect=self._make_fetch(responses)
        ):
            success, msg = poll_status.run_poll_loop(
                "example.pilue.co.uk",
                "ts",
                "secret",
                _sleep=lambda x: None,
            )
        self.assertTrue(success)

    def test_three_consecutive_network_errors_fail(self):
        # Three consecutive transient errors should abort
        responses = [
            ({}, "Connection reset"),
            ({}, "Connection reset"),
            ({}, "Connection reset"),
        ]
        with patch.object(
            poll_status, "fetch_status", side_effect=self._make_fetch(responses)
        ):
            success, msg = poll_status.run_poll_loop(
                "example.pilue.co.uk",
                "ts",
                "secret",
                _sleep=lambda x: None,
            )
        self.assertFalse(success)
        self.assertIn("consecutive errors", msg)

    def test_run_url_reported(self):
        responses = [
            {"status": "in_progress", "run_url": "https://github.com/actions/runs/1"},
            {
                "status": "completed",
                "conclusion": "success",
                "run_url": "https://github.com/actions/runs/1",
            },
        ]
        printed = []
        with (
            patch.object(
                poll_status, "fetch_status", side_effect=self._make_fetch(responses)
            ),
            patch("builtins.print", side_effect=printed.append),
        ):
            poll_status.run_poll_loop(
                "example.pilue.co.uk",
                "ts",
                "secret",
                poll_interval=10,
                max_wait=300,
                _sleep=lambda x: None,
            )
        run_url_lines = [line for line in printed if "runs/1" in str(line)]
        # Should only print the run URL once even though it appears in both responses
        self.assertEqual(len(run_url_lines), 1)


if __name__ == "__main__":
    unittest.main()
