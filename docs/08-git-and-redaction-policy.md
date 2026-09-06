# Git and redaction policy

> **Historical policy.** This repository is frozen and must not be used to
> deploy OpenClaw. Active work is in
> [My AI Office](https://github.com/eiler2005/my-ai-office).

The repository preserves a sanitized record of the former OpenClaw deployment.
It must never contain live credentials, OAuth profiles, private keys, Telegram
sessions, production conversations, server access notes, raw environment files,
or state archives.

The final freeze review checked the current tree and all reachable Git history
for common API-token, private-key, Telegram-token, Telegram-chat, email, and
local-path patterns. No API token, private key, or Telegram bot token appeared.
Historic Telegram-chat and local-path matches are retained only in earlier
commits; the frozen tree contains neither. Current email references are
documentary or redacted examples, not credentials.

The verified recovery archive is kept outside this Git checkout in protected
Mac storage. It is not an artifact of this repository and must never be added
to Git.
