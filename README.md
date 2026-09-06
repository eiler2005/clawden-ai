# clawden-ai

> [!IMPORTANT]
> This repository is frozen as the OpenClaw predecessor of
> [My AI Office](https://github.com/eiler2005/my-ai-office). New development and
> migration work continue in
> [migration/hermes-native](https://github.com/eiler2005/my-ai-office/tree/migration/hermes-native).
> Do not use this repository to install, deploy, or upgrade OpenClaw.

## Final OpenClaw state

The production Gateway remains on **OpenClaw 2026.6.9**. The 2026.9.1 derived
candidate built and passed offline configuration checks, but its Gateway never
exposed the healthz, startupz, or readyz endpoints before the bounded deadline.
It was not OOM-killed. The candidate was removed and the 2026.6.9 Gateway was
restored from a verified Mac-held state archive.

The complete outcome and retained recovery rules are recorded in
[the compatibility ledger](docs/22-openclaw-version-compatibility-ledger.md)
and [the archive and migration record](docs/26-archive-and-migration.md).

## Functional handoff

The replacement implementation lives in
[My AI Office](https://github.com/eiler2005/my-ai-office), in its
[migration/hermes-native](https://github.com/eiler2005/my-ai-office/tree/migration/hermes-native)
branch:

| Legacy capability | New home |
| --- | --- |
| Gateway runtime, agent workspace, Telegram operating surface | Hermes deployment, benka plugin, and src/benka_integrations |
| Signals and Last30Days workflows | artifacts/signals-bridge and Hermes integration pipelines |
| Telegram digest workflow | artifacts/telethon-digest and native schedule adapters |
| Personal and work email workflows | artifacts/agentmail-email and Hermes delivery adapters |
| Knowledge capture, wiki, retrieval, and migration tooling | artifacts/llm-wiki, src/benka_integrations/wiki.py, and migration tooling |
| Model routing, delivery, schedules, and operational checks | Hermes integration modules, deployment manifests, and regression tests |

This is a code and operational handoff. It does not declare a production
cutover: credentials, conversations, sessions, and live server state stay out
of both public Git history and this repository.

## What remains here

This frozen repository retains the sanitized historical documentation, the
OpenClaw failure record, and release history. Installation files, deployment
scripts, runtime templates, tests, and skills have been removed to prevent a
new deployment from being created from this repository.

The planned final release tag is **v1.0.0-openclaw-final**. The GitHub repository
is intentionally left unarchived for now so existing links, issues, and the
historical record remain usable.

## License

[MIT](LICENSE)
