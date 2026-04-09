# Claude Code Instructions

## Repository Role

- This repository is a git-safe operations and handoff package for an OpenClaw deployment on a Hetzner server.
- It is not the live OpenClaw application source tree.
- Start with `README.md`, then use `docs/01-server-state.md`, `docs/02-openclaw-installation.md`, `docs/07-architecture-and-security.md`, and `docs/08-git-and-redaction-policy.md` for deeper context.

## Runtime Boundary

- OpenClaw runs in Docker Compose under `/opt/openclaw` on the Hetzner server.
- If a tool is needed by OpenClaw, its agents, or gateway-executed workflows, install it into the derived OpenClaw image or run it with `docker compose exec`.
- Do not install OpenClaw-adjacent runtime tools on the host OS unless the user explicitly asks for a host-level admin dependency.
- When verifying command availability, check the correct runtime context:
  - host OS for infrastructure/admin tools
  - `openclaw-gateway` container for OpenClaw runtime tools

## Security And Secrets

- Never commit or quote live values from `LOCAL_ACCESS.md` or anything under `secrets/`.
- Keep all documentation sanitized and safe for Git publication.
- Use placeholders instead of real hostnames, passwords, tokens, client certificate details, or raw SSH coordinates in tracked docs.

## Git Workflow

- Use explicit staging in this repo.
- Do not use `git add .`, `git add -A`, `git add --all`, or `git commit -a`.
- Review `.gitignore` before adding new local-only files.
- If deployment behavior changes, update the relevant docs in the same task.

## Changelog

- Update `CHANGELOG.md` with every significant change — new features, fixes, config changes, deployments.
- Do this in the same task as the change itself, before or together with the commit.
- Format: add an entry under `[Unreleased]` or a dated section using [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) conventions.

## Files To Keep Aligned

- `README.md`
- `CHANGELOG.md`
- `docs/01-server-state.md`
- `docs/02-openclaw-installation.md`
- `docs/03-operations.md`
- `docs/06-command-log.md`
- `docs/07-architecture-and-security.md`
- `docs/08-git-and-redaction-policy.md`

## Local-Only Complements

- Use `CLAUDE.local.md` for personal notes that should not be committed.
- Use `.claude/settings.local.json` for local Claude Code overrides that should not be committed.

## Commit Permission Rule

- **Never create a git commit or push to remote without explicit user approval in the current session.**
- Before any `git commit` or `git push`, state what will be committed and ask for confirmation.
- This rule overrides any general "commit when done" instructions.
- One-time approval does not carry over to future commits in the same or other sessions.
