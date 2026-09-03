# Cloudflare trigger

GitHub Actions' `schedule:` is best-effort. Measured on this repo over 5 days it
delivered **35 of ~290** requested runs — a median gap of 200 minutes and a worst
case of 412. `workflow_dispatch` is not throttled, so the clock lives here and
GitHub only executes.

## Deploy

```bash
npx wrangler deploy
```

## The one secret it needs

A fine-grained GitHub PAT scoped to `Simplyair/pm-internship-watcher` with
**Actions: Read and write**, nothing else:

```bash
npx wrangler secret put GITHUB_TOKEN
```

## Verify

```bash
npx wrangler tail          # live logs; look for "dispatched (cron: ...)"
gh run list --limit 5      # dispatch-triggered runs appear as `workflow_dispatch`
```

## Schedule

| Cron | Meaning |
|---|---|
| `*/10 11-23 * * 1-5` | every 10 min, Mon–Fri 7am–8pm ET |
| `0 0-10 * * *` | hourly overnight, daily |
| `0 11-23 * * SAT` / `SUN` | hourly weekend daytime |

~2,159 dispatches/month, plus the workflow's own 8-hourly safety net, is about
**75%** of the 3,000 GitHub Actions minutes included with GitHub Pro.

Cloudflare's free plan allows 5 cron triggers per account; this uses 4.
