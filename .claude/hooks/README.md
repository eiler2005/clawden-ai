# Claude Code Hooks

This directory contains small, project-safe hooks for this repository.

Current hooks:

- `prevent-unsafe-git.sh`
  - blocks broad staging commands such as `git add .`, `git add -A`, and `git commit -a`
- `enforce-container-runtime.sh`
  - blocks host-level package installs for OpenClaw runtime dependencies such as `whisper`, `ffmpeg`, and `openclaw`

Design goals:

- keep hooks short and auditable
- avoid secrets
- use the project directory through `"$CLAUDE_PROJECT_DIR"`
- focus on preventing repeat mistakes that are specific to this repository

Debugging:

- run Claude Code with `claude --debug`
- see the official hooks reference for configuration and troubleshooting
