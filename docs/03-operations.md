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

### Obsidian vault sync — Syncthing setup (bidirectional)

The vault syncs **bidirectionally** between Mac (iCloud) and server via Syncthing.
Changes on either side propagate automatically within seconds.

**Current state (already configured):**

| Parameter | Mac | Server |
|---|---|---|
| Device ID | `EJ6FHJG` | `6JODYFX` |
| Config dir | `~/Library/Application Support/Syncthing/` | `~/.config/syncthing/` |
| Vault path | `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/DenisJournals` | `/opt/obsidian-vault` |
| Service | `homebrew.mxcl.syncthing` (launchd) | `syncthing@deploy` (systemd) |
| Folder ID | `obsidian-vault` | `obsidian-vault` |
| Connection | via global relay (Hetzner cloud firewall blocks port 22000 externally) | |

**GUI access:**

| Side | URL | Notes |
|---|---|---|
| Mac | `http://127.0.0.1:8384` | open directly in browser |
| Server | `http://127.0.0.1:8384` (on server) | access via SSH tunnel: `ssh -i ~/.ssh/id_rsa -L 8385:127.0.0.1:8384 deploy@<server-host>` → `http://127.0.0.1:8385` |

Folder shows **"Up to Date"** when in sync. Remote device shows **"Up to Date"** when peer is connected and synced.

**Check sync status (Mac):**

```bash
# Via Syncthing API
curl -s -H "X-API-Key: $(grep -o '<apikey>[^<]*' ~/Library/Application\ Support/Syncthing/config.xml | cut -d'>' -f2)" \
  http://127.0.0.1:8384/rest/system/connections | python3 -c "
import json,sys; d=json.load(sys.stdin)
for k,v in d.get('connections',{}).items():
    if k!='total': print(k[:16],'connected:',v.get('connected'),'addr:',v.get('address','-'))
"
```

Or open `http://127.0.0.1:8384` in browser — folder shows **Up to Date** when in sync.

**Restart Syncthing if disconnected:**

```bash
# Mac
brew services restart syncthing

# Server
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'sudo systemctl restart syncthing@deploy'
```

**If devices show "Disconnected (Inactive)" — force reconnect:**

```bash
API_KEY=$(grep -o '<apikey>[^<]*' ~/Library/Application\ Support/Syncthing/config.xml | cut -d'>' -f2)
SRV_ID="6JODYFX-EEYVQQA-VRWGIUE-OAKH3DA-5LAMQYZ-3FR5HEN-GK7JWU5-DH24MAD"
# Pause then unpause to force retry
curl -s -X PATCH -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d "{\"deviceID\":\"$SRV_ID\",\"paused\":true}" http://127.0.0.1:8384/rest/config/devices/$SRV_ID
sleep 2
curl -s -X PATCH -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d "{\"deviceID\":\"$SRV_ID\",\"paused\":false}" http://127.0.0.1:8384/rest/config/devices/$SRV_ID
```

**Fresh install on a new Mac:**

1. Install Syncthing: `brew install syncthing && brew services start syncthing`
2. Open `http://127.0.0.1:8384` → Actions → Show ID — note the device ID
3. Add the device ID to server config via server's Syncthing GUI (via SSH tunnel: `ssh -L 8385:127.0.0.1:8384 deploy@<server-host>`, then open `http://127.0.0.1:8385`)
4. Share folder `obsidian-vault` with the new device on both sides
5. Create `.stfolder` marker: `touch ~/Library/Mobile\ Documents/iCloud~md~obsidian/Documents/DenisJournals/.stfolder`

---

### Obsidian vault sync check

```bash
# Files on server
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" "find /opt/obsidian-vault -name '*.md' | wc -l"
# Expected: > 0 (should match Mac vault count)

# Server Syncthing status
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  "curl -s -H 'X-API-Key: \$(grep -o \"<apikey>[^<]*\" ~/.config/syncthing/config.xml | cut -d\">\" -f2)' \
  http://127.0.0.1:8384/rest/db/status?folder=obsidian-vault" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('state:',d.get('state'),'files:',d.get('globalFiles'),'needFiles:',d.get('needFiles'))"
```

**Trigger LightRAG re-index after bulk Obsidian changes:**

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '/opt/lightrag/scripts/lightrag-ingest.sh'
```

---

### Legacy rsync sync (deprecated)

The old one-way rsync agent (`com.openclaw.obsidian-sync`) is still installed at
`~/Library/LaunchAgents/com.openclaw.obsidian-sync.plist` but is superseded by Syncthing.
It can be left in place (it runs but finds nothing to sync since Syncthing handles it),
or unloaded:

```bash
launchctl unload ~/Library/LaunchAgents/com.openclaw.obsidian-sync.plist
```

## If SSH times out during banner exchange

This indicates a host-level access problem before shell login. Use Hetzner Console for recovery checks:

1. verify server power state and load
2. verify Hetzner Firewall still allows `22/tcp` from your current client IP
3. verify `sshd` is active (`systemctl status ssh`)
4. if the host is overloaded, restart only `openclaw-gateway` first, then re-test SSH

## OmniRoute operations

OmniRoute runs as an additional service inside the OpenClaw Docker Compose project (`docker-compose.override.yml`).

### Start / stop

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && sudo docker compose up -d omniroute'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && sudo docker compose stop omniroute'
```

### Status and logs

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && sudo docker compose ps'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && sudo docker compose logs --tail=100 omniroute'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && sudo docker compose logs -f omniroute'
```

### Access dashboard via SSH tunnel

```bash
ssh -i ~/.ssh/id_rsa -L 20128:localhost:20128 "$OPENCLAW_HOST" -N &
# Open http://localhost:20128 in browser
# Password: see /opt/openclaw/client-secrets/omniroute-password.txt on server
kill %1   # close tunnel when done
```

### Test API from server

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf http://127.0.0.1:20129/v1/models \
    -H "Authorization: Bearer $(grep ^OMNIROUTE_API_KEY /opt/openclaw/.env | cut -d= -f2)"
'
```

### Bootstrap providers (one-time, via SSH tunnel)

Open dashboard via SSH tunnel (see above), then:

1. **OpenRouter** — auto-connects from `OPENROUTER_API_KEY` in `omniroute.env` (check green in Dashboard → Providers)
2. **Codex CLI** — Dashboard → Providers → Codex CLI → Connect → OpenAI OAuth (same credentials as OpenClaw)
3. **Kiro** — Dashboard → Providers → Kiro → Connect → AWS Builder ID OAuth
4. **Qoder** — Dashboard → Providers → Qoder → Connect → OAuth (gives Kimi, Qwen, DeepSeek)
5. **Gemini CLI** — Dashboard → Providers → Gemini CLI → Connect → Google OAuth (same Google account)

After auth, tokens persist in the `omniroute-data` volume and auto-refresh.

### Create routing tiers (one-time, via dashboard)

Dashboard → Combos → Create New:

| Combo name | Strategy | Chain |
|---|---|---|
| `smart` | priority | Codex/gpt-5.4 → Kiro/claude-sonnet → OpenRouter/claude-3.5-sonnet → Qoder/kimi-k2 |
| `medium` | priority | Codex/gpt-4o-mini → Kiro/claude-haiku → Qoder/kimi → Qoder/qwen3 |
| `light` | priority | Gemini CLI/gemini-2.0-flash → Qoder/qwen3-coder → Kiro/claude-haiku |

After creating combos: Dashboard → API Manager → Create Key → copy bearer token.

### Generate OmniRoute API key (one-time)

1. Open dashboard
2. Go to API Manager → Create Key
3. Copy bearer token
4. Add to `/opt/openclaw/.env`: `OMNIROUTE_API_KEY=<token>`
5. Re-create openclaw-gateway: `sudo docker compose up -d --force-recreate openclaw-gateway`

### Upgrade OmniRoute

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw/omniroute-src && sudo git pull
  cd /opt/openclaw && sudo docker compose build --no-cache omniroute
  sudo docker compose up -d --force-recreate omniroute
'
```

The `omniroute-data` volume persists auth tokens and settings across rebuilds.
