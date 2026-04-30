import hashlib
import hmac
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import send_publish


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_ENV = {
    "DOMAIN": "example.pilue.co.uk",
    "REPO": "https://github.com/pilue/site-example",
    "PREVIEW": "false",
    "HMAC_SECRET": "test-secret",
    "GITHUB_REF_NAME": "main",
    "GITHUB_SHA": "abc1234",
}


def env(**overrides):
    return {**BASE_ENV, **overrides}


# ---------------------------------------------------------------------------
# resolve_inputs
# ---------------------------------------------------------------------------


class TestResolveInputs(unittest.TestCase):
    def test_explicit_ref_is_used(self):
        inputs = send_publish.resolve_inputs(env(REF="my-branch"), {})
        self.assertEqual(inputs["ref"], "my-branch")

    def test_ref_defaults_to_head_ref_on_pr(self):
        inputs = send_publish.resolve_inputs(env(GITHUB_HEAD_REF="feature/foo"), {})
        self.assertEqual(inputs["ref"], "feature/foo")

    def test_ref_falls_back_to_ref_name_on_push(self):
        inputs = send_publish.resolve_inputs(env(), {})
        self.assertEqual(inputs["ref"], "main")

    def test_source_sha_explicit(self):
        inputs = send_publish.resolve_inputs(env(SOURCE_SHA="deadbeef"), {})
        self.assertEqual(inputs["source_sha"], "deadbeef")

    def test_source_sha_from_pr_event(self):
        event = {"pull_request": {"head": {"sha": "pr-sha-123"}}}
        inputs = send_publish.resolve_inputs(env(), event)
        self.assertEqual(inputs["source_sha"], "pr-sha-123")

    def test_source_sha_falls_back_to_github_sha(self):
        inputs = send_publish.resolve_inputs(env(GITHUB_SHA="push-sha-456"), {})
        self.assertEqual(inputs["source_sha"], "push-sha-456")

    def test_pr_number_explicit(self):
        inputs = send_publish.resolve_inputs(env(PR_NUMBER="42"), {})
        self.assertEqual(inputs["pr_number"], "42")

    def test_pr_number_auto_detected_from_event(self):
        event = {"pull_request": {"number": 99, "head": {"sha": "x"}}}
        inputs = send_publish.resolve_inputs(env(), event)
        self.assertEqual(inputs["pr_number"], "99")

    def test_pr_number_empty_on_push(self):
        inputs = send_publish.resolve_inputs(env(), {})
        self.assertEqual(inputs["pr_number"], "")

    def test_notification_token_defaults_to_source_token(self):
        inputs = send_publish.resolve_inputs(env(SOURCE_TOKEN="tok-abc"), {})
        self.assertEqual(inputs["notification_token"], "tok-abc")

    def test_notification_token_explicit_overrides_source_token(self):
        inputs = send_publish.resolve_inputs(
            env(SOURCE_TOKEN="tok-abc", NOTIFICATION_TOKEN="tok-xyz"), {}
        )
        self.assertEqual(inputs["notification_token"], "tok-xyz")

    def test_notification_token_empty_when_no_tokens(self):
        inputs = send_publish.resolve_inputs(env(), {})
        self.assertEqual(inputs["notification_token"], "")

    def test_preview_true(self):
        inputs = send_publish.resolve_inputs(env(PREVIEW="true"), {})
        self.assertTrue(inputs["preview"])

    def test_teardown_true(self):
        inputs = send_publish.resolve_inputs(env(TEARDOWN="true"), {})
        self.assertTrue(inputs["teardown"])


# ---------------------------------------------------------------------------
# build_payload
# ---------------------------------------------------------------------------


class TestBuildPayload(unittest.TestCase):
    def _inputs(self, **overrides):
        base = {
            "domain": "example.pilue.co.uk",
            "repo": "https://github.com/pilue/site-example",
            "ref": "main",
            "preview": False,
            "teardown": False,
            "pr_number": "",
            "source_sha": "",
            "source_token": "",
            "notification_token": "",
            "hmac_secret": "secret",
        }
        return {**base, **overrides}

    def test_required_fields_always_present(self):
        payload = send_publish.build_payload(self._inputs())
        self.assertEqual(payload["domain"], "example.pilue.co.uk")
        self.assertEqual(payload["repo"], "https://github.com/pilue/site-example")
        self.assertEqual(payload["ref"], "main")
        self.assertFalse(payload["preview"])

    def test_optional_fields_omitted_when_empty(self):
        payload = send_publish.build_payload(self._inputs())
        self.assertNotIn("pr_number", payload)
        self.assertNotIn("source_sha", payload)
        self.assertNotIn("source_token", payload)
        self.assertNotIn("notification_token", payload)
        self.assertNotIn("teardown", payload)

    def test_optional_fields_included_when_set(self):
        payload = send_publish.build_payload(
            self._inputs(
                pr_number="7",
                source_sha="abc",
                source_token="tok",
                notification_token="tok",
            )
        )
        self.assertEqual(payload["pr_number"], "7")
        self.assertEqual(payload["source_sha"], "abc")
        self.assertIn("source_token", payload)
        self.assertIn("notification_token", payload)

    def test_teardown_included_when_true(self):
        payload = send_publish.build_payload(self._inputs(teardown=True))
        self.assertTrue(payload["teardown"])

    def test_preview_true(self):
        payload = send_publish.build_payload(self._inputs(preview=True))
        self.assertTrue(payload["preview"])


# ---------------------------------------------------------------------------
# sign_payload
# ---------------------------------------------------------------------------


class TestSignPayload(unittest.TestCase):
    def test_signature_format(self):
        sig = send_publish.sign_payload(b"hello", "secret")
        self.assertTrue(sig.startswith("sha256="))

    def test_signature_is_correct(self):
        payload = b'{"domain":"example.pilue.co.uk"}'
        secret = "my-secret"
        expected = (
            "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        )
        self.assertEqual(send_publish.sign_payload(payload, secret), expected)

    def test_different_secrets_produce_different_signatures(self):
        payload = b"payload"
        self.assertNotEqual(
            send_publish.sign_payload(payload, "secret-a"),
            send_publish.sign_payload(payload, "secret-b"),
        )


# ---------------------------------------------------------------------------
# send_request
# ---------------------------------------------------------------------------


class TestSendRequest(unittest.TestCase):
    def _mock_response(self, status, body):
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.read.return_value = body.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_successful_202(self):
        with patch(
            "urllib.request.urlopen",
            return_value=self._mock_response(
                202, '{"dispatch_time":"2026-01-01T00:00:00Z"}'
            ),
        ):
            status, body = send_publish.send_request(
                b"{}", "sha256=sig", "secret", url="https://example.com"
            )
        self.assertEqual(status, 202)
        self.assertIn("dispatch_time", body)

    def test_http_error_returned_as_status(self):
        import urllib.error

        err = urllib.error.HTTPError(
            url="", code=403, msg="Forbidden", hdrs={}, fp=None
        )
        err.read = lambda: b"Forbidden"
        with patch("urllib.request.urlopen", side_effect=err):
            status, body = send_publish.send_request(
                b"{}", "sha256=sig", "secret", url="https://example.com"
            )
        self.assertEqual(status, 403)


# ---------------------------------------------------------------------------
# write_github_output
# ---------------------------------------------------------------------------


class TestWriteGithubOutput(unittest.TestCase):
    def test_writes_key_value(self):
        with tempfile.NamedTemporaryFile(mode="r", suffix=".env", delete=False) as f:
            path = f.name
        send_publish.write_github_output(
            "dispatch_time", "2026-01-01T00:00:00Z", {"GITHUB_OUTPUT": path}
        )
        with open(path) as f:
            content = f.read()
        self.assertIn("dispatch_time=2026-01-01T00:00:00Z", content)

    def test_no_write_when_value_empty(self):
        with tempfile.NamedTemporaryFile(mode="r", suffix=".env", delete=False) as f:
            path = f.name
        send_publish.write_github_output("dispatch_time", "", {"GITHUB_OUTPUT": path})
        with open(path) as f:
            self.assertEqual(f.read(), "")

    def test_no_write_when_path_not_set(self):
        # Should not raise even when GITHUB_OUTPUT is absent
        send_publish.write_github_output("dispatch_time", "2026-01-01T00:00:00Z", {})


if __name__ == "__main__":
    unittest.main()
