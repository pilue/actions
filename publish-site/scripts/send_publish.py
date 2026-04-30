#!/usr/bin/env python3
"""
Build and send an HMAC-signed publish request to platform-api.

Reads all inputs from environment variables, applies sensible defaults from
GitHub context, then POSTs the signed payload and writes dispatch_time to
GITHUB_OUTPUT.
"""
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request

PUBLISH_URL = "https://api.davidcloud.co.uk/publish"

# ---------------------------------------------------------------------------
# Load GitHub event payload for auto-detection
# ---------------------------------------------------------------------------

event = {}
event_path = os.environ.get("GITHUB_EVENT_PATH", "")
if event_path:
    try:
        with open(event_path) as f:
            event = json.load(f)
    except Exception:
        pass
pr = event.get("pull_request", {})

# ---------------------------------------------------------------------------
# Resolve inputs, applying defaults from GitHub context where not set
# ---------------------------------------------------------------------------

# ref: PR head branch → current branch/tag name
ref = os.environ.get("REF", "").strip()
if not ref:
    ref = os.environ.get("GITHUB_HEAD_REF", "").strip() or os.environ.get("GITHUB_REF_NAME", "").strip()

# source_sha: PR head SHA → current commit SHA
source_sha = os.environ.get("SOURCE_SHA", "").strip()
if not source_sha:
    source_sha = pr.get("head", {}).get("sha", "") or os.environ.get("GITHUB_SHA", "")

# pr_number: auto-detect on pull_request events
pr_number = os.environ.get("PR_NUMBER", "").strip()
if not pr_number and pr.get("number"):
    pr_number = str(pr["number"])

# notification_token falls back to source_token
source_token = os.environ.get("SOURCE_TOKEN", "").strip()
notification_token = os.environ.get("NOTIFICATION_TOKEN", "").strip()
if not notification_token:
    notification_token = source_token

hmac_secret = os.environ["HMAC_SECRET"]

# ---------------------------------------------------------------------------
# Build payload
# ---------------------------------------------------------------------------

payload: dict = {
    "domain": os.environ["DOMAIN"],
    "repo": os.environ["REPO"],
    "ref": ref,
    "preview": os.environ.get("PREVIEW", "false").lower() == "true",
}

if pr_number:
    payload["pr_number"] = pr_number
if source_token:
    payload["source_token"] = source_token
if notification_token:
    payload["notification_token"] = notification_token
if source_sha:
    payload["source_sha"] = source_sha
if os.environ.get("TEARDOWN", "false").lower() == "true":
    payload["teardown"] = True

payload_bytes = json.dumps(payload).encode()

# ---------------------------------------------------------------------------
# Sign and send
# ---------------------------------------------------------------------------

sig = "sha256=" + hmac.new(hmac_secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

req = urllib.request.Request(
    PUBLISH_URL,
    data=payload_bytes,
    method="POST",
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "GitHub-Actions/pilue-publish-site",
        "X-Publish-Token": hmac_secret,
        "X-Hub-Signature-256": sig,
    },
)

try:
    with urllib.request.urlopen(req) as resp:
        status = resp.status
        body = resp.read().decode()
except urllib.error.HTTPError as e:
    status = e.code
    body = e.read().decode()

print(f"platform-api response (HTTP {status}):")
print(body)

if status != 202:
    if "just a moment" in body.lower():
        print("Cloudflare challenge blocked the request before it reached platform-api.")
        print("Create a Cloudflare WAF skip rule for host api.davidcloud.co.uk and path /publish.")
        print("HMAC validation in platform-api still protects the endpoint.")
    print(f"Publish request failed with HTTP {status}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Write dispatch_time to GITHUB_OUTPUT
# ---------------------------------------------------------------------------

try:
    data = json.loads(body)
    dispatch_time = data.get("dispatch_time", "")
except Exception:
    dispatch_time = ""

github_output = os.environ.get("GITHUB_OUTPUT", "")
if github_output and dispatch_time:
    with open(github_output, "a") as f:
        f.write(f"dispatch_time={dispatch_time}\n")
