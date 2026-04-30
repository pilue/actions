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

POLL_INTERVAL = 15
MAX_WAIT = 1200  # 20 minutes

domain = os.environ["DOMAIN"]
dispatch_time = os.environ.get("DISPATCH_TIME", "").strip()
hmac_secret = os.environ["HMAC_SECRET"]

if not dispatch_time:
    print("No dispatch_time in response — skipping wait.")
    sys.exit(0)

params = urllib.parse.urlencode({"domain": domain, "since": dispatch_time})
status_url = f"https://api.davidcloud.co.uk/status?{params}"

print(f"Waiting for deployment of {domain} to complete...")
print(f"Polling: {status_url}")

elapsed = 0
last_run_url = ""

while True:
    data = {}
    try:
        req = urllib.request.Request(
            status_url,
            headers={"X-Publish-Token": hmac_secret},
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        pass

    status = data.get("status", "unknown")
    conclusion = data.get("conclusion", "")
    run_url = data.get("run_url", "")

    if run_url and run_url != last_run_url:
        print(f"Deployment run: {run_url}")
        last_run_url = run_url

    if status == "completed":
        print(f"Deployment {conclusion or 'unknown'}.")
        if conclusion != "success":
            print(f"Deployment did not succeed (conclusion: {conclusion}). See run for details.")
            sys.exit(1)
        print(f"Deployment of {domain} succeeded.")
        sys.exit(0)
    elif status == "in_progress":
        print(f"  [{elapsed}s] Deployment in progress...")
    elif status == "queued":
        print(f"  [{elapsed}s] Deployment queued, waiting to start...")
    else:
        print(f"  [{elapsed}s] Waiting for workflow run to appear... (status: {status})")

    if elapsed >= MAX_WAIT:
        print(f"Timed out after {MAX_WAIT}s waiting for deployment to complete.")
        sys.exit(1)

    time.sleep(POLL_INTERVAL)
    elapsed += POLL_INTERVAL
