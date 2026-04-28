# pilue/actions

Shared GitHub Actions for pilue org site publishing pipelines.

## publish-site

Sends an HMAC-signed publish request to the platform-api, triggering a build and deploy into [davidcloud](https://davidcloud.co.uk)

```yaml
- uses: pilue/actions/publish-site@main
  with:
    domain: example.pilue.co.uk
    repo: https://github.com/pilue/site-example
    ref: ${{ github.event.pull_request.head.ref }}
    preview: true
    pr_number: ${{ github.event.pull_request.number }}
    source_sha: ${{ github.event.pull_request.head.sha }}
    hmac_secret: ${{ secrets.PUBLISH_HMAC_SECRET }}
    source_token: ${{ secrets.PUBLISH_TOKEN }}
    notification_token: ${{ secrets.PUBLISH_TOKEN }}
```

### Inputs

| Input | Required | Description |
|---|---|---|
| `domain` | yes | Registered domain, e.g. example.pilue.co.uk` |
| `repo` | yes | HTTPS clone URL of the source repo |
| `ref` | yes | Git ref to build (branch/tag/SHA) |
| `preview` | yes | `true` for preview deploy, `false` for production |
| `pr_number` | no | PR number for comment notifications |
| `source_sha` | no | HEAD SHA of the source commit (used in image tag) |
| `hmac_secret` | yes | Shared HMAC secret for this domain |
| `source_token` | no | Token for cloning private source repo |
| `notification_token` | no | Token for posting PR/release comments |
| `teardown` | no | `true` to tear down a preview deployment |
