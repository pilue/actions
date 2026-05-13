#!/usr/bin/env python3
"""
Poll the platform-api status endpoint until the deployment completes.

Expects DOMAIN, DISPATCH_TIME, and HMAC_SECRET in environment.
Exits 0 on success, 1 on failure or timeout.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def fetch_status(status_url, hmac_secret):
    """
    Fetch the deployment status from platform-api.

    Returns (data: dict, error: str | None).
    - On success: (parsed JSON dict, None)
    - On HTTP error: ({}, "<status code> <body snippet>")
    - On network error: ({}, "<exception message>")
    """
    req = urllib.request.Request(
        status_url,
        headers={
            "X-Publish-Token": hmac_secret,
            "User-Agent": "davidcloud-deploy/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode(errors="replace")[:200]
        except Exception:
            body = ""
        return {}, f"HTTP {exc.code}: {body}"
    except Exception as exc:
        return {}, str(exc)


def build_status_url(domain, dispatch_time, log_lines=50):
    params = urllib.parse.urlencode(
        {"domain": domain, "since": dispatch_time, "log_lines": log_lines}
    )
    return f"https://api.davidcloud.co.uk/status?{params}"


def _http_error_message(fetch_error):
    """Return a human-readable message for an HTTP error from fetch_status."""
    # fetch_error is "HTTP <code>: <body snippet>"
    code = fetch_error.split()[1].rstrip(":")
    if code in ("401", "403"):
        return (
            f"Status check failed ({code} Forbidden).\n"
            "Access was denied by the server. Check that the source_token has the "
            "correct scopes and that all required secrets are configured."
        )
    if code == "404":
        return (
            "Status check failed (404 Not Found).\n"
            "The domain may not be registered with platform-api yet."
        )
    if code.startswith("5"):
        return (
            f"Status check failed ({code} Server Error).\n"
            "This may indicate a misconfiguration on the server side "
            "(e.g. hmac_secret does not match the server's expected value)."
        )
    return f"Status check failed: {fetch_error}"


def run_poll_loop(
    domain,
    dispatch_time,
    hmac_secret,
    log_tail_lines=50,
    poll_interval=15,
    max_wait=1200,
    _sleep=None,
):
    """
    Poll until the deployment completes, times out, or fails.
    Returns (success: bool, message: str).
    _sleep is injectable for testing.
    """
    if _sleep is None:
        _sleep = time.sleep

    status_url = build_status_url(domain, dispatch_time, log_tail_lines)
    print(f"Waiting for deployment of {domain} to complete...")
    print(f"Polling: {status_url}")

    elapsed = 0
    last_run_url = ""
    consecutive_errors = 0

    while True:
        data, fetch_error = fetch_status(status_url, hmac_secret)
        status = data.get("status", "unknown")
        conclusion = data.get("conclusion", "")
        run_url = data.get("run_url", "")

        if fetch_error:
            consecutive_errors += 1
            # Fail immediately on auth/config errors — retrying won't help.
            if fetch_error.startswith("HTTP 4") or fetch_error.startswith("HTTP 5"):
                friendly = _http_error_message(fetch_error)
                return False, friendly
            # For transient network errors allow a few retries.
            if consecutive_errors >= 3:
                return (
                    False,
                    f"Status check failed after {consecutive_errors} consecutive errors: {fetch_error}",
                )
            print(f"  [{elapsed}s] Status check error (will retry): {fetch_error}")
        else:
            consecutive_errors = 0

        if run_url and run_url != last_run_url:
            last_run_url = run_url

        if status == "completed":
            print(f"Deployment {conclusion or 'unknown'}.")
            if conclusion != "success":
                print(f"Response data: {data!r}")
                logs = data.get("logs")
                if logs:
                    if isinstance(logs, list):
                        print("\n".join(logs))
                    else:
                        print(
                            f"Unexpected logs format ({type(logs).__name__}): {logs!r}"
                        )
                else:
                    print(f"No logs in response. Keys: {list(data.keys())}")
                return (
                    False,
                    f"Deployment did not succeed (conclusion: {conclusion}).",
                )
            return True, f"Deployment of {domain} succeeded."
        elif status == "in_progress":
            print(f"  [{elapsed}s] Deployment in progress...")
        elif status == "queued":
            print(f"  [{elapsed}s] Deployment queued, waiting to start...")
        elif not fetch_error:
            print(f"  [{elapsed}s] Waiting for deployment to start...")

        if elapsed >= max_wait:
            return (
                False,
                f"Timed out after {max_wait}s waiting for deployment to complete.",
            )

        _sleep(poll_interval)
        elapsed += poll_interval


def main(env=None):
    if env is None:
        env = os.environ

    domain = env["DOMAIN"]
    dispatch_time = env.get("DISPATCH_TIME", "").strip()
    hmac_secret = env["HMAC_SECRET"]
    log_tail_lines = int(env.get("LOG_TAIL_LINES", "50"))

    if not dispatch_time:
        print("No dispatch_time in response — skipping wait.")
        sys.exit(0)

    success, message = run_poll_loop(domain, dispatch_time, hmac_secret, log_tail_lines)
    print(message)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
