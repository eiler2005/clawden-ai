# Codex Skills Catalog

This document tracks the project-specific Codex skills used with this repo.
It is intentionally separate from OpenClaw runtime docs: these skills help the
operator agent work on the system, not the production assistant answer end users.

---

## Purpose

We keep custom skills for workflows that are:

- repeated often enough to deserve a stable playbook
- specific to this deployment
- easy to get subtly wrong without local context
- good candidates for future expansion

The repo is the canonical source of truth. Installed local copies in
`~/.codex/skills/` should mirror the versions here.

---

## Current Skills

### `openclaw-cron-maintenance`

Canonical file: `skills/openclaw-cron-maintenance/SKILL.md`

Use when:

- updating OpenClaw-managed schedules for `telethon-digest`, `agentmail-email`, or similar bridges
- fixing `sync-openclaw-cron-jobs.sh`
- validating Gateway RPC inventory after deploy
- recovering from a hanging `openclaw cron list` / cron CLI path

Core rule:

- use bounded Gateway RPC through `artifacts/openclaw/openclaw-cron-rpc.sh`; do
  not edit cron store files or SQLite directly

Default safe workflow:

1. Read the managed prefix and expected schedules from the repo sync script.
2. Enumerate every `cron.list` page with `includeDisabled=true` and a stable snapshot.
3. Patch only the managed prefix through `cron.add`, `cron.update`, or `cron.remove`.
4. Preserve ids, unknown fields, unrelated jobs, and Gateway-computed runtime state.
5. Validate expected names, cron expressions, timezones, and enabled state through a second RPC inventory.

Why it exists:

- ordinary cron CLI paths can hang, while bounded Gateway RPC gives a defined failure mode
- the 2026.9.1 candidate uses SQLite-backed cron state, so direct file edits are unsafe; production
  remains on the 2026.6.9 hotfix until its release gates pass

---

## Catalog Rules

Every new project skill should follow these rules:

1. One skill = one narrow operational problem space.
2. The repo copy is canonical and reviewable in git.
3. The skill must reference the real scripts/docs, not replace them.
4. The skill must encode the safest known path, especially around deploys, secrets, and rollback.
5. If a workflow has a server-specific gotcha, write it down explicitly.

---

## Suggested Next Skills

Good candidates for the next wave:

- `telethon-digest-ops` — deploy, auth, sync, smoke-test, and rollback flow for Telegram Digest
- `agentmail-email-ops` — poll/digest validation, lookback recovery, Redis queue checks, label safety
- `lightrag-maintenance` — ingest, reprocess, healthcheck, and query validation workflow
- `openclaw-runtime-deploy` — safe deploy/update procedure for the shared OpenClaw gateway stack
- `omniroute-maintenance` — provider health, tier validation, and upgrade checks

This keeps the catalog small but composable: one sharp skill per operational area.

---

## Install / Sync Pattern

Recommended workflow for local Codex usage:

1. Edit the repo copy in `skills/...`.
2. Review and commit it like normal code/docs.
3. Sync the final version into `~/.codex/skills/` for active local use.

Example:

```bash
mkdir -p ~/.codex/skills/openclaw-cron-maintenance
cp skills/openclaw-cron-maintenance/SKILL.md ~/.codex/skills/openclaw-cron-maintenance/SKILL.md
```

If we later automate this, we can add a tiny `scripts/install-codex-skill.sh` helper.
