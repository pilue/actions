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
    Returns the parsed JSON dict, or an empty dict on any error.
    """
    req = urllib.request.Request(
        status_url,
        headers={"X-Publish-Token": hmac_secret},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return {}


def build_status_url(domain, dispatch_time):
    params = urllib.parse.urlencode({"domain": domain, "since": dispatch_time})
    return f"https://api.davidcloud.co.uk/status?{params}"


def run_poll_loop(
    domain, dispatch_time, hmac_secret, poll_interval=15, max_wait=1200, _sleep=None
):
    """
    Poll until the deployment completes, times out, or fails.
    Returns (success: bool, message: str).
    _sleep is injectable for testing.
    """
    if _sleep is None:
        _sleep = time.sleep

    status_url = build_status_url(domain, dispatch_time)
    print(f"Waiting for deployment of {domain} to complete...")
    print(f"Polling: {status_url}")

    elapsed = 0
    last_run_url = ""

    while True:
        data = fetch_status(status_url, hmac_secret)
        status = data.get("status", "unknown")
        conclusion = data.get("conclusion", "")
        run_url = data.get("run_url", "")

        if run_url and run_url != last_run_url:
            print(f"Deployment run: {run_url}")
            last_run_url = run_url

        if status == "completed":
            print(f"Deployment {conclusion or 'unknown'}.")
            if conclusion != "success":
                return (
                    False,
                    f"Deployment did not succeed (conclusion: {conclusion}). See run for details.",
                )
            return True, f"Deployment of {domain} succeeded."
        elif status == "in_progress":
            print(f"  [{elapsed}s] Deployment in progress...")
        elif status == "queued":
            print(f"  [{elapsed}s] Deployment queued, waiting to start...")
        else:
            print(
                f"  [{elapsed}s] Waiting for workflow run to appear... (status: {status})"
            )

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

    if not dispatch_time:
        print("No dispatch_time in response — skipping wait.")
        sys.exit(0)

    success, message = run_poll_loop(domain, dispatch_time, hmac_secret)
    print(message)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
