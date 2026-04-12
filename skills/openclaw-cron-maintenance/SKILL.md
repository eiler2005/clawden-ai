---
name: openclaw-cron-maintenance
description: Use when maintaining OpenClaw cron-managed bridge jobs such as Telegram Digest or AgentMail Inbox, especially when updating schedules, fixing sync-openclaw-cron-jobs.sh, validating jobs.json, or recovering from a hanging `openclaw cron list` / cron CLI path.
---

# OpenClaw Cron Maintenance

Use this skill for server-side cron maintenance around bridge-style jobs (`telethon-digest`, `agentmail-email`, similar).

## Core rule

On this deployment, do not trust `openclaw cron list/add/remove` as the primary path.
The gateway CLI can hang while the scheduler and cron store still work.

Prefer:

1. inspect the cron store JSON directly
2. patch only the managed jobs for one prefix
3. back up the store before changes
4. restart `openclaw-openclaw-gateway-1`
5. validate via `jobs.json` + container health

## Default cron-store locations

Check in this order:

- `/opt/openclaw/config/cron/jobs.json`
- `/home/deploy/.openclaw/cron/jobs.json`

Allow override with `OPENCLAW_CRON_STORE`.

## Safe workflow

1. Read the managed prefix and intended schedules from the repo sync script.
2. Read the current cron store and extract only jobs matching that prefix.
3. Back up the store to `jobs.json.bak-<unix_ts>`.
4. Replace only the managed jobs for that prefix.
5. Preserve other jobs untouched.
6. Restart `openclaw-openclaw-gateway-1`.
7. Wait until the gateway returns to `healthy`.
8. Validate the store contains the expected names, `schedule.expr`, and `enabled=true`.

## Useful checks

Check gateway/container health:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "openclaw-openclaw-gateway-1|telethon-digest-cron-bridge|agentmail-email-bridge"'
```

Inspect cron store:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'sudo cat /opt/openclaw/config/cron/jobs.json 2>/dev/null || sudo cat /home/deploy/.openclaw/cron/jobs.json'
```

## When editing sync scripts

- Keep them idempotent.
- Patch only one managed prefix per script.
- Preserve existing `id` / `createdAtMs` when the same job name still exists.
- Recompute `nextRunAtMs`.
- Restart the gateway after patching the store.
- Never rewrite unrelated cron jobs.

## Validation target

After a successful change, confirm:

- gateway is `healthy`
- bridge container is `Up`
- managed jobs exist in `jobs.json`
- expected cron expressions are present
- no unrelated jobs were removed
