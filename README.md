# pilue/actions

Shared GitHub Actions for `davidcloud` site publishing pipelines.

## publish-site

Sends an HMAC-signed publish request to the platform api, which triggers a deployment in `davidcloud`. The action then polls the platform api status endpoint until the deployment completes (up to 20 minutes) and fails the job if the deployment does not succeed.

### How it works

```
Site repo workflow
  └── publish-site action
        ├── POST https://api.davidcloud.co.uk/publish  (HMAC-signed)
        │     └── platform-api validates signature → triggers site deployment
        └── Poll /status?domain=...&since=...  every 15 s
              └── Resolves once the deployment completes
```

The action requires two secrets to be set on the site repo:

| Secret | Description |
|---|---|
| `PUBLISH_HMAC_SECRET` | Per-domain HMAC secret (provided during onboarding to `davidcloud`) |
| `PUBLISH_TOKEN` | Fine-grained PAT with `contents: read` on the site repo (for cloning) and `pull_requests: write` on the site repo (for PR comments) |

### Usage

#### Production deploy (on push to main)

```yaml
- uses: pilue/actions/publish-site@main
  with:
    domain: example.pilue.co.uk
    repo: https://github.com/pilue/site-example
    preview: "false"
    hmac_secret: ${{ secrets.PUBLISH_HMAC_SECRET }}
```

#### Preview deploy (on pull request)

```yaml
- uses: pilue/actions/publish-site@main
  with:
    domain: example.pilue.co.uk
    repo: https://github.com/pilue/site-example
    preview: "true"
    hmac_secret: ${{ secrets.PUBLISH_HMAC_SECRET }}
    source_token: ${{ secrets.PUBLISH_TOKEN }}
```

#### Teardown preview (on pull request close)

```yaml
- uses: pilue/actions/publish-site@main
  with:
    domain: example.pilue.co.uk
    repo: https://github.com/pilue/site-example
    preview: "true"
    teardown: "true"
    hmac_secret: ${{ secrets.PUBLISH_HMAC_SECRET }}
```

### Inputs

| Input | Required | Description |
|---|---|---|
| `domain` | yes | Registered domain, e.g. `example.pilue.co.uk` |
| `repo` | yes | HTTPS clone URL of the source repo |
| `preview` | yes | `"true"` for preview deploy, `"false"` for production |
| `hmac_secret` | yes | Shared HMAC secret for this domain |
| `ref` | no | Git ref to build (branch/tag/SHA). Defaults to the PR head branch on pull request events, or the branch/tag name on push events. |
| `source_sha` | no | HEAD SHA of the source commit — ensures a unique image tag per push. Auto-detected from the current commit or PR head. |
| `pr_number` | no | PR number — used to post a comment when the preview URL is ready. Auto-detected on pull request events. |
| `source_token` | no | PAT for cloning a private source repo |
| `notification_token` | no | Fine-grained PAT for posting comments back to the source repo. Defaults to `source_token` if not set. |
| `teardown` | no | `"true"` to tear down a preview deployment (skips build) |

### Outputs

| Output | Description |
|---|---|
| `dispatch_time` | ISO-8601 timestamp of when the hetzner-k3s workflow was dispatched — used internally for status polling |
