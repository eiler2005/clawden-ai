# Architecture And Security

## Architecture overview

This deployment intentionally separates public access, application runtime, and unrelated workloads.

```text
Browser
  -> TLS + client certificate
  -> Caddy (80/443)
     -> reverse proxy (HTTP + WebSocket) to 127.0.0.1:18789
        -> OpenClaw gateway container (single UI + API source)
           -> provider auth profiles
           -> workspace and task state
           -> upstream model/provider access

Existing app (deploy-bridge-1)
  -> separate project
  -> unchanged
```

## Main components

### Caddy

Role:

- public TLS termination
- mandatory client certificate validation
- reverse proxy for full OpenClaw traffic (HTTP + WebSocket)

Why it matters:

- keeps the OpenClaw gateway off the public internet
- gives one clean trust boundary at the edge

### OpenClaw gateway

Role:

- application backend
- websocket endpoint
- auth profile usage
- agent/runtime orchestration

Current auth mode:

- token auth at the gateway layer

### Host OS boundary

Role:

- Docker host
- reverse-proxy host
- SSH/admin surface

Intentional non-role:

- not the place for OpenClaw runtime add-ons such as `whisper`, `ffmpeg`, or other agent-facing toolchains

Why it matters:

- avoids "installed on the server but missing in the app runtime" confusion
- keeps operational drift smaller
- makes runtime verification deterministic

### Derived OpenClaw image

Role:

- same upstream runtime, plus deployment-required runtime dependencies

Why it exists:

- the selected network mode required the `ip` binary at runtime
- the upstream image did not provide it
- OpenClaw-adjacent tools such as `ffmpeg` and `whisper` must live where OpenClaw actually executes commands

### Control UI delivery strategy

Current strategy:

- Control UI is delivered by OpenClaw gateway itself
- `Caddy` forwards all browser traffic to the gateway instead of serving a host-side UI copy

Why it matters:

- avoids UI/backend version drift between copied static assets and running OpenClaw build
- keeps runtime behavior deterministic during upgrades and rollbacks

## Security model

## Edge protection

- only `80/443` are publicly exposed for the application
- SSH remains administrative only
- direct OpenClaw ports stay bound to host loopback

## Client authentication

Primary public access control:

- `mTLS`

Effect:

- a browser without the trusted client certificate should not obtain usable access

## Application authentication

Inside the trusted edge:

- OpenClaw still requires its own gateway token for websocket access

This creates layered access control:

1. edge trust via client certificate
2. application trust via OpenClaw token/auth flow

## Secret handling

Sensitive items intentionally kept out of tracked docs:

- server access details
- raw `.env`
- provider auth profiles
- client certificates
- client certificate passwords
- tokenized browser URLs
- reverse proxy private keys

Storage approach:

- local-only files under `secrets/`
- local-only server notes under `LOCAL_ACCESS.md`
- redacted copies only under `artifacts/`

## Trust boundaries

### Public internet to edge

Trusted only after:

- valid TLS
- valid client certificate

### Edge to OpenClaw

Trusted path:

- localhost proxy hop only

### Host OS to container runtime

Operational rule:

- host-level package installs do not count as OpenClaw runtime installs
- if a binary must be visible to OpenClaw, it must exist in the derived image or in a container-mounted path intentionally consumed by the runtime

### OpenClaw to model/provider layer

Trusted by:

- server-resident OpenClaw auth profile

## Operational risks and trade-offs

### Upstream image assumptions

The deployment depends on behavior not fully captured by the upstream image defaults. That is why the derived image exists.

### Startup convergence window

A strict readiness probe (`/healthz`) can report `starting` or `unhealthy` during cold boot and internal gateway restarts before converging to `healthy`.

### Short-lived proxy errors during restart

If the gateway restarts (for example after config changes), the edge proxy can briefly return `502` until the backend is listening again.

## Applied OpenClaw security settings

Reference: [docs.openclaw.ai/gateway/security](https://docs.openclaw.ai/gateway/security)

These settings are applied in `/opt/openclaw/config/openclaw.json` on the server.
The redacted copy lives in `artifacts/openclaw/openclaw.json`.

### Gateway hardening

| Setting | Value | Reason |
|---|---|---|
| `gateway.auth.allowTailscale` | `false` | Tailscale not used; disable identity header acceptance |
| `gateway.auth.rateLimit` | `{}` (defaults) | Enable brute-force protection on auth endpoints |
| `gateway.trustedProxies` | `[<docker-bridge-gateway-ip>]` | Trust Caddy's forwarded headers for client IP; actual IP in `LOCAL_ACCESS.md` |
| `gateway.allowRealIpFallback` | `false` | Prefer `X-Forwarded-For` only; no `X-Real-IP` fallback |

### Tool execution policy

| Setting | Value | Reason |
|---|---|---|
| `tools.profile` | `"messaging"` | Safest preset; restrict to messaging tools only |
| `tools.exec.security` | `"deny"` | No host shell execution from agents |
| `tools.exec.ask` | `"always"` | Approval prompts for any exec attempt |
| `tools.fs.workspaceOnly` | `true` | Filesystem tools limited to mounted workspace |
| `tools.elevated.enabled` | `false` | No privileged execution mode |

Note: if agent workflows require file system or execution tools, switch to `tools.profile: "full"` with an explicit `tools.deny` list. Start strict, widen as needed.

### Operational note: gateway startup time

With these security settings applied, gateway startup time increased to ~2 minutes (vs ~30s before). This is expected — additional config validation and plugin initialisation at boot. The Compose `healthcheck.start_period` (10s) is shorter than the actual startup, so the container briefly reports `unhealthy` before converging to `healthy`. End-user impact: none (Caddy returns 502 only during the ~2 minute window after a `docker compose restart`).

### Logging

| Setting | Value | Reason |
|---|---|---|
| `logging.redactSensitive` | `"tools"` | Redact secrets from tool output (note: `"all"` is not supported in 2026.4.2; allowed values: `"off"`, `"tools"`) |

### Network and discovery

| Setting | Value | Reason |
|---|---|---|
| `discovery.mdns.mode` | `"off"` | No LAN discovery needed on VPS; reduce attack surface |
| `session.dmScope` | `"per-channel-peer"` | Session isolation between peers (safe default even with no DM channels) |

### Browser / SSRF policy

| Setting | Value | Reason |
|---|---|---|
| `browser.ssrfPolicy.dangerouslyAllowPrivateNetwork` | `false` | Block agents from reaching internal/private network destinations |

If agents need to browse specific internal hosts, add them to `browser.ssrfPolicy.allowedHostnames`.

### Caddy: HSTS

| Setting | Before | After | Reason |
|---|---|---|---|
| `Strict-Transport-Security max-age` | `300` | `31536000` | 300s was development-safe; 1 year is the production standard |

### Telegram channel access control

Telegram is configured with layered access control:

| Setting | Value | Reason |
|---|---|---|
| `channels.telegram.dmPolicy` | `"allowlist"` | DMs only from explicitly listed user IDs |
| `channels.telegram.allowFrom` | `[<owner-id>]` | Only owner can DM the bot; actual ID in `LOCAL_ACCESS.md` |
| `channels.telegram.groupAllowFrom` | `[<owner-id>]` | Explicit user allowlist for group triggers |
| `channels.telegram.groups."*".requireMention` | `true` | All groups require @mention by default |
| `channels.telegram.groups.<supergroup-id>.requireMention` | `false` | Target group reads all messages (forum supergroup with topics) |
| `channels.telegram.groups.<supergroup-id>.groupPolicy` | `"open"` | Any member of the target group can trigger the bot |

The target group ID is kept in `LOCAL_ACCESS.md` (not committed).

Bot prerequisites: admin role in group, Privacy Mode disabled via BotFather `/setprivacy`.

### Settings NOT applied

| Setting | Reason |
|---|---|
| `sandbox.*` | Docker-in-Docker not set up on this VPS |
| `plugins.allowlist` | No plugins configured |
| `hooks.*` | No webhooks configured |
| `gateway.auth.trustedProxy.userHeader` | Not using trusted-proxy auth mode |
| `controlUi.allowedOrigins` | Redundant — mTLS already enforces client identity at the edge |

### Dangerous flags confirmed absent

These flags are explicitly not set, confirming no security downgrades:

- `gateway.controlUi.dangerouslyAllowHostHeaderOriginFallback`
- `gateway.controlUi.dangerouslyDisableDeviceAuth`
- `browser.ssrfPolicy.dangerouslyAllowPrivateNetwork` (set to `false`)
- `tools.exec.applyPatch.workspaceOnly` (not set to `false`)

## Recommended long-term hardening

- pin the exact base image digest
- rotate client certificates on a schedule
- move from ad hoc local secrets to a formal secret manager if the project grows
- replace ad hoc tokenized browser URLs with a documented issuance flow
- keep readiness checks aligned with `/healthz` and gateway startup characteristics
- automate derived-image rebuilds so runtime dependency changes are always traceable
- if agents need shell access, re-enable `tools.exec.security: "ask"` with `tools.exec.safeBins` allowlist instead of full deny
