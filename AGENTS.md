# Agent Instructions

Read [CLAUDE.md](./CLAUDE.md) first. It is the source of truth for project role, runtime boundaries, security rules, deployment constraints, changelog expectations, and git workflow.

@CLAUDE.md

## lean-ctx

Prefer lean-ctx MCP tools over native equivalents for token savings when they are available.

If a local `LEAN-CTX.md` is added later, follow it as the detailed lean-ctx rule source.

## Project Notes

- This repository is a git-safe operations and handoff package for an OpenClaw deployment, not the live OpenClaw application source tree.
- Keep tracked files sanitized. Never copy or quote live values from `LOCAL_ACCESS.md`, `secrets/`, raw `.env` files, certificates, tokens, or tokenized URLs.
- Deployment to the server is a separate operation. Prepare local files freely, but only deploy after an explicit user request.
- Significant operational changes should update `CHANGELOG.md` and the relevant docs in the same task.
- Use explicit git staging only; do not use `git add .`, `git add -A`, `git add --all`, or `git commit -a`.
