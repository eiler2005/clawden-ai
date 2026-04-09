# Operations

## SSH convention

Use a placeholder in committed docs and keep the real value only in `LOCAL_ACCESS.md`.

```bash
export OPENCLAW_HOST="deploy@<server-host>"
```

## Container-only operational rule

For this deployment, OpenClaw runtime changes happen in Docker, not on the host OS.

Use the host OS for:

- Docker and Compose management
- `Caddy`
- SSH and general system administration

Use the container runtime for:

- OpenClaw CLI checks
- runtime dependency verification
- tool execution that agents depend on, such as `whisper`

If a new OpenClaw feature requires a binary or Python package, update `/opt/openclaw/Dockerfile.iproute2`, rebuild the image, and recreate `openclaw-gateway` instead of installing the package directly on Ubuntu.

## Move to the OpenClaw project

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && pwd'
```

## Core runtime checks

Show Compose state:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose ps
'
```

Show Docker state:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"
'
```

Gateway logs:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose logs --tail=200 openclaw-gateway
'
```

Follow gateway logs:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose logs -f openclaw-gateway
'
```

## Container transcription (Whisper)

Whisper is installed inside the OpenClaw gateway container image, so verify it in that same runtime context:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway sh -lc "
    which whisper &&
    which ffmpeg &&
    which ffprobe
  "
'
```

Example transcription (use the mounted workspace so the host can provide files):

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway whisper \
    /home/node/.openclaw/workspace/tmp/audio.mp3 \
    --model small \
    --output_dir /home/node/.openclaw/workspace/tmp/whisper-out \
    --task transcribe
'
```

## Restart paths

Restart OpenClaw only:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose restart openclaw-gateway
'
```

Recreate OpenClaw:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose up -d --force-recreate openclaw-gateway
'
```

Reload `Caddy`:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  sudo caddy validate --config /etc/caddy/Caddyfile &&
  sudo systemctl reload caddy
'
```

## Connecting to the OpenClaw web UI

### Local-only access materials

These files live under `secrets/` (gitignored) and must never be committed:

| File | Purpose |
|------|---------|
| `secrets/openclaw-denis-client.p12` | Client certificate (mTLS) |
| `secrets/openclaw-denis-client-password.txt` | Password for the `.p12` file |
| `secrets/openclaw-tokenized-url.txt` | Full browser URL with session token |

### Step 1 — Import the client certificate

The server requires a client certificate (mTLS). Install it once per device.

**macOS (system keychain — works for Chrome and Safari):**

```bash
# Double-click the .p12 file in Finder, or:
security import secrets/openclaw-denis-client.p12 \
  -k ~/Library/Keychains/login.keychain-db \
  -P "$(cat secrets/openclaw-denis-client-password.txt)"
```

Then in **Keychain Access**: find the imported certificate → right-click → Get Info → Trust → set "When using this certificate" to **Always Trust**.

**Firefox (uses its own certificate store):**

1. Open Firefox → Settings → Privacy & Security → View Certificates → Your Certificates
2. Click Import, select `secrets/openclaw-denis-client.p12`, enter the password

**iOS / iPadOS:**

1. AirDrop or email the `.p12` to the device
2. Open Settings → Profile Downloaded → Install
3. Enter the certificate password when prompted

### Step 2 — Open the tokenized URL

```bash
# View the full URL (contains the session token — keep private)
cat secrets/openclaw-tokenized-url.txt
```

Open that URL in your browser. On first load:

- the browser prompts to select a client certificate — select the one imported in Step 1
- if the certificate is accepted, the OpenClaw Control UI loads
- if no certificate is offered or the wrong one is selected, the server returns no response or a TLS error

### Step 3 — Start a session

The Control UI opens in a ready state. To begin a conversation:

- type a message and press Enter
- the bot loads workspace files at the start of each new session

**Starting a fresh session** (reloads all workspace files):

```
/new
```

Use `/new` after deploying updated workspace files, or when switching context to avoid token waste from a long previous session.

### Troubleshooting connection issues

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Browser shows no response / connection reset | No client certificate presented | Import `.p12` and retry |
| Browser prompts for certificate but access fails | Wrong certificate selected | Open browser certificate manager, check which cert is installed |
| `502 Bad Gateway` | Gateway restarting | Wait ~90s after a restart, then reload |
| Page loads but bot doesn't respond | Token in URL may be stale | Check `secrets/openclaw-tokenized-url.txt` — may need re-issuance |
| SSH times out before banner | Hetzner Firewall may have narrowed | Open Hetzner Console, verify `22/tcp` is allowed from your IP |

### Public access verification (curl)

With client certificate:

```bash
curl -skI \
  --cert-type P12 \
  --cert secrets/openclaw-denis-client.p12:"$(cat secrets/openclaw-denis-client-password.txt)" \
  https://<public-host>/
# Expected: HTTP/1.1 200 OK
```

Without client certificate (should be blocked):

```bash
curl -skI https://<public-host>/ || true
# Expected: connection reset or no response
```

## Workspace management

Workspace files define the bot's identity, behaviour, and long-term memory.

### View current workspace files on server

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway \
   sh -lc "ls -la /home/node/.openclaw/workspace/"'
```

### Read a specific workspace file

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway \
   sh -lc "cat /home/node/.openclaw/workspace/MEMORY.md"'
```

### Deploy updated workspace templates from git

```bash
export OPENCLAW_HOST="deploy@<server-host>"
./scripts/deploy-workspace.sh
```

Then start a new session in the bot (`/new`) to reload the files.

### Read today's daily memory log

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway \
   sh -lc "cat /home/node/.openclaw/workspace/memory/$(date +%Y-%m-%d).md 2>/dev/null || echo no-log-yet"'
```

### Edit a workspace file directly on server

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'sudo nano /opt/openclaw/workspace/MEMORY.md'
```

Note: changes take effect on the next bot session start (`/new`). If you edit directly, sync changes back to `workspace/` in git to keep templates current.

## Files worth backing up

### OpenClaw

- `/opt/openclaw/.env`
- `/opt/openclaw/docker-compose.yml`
- `/opt/openclaw/config/openclaw.json`
- `/opt/openclaw/config/agents/main/agent/auth-profiles.json`
- `/opt/openclaw/Dockerfile.iproute2`

### Reverse proxy and certificates

- `/etc/caddy/Caddyfile`
- `/etc/caddy/certs/`

### Existing application

- `/opt/maxtg-bridge/`

## Security verification

### Confirm active tools profile

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway sh -lc "
    grep -A2 profile /home/node/.openclaw/openclaw.json 2>/dev/null || echo no-override
  "
'
```

### Verify mDNS is off

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway sh -lc "
    ss -ulnp | grep -E \"5353|mdns\" || echo mdns-absent
  "
'
```

### Verify exec security mode

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway sh -lc "
    grep -A2 exec /home/node/.openclaw/openclaw.json 2>/dev/null || echo using-config-file
  "
'
```

### Check HSTS header value

```bash
curl -skI --cert-type P12 \
  --cert /path/to/client.p12:<password> \
  https://<public-host>/ | grep -i strict-transport
# Expected: max-age=31536000
```

### Verify no private network SSRF

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway sh -lc "
    grep -A3 ssrfPolicy /home/node/.openclaw/openclaw.json 2>/dev/null || echo check-config
  "
'
```

## Run openclaw doctor

After any upgrade or config change, run doctor inside the container to catch issues early:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway openclaw doctor
'
```

No errors = config is valid. Warnings about startup optimization and `bind=lan` are expected in this deployment.

## Known operational nuances

### Startup time

Gateway takes ~90 seconds to converge from `starting` → `healthy` after a `force-recreate`. This is normal — the Compose healthcheck start period (10s) is shorter than the actual boot time, so `unhealthy` is briefly reported before the probe succeeds. Real user impact: Caddy returns `502` only during this ~90s window.

Do not confuse `unhealthy` with a broken deployment — always check `/healthz` directly:

```bash
curl -sf http://127.0.0.1:18789/healthz  # inside server
```

If this returns `{"ok":true,"status":"live"}` but Compose shows `unhealthy`, the service is fine and will flip to `healthy` on the next probe cycle.

### Startup environment variables

These are set in `/opt/openclaw/.env` to reduce startup overhead on this VPS:

```
NODE_COMPILE_CACHE=/var/tmp/openclaw-compile-cache
OPENCLAW_NO_RESPAWN=1
```

The cache directory must exist on the host (mounted into the container):

```bash
sudo mkdir -p /var/tmp/openclaw-compile-cache
```

### bind=lan warning from doctor

`openclaw doctor` warns that `bind=lan` (0.0.0.0) is network-accessible. This is intentional: Caddy handles all public exposure via mTLS. The gateway port is only published to `127.0.0.1:18789` on the host — not externally reachable. The warning can be ignored in this architecture.

## Memory management

### Memory system overview

The bot uses a three-layer memory system. See `docs/10-memory-architecture.md` for full details.

```
LIVE > RAW > DERIVED
```

Quick rule: current-state questions → always live-check. Never answer from memory files.

### Check LightRAG health

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf http://127.0.0.1:8020/health | jq .
'
```

### View LightRAG logs

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/lightrag && docker compose -f docker-compose.yml -f docker-compose.override.yml logs --tail=100 lightrag
'
```

### Trigger LightRAG re-index (after bulk workspace or Obsidian changes)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  /opt/lightrag/scripts/lightrag-ingest.sh
'
```

### Query LightRAG directly (for debugging)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf -X POST http://127.0.0.1:8020/query \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"test query\", \"mode\": \"hybrid\"}" | jq .
'
```

### Read today's memory index

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway \
   sh -lc "cat /home/node/.openclaw/workspace/memory/INDEX.md 2>/dev/null || echo no-index-yet"'
```

### Read workspace master index

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway \
   sh -lc "cat /home/node/.openclaw/workspace/INDEX.md"'
```

### Weekly memory maintenance (manual)

Run when HEARTBEAT prompts or weekly:

1. Move daily notes older than 14 days to `memory/archive/`
2. Update `memory/INDEX.md` — remove stale entries
3. Trigger LightRAG re-index
4. Scan for contradictions between `MEMORY.md` and recent raw/ entries

```bash
# Example: archive old daily note
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw/workspace &&
  mv memory/2026-04-08.md memory/archive/ 2>/dev/null || echo "file not found"
'
```

After archiving, deploy updated `memory/INDEX.md` and trigger `/new` in the bot.

### Obsidian vault sync check

The vault is synced one-way from Mac via rsync (launchd, every 15 min). Check last sync time:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  ls -la /opt/obsidian-vault/ | head -20
'
```

Check sync log on Mac:

```bash
tail -50 /tmp/obsidian-sync.log
```

Force sync manually from Mac:

```bash
OPENCLAW_HOST="deploy@<server-host>" TRIGGER_REINDEX=true ./scripts/sync-obsidian.sh
```

## If SSH times out during banner exchange

This indicates a host-level access problem before shell login. Use Hetzner Console for recovery checks:

1. verify server power state and load
2. verify Hetzner Firewall still allows `22/tcp` from your current client IP
3. verify `sshd` is active (`systemctl status ssh`)
4. if the host is overloaded, restart only `openclaw-gateway` first, then re-test SSH
