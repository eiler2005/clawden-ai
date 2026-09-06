# Freeze record and functional handoff

Date: 2026-09-06

## Repository status

This repository is frozen as the historical OpenClaw edition of Benka. It is
kept accessible under its existing name to preserve links, Git history, issues,
and release references. It is not a supported installation or deployment
source.

The planned final tag is **v1.0.0-openclaw-final**. GitHub Archive is
intentionally not enabled at this stage. The old OpenClaw Gateway remains
available on the VPS as a recovery reference, on version 2026.6.9.

## OpenClaw 2026.9.1 failure

The pinned 2026.9.1 derived image built successfully and passed image identity,
iproute2, patched-runtime, and disposable configuration validation checks. A
candidate Gateway then remained running without opening healthz, startupz, or
readyz before the bounded readiness deadline. Docker did not report an OOM
kill.

The candidate was not accepted. No manual Telegram test, model routing test,
cron acceptance, or bridge acceptance ran against it. The verified state archive
on the Mac was used to restore the known-good 2026.6.9 Gateway, its
authorisation, and the prior callers. Candidate containers, images, build cache,
and temporary server runs were removed afterwards.

The remaining blocker is an unresolved Gateway-startup/readiness failure in
2026.9.1. No more upgrade attempts will be made from this frozen repository.
The compatibility ledger is the detailed technical record:
[OpenClaw version compatibility ledger](22-openclaw-version-compatibility-ledger.md).

## Functional destination

Active development and the replacement implementation live in
[My AI Office](https://github.com/eiler2005/my-ai-office), specifically the
[migration/hermes-native](https://github.com/eiler2005/my-ai-office/tree/migration/hermes-native)
branch. That repository moves the following functional scope:

| Former OpenClaw scope | My AI Office destination |
| --- | --- |
| Agent runtime and workspace | Hermes deployment, benka plugin, and integration package |
| Telegram operating surface | Hermes adapters, delivery layer, and workspace rules |
| Signals and Last30Days | Signals bridge and integration pipelines |
| Telegram digest | Telethon digest bridge and schedule adapters |
| Personal and work email | AgentMail bridge and delivery adapters |
| Knowledge capture and retrieval | LLM wiki, retrieval modules, and migration tooling |
| Model routing, schedules, observability | Hermes integration modules, manifests, and tests |

This handoff transfers source code, documented behaviour, sanitized
configuration patterns, and acceptance criteria. It does not transfer live
secrets, OAuth profiles, conversations, Telegram sessions, or VPS state through
Git.

## Removed from this repository

The OpenClaw installation artifacts, deployment scripts, runtime templates,
maintenance skills, tests, and workspace templates are removed with this freeze.
Their maintained successors belong to My AI Office. Historical sanitized
documentation remains here only as an audit record.
