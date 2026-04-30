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


def load_github_event(env=None):
    """Load and return the GitHub event JSON, or an empty dict on failure."""
    if env is None:
        env = os.environ
    event_path = env.get("GITHUB_EVENT_PATH", "")
    if event_path:
        try:
            with open(event_path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def resolve_inputs(env, event):
    """
    Resolve all action inputs, applying GitHub context defaults where needed.
    Returns a flat dict of resolved string values.
    """
    pr = event.get("pull_request", {})

    # ref: explicit → PR head branch → current branch/tag
    ref = env.get("REF", "").strip()
    if not ref:
        ref = (
            env.get("GITHUB_HEAD_REF", "").strip()
            or env.get("GITHUB_REF_NAME", "").strip()
        )

    # source_sha: explicit → PR head SHA → current commit SHA
    source_sha = env.get("SOURCE_SHA", "").strip()
    if not source_sha:
        source_sha = pr.get("head", {}).get("sha", "") or env.get("GITHUB_SHA", "")

    # pr_number: explicit → pull_request event number
    pr_number = env.get("PR_NUMBER", "").strip()
    if not pr_number and pr.get("number"):
        pr_number = str(pr["number"])

    # notification_token falls back to source_token
    source_token = env.get("SOURCE_TOKEN", "").strip()
    notification_token = env.get("NOTIFICATION_TOKEN", "").strip()
    if not notification_token:
        notification_token = source_token

    return {
        "domain": env.get("DOMAIN", ""),
        "repo": env.get("REPO", ""),
        "ref": ref,
        "preview": env.get("PREVIEW", "false").lower() == "true",
        "teardown": env.get("TEARDOWN", "false").lower() == "true",
        "pr_number": pr_number,
        "source_sha": source_sha,
        "source_token": source_token,
        "notification_token": notification_token,
        "hmac_secret": env.get("HMAC_SECRET", ""),
    }


def build_payload(inputs):
    """Build the publish request payload dict from resolved inputs."""
    payload = {
        "domain": inputs["domain"],
        "repo": inputs["repo"],
        "ref": inputs["ref"],
        "preview": inputs["preview"],
    }
    if inputs["pr_number"]:
        payload["pr_number"] = inputs["pr_number"]
    if inputs["source_token"]:
        payload["source_token"] = inputs["source_token"]
    if inputs["notification_token"]:
        payload["notification_token"] = inputs["notification_token"]
    if inputs["source_sha"]:
        payload["source_sha"] = inputs["source_sha"]
    if inputs["teardown"]:
        payload["teardown"] = True
    return payload


def sign_payload(payload_bytes, secret):
    """Return the HMAC-SHA256 signature header value for the given payload."""
    digest = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def send_request(payload_bytes, sig, hmac_secret, url=PUBLISH_URL):
    """POST the signed payload. Returns (http_status: int, body: str)."""
    req = urllib.request.Request(
        url,
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
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def write_github_output(key, value, env=None):
    """Append key=value to the GITHUB_OUTPUT file if it is set."""
    if env is None:
        env = os.environ
    path = env.get("GITHUB_OUTPUT", "")
    if path and value:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def main(env=None):
    if env is None:
        env = os.environ

    event = load_github_event(env)
    inputs = resolve_inputs(env, event)

    payload = build_payload(inputs)
    payload_bytes = json.dumps(payload).encode()
    sig = sign_payload(payload_bytes, inputs["hmac_secret"])

    status, body = send_request(payload_bytes, sig, inputs["hmac_secret"])

    print(f"platform-api response (HTTP {status}):")
    print(body)

    if status != 202:
        if "just a moment" in body.lower():
            print(
                "Cloudflare challenge blocked the request before it reached platform-api."
            )
            print(
                "Create a Cloudflare WAF skip rule for host api.davidcloud.co.uk and path /publish."
            )
            print("HMAC validation in platform-api still protects the endpoint.")
        print(f"Publish request failed with HTTP {status}")
        sys.exit(1)

    try:
        dispatch_time = json.loads(body).get("dispatch_time", "")
    except Exception:
        dispatch_time = ""

    write_github_output("dispatch_time", dispatch_time, env)


if __name__ == "__main__":
    main()
