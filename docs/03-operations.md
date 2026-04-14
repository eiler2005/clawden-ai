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
- tool execution that agents depend on

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

## Voice transcription status

Voice transcription is intentionally disabled in the current production image. The VPS keeps only the runtime dependency that is operationally required for `bind=lan`:

- `iproute2` in the container image
- no `whisper`
- no `ffmpeg`
- no `ffprobe`

Verify the current absence in the same runtime context where OpenClaw actually runs:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway sh -lc "
    command -v whisper || echo container_whisper_absent
    command -v ffmpeg || echo container_ffmpeg_absent
    command -v ffprobe || echo container_ffprobe_absent
  "
'
```

And verify the host stays clean too:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  command -v whisper || echo host_whisper_absent
  command -v ffmpeg || echo host_ffmpeg_absent
  command -v ffprobe || echo host_ffprobe_absent
'
```

If voice workflows become important later, add them back intentionally via a lighter CPU-first stack or an external API rather than by default in the main runtime image.

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

LightRAG is the retrieval layer over the markdown memory corpus. It indexes workspace files and the
curated LLM-Wiki layer plus raw signal digests, then lets OpenClaw ask narrow historical questions
without loading archives into the conversation. It is useful for "what do we know about X?" and
"why did we decide Y?", but it is not authoritative for live service state.

Data flow:

```text
workspace/*.md + workspace/memory/*.md + workspace/raw/*.md
Obsidian vault via Syncthing
  ├─ wiki/**/*.md
  └─ raw/signals/**/*.md
        ↓
/opt/lightrag/scripts/lightrag-ingest.sh
        ↓
POST /documents/upload + POST /documents/reprocess_failed
        ↓
chunks + entities + relationships + vectors
        ↓
OpenClaw lightrag_query → http://lightrag:9621/query
```

### Check LightRAG health

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf http://127.0.0.1:8020/health | jq .
'
```

### Check LightRAG indexing status

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf http://127.0.0.1:8020/documents/status_counts | jq .
'
```

Healthy indexing should converge to `failed=0`. Upload success alone is not enough: documents can
be accepted by `/documents/upload` and still fail later during LLM extraction.

For LLM-Wiki rollout v2, `documents/status_counts` should not suddenly jump because of legacy vault
folders or bulk `raw/articles` imports. If it does, the ingest boundary has drifted.

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

### Check curated import bridge

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  token="$(sudo awk -F= "/^WIKI_IMPORT_TOKEN=/{print substr(\$0, length(\$1)+2)}" /opt/wiki-import/wiki-import.env | tail -n1)"
  curl -sf http://127.0.0.1:8095/health && echo
  curl -sf http://127.0.0.1:8095/status -H "Authorization: Bearer ${token}" | jq .
'
```

### Trigger curated wiki import manually

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  token="$(sudo awk -F= "/^WIKI_IMPORT_TOKEN=/{print substr(\$0, length(\$1)+2)}" /opt/wiki-import/wiki-import.env | tail -n1)"
  curl -sf -X POST http://127.0.0.1:8095/trigger \
    -H "Authorization: Bearer ${token}" \
    -H "Content-Type: application/json" \
    -d "{\"source_type\":\"url\",\"source\":\"https://example.com/article\",\"target_kind\":\"auto\"}" | jq .
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

### Query LightRAG as OpenClaw sees it

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway sh -lc "
    node -e \"fetch(\\\"http://lightrag:9621/query\\\", {
      method: \\\"POST\\\",
      headers: {\\\"Content-Type\\\": \\\"application/json\\\"},
      body: JSON.stringify({query: \\\"test query\\\", mode: \\\"hybrid\\\"})
    }).then(r => r.text()).then(t => console.log(t.slice(0, 1000)))\"
  "
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
# Curated wiki tree on server
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" "find /opt/obsidian-vault/wiki -name '*.md' | wc -l"
# Expected: > 0 and growing via curated import

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

## Telethon Digest

Telethon Digest reads Denis's Telegram subscriptions via Telethon and posts structured
digests to the configured supergroup topic using the OpenClaw Telegram bot token.
It calls OmniRoute (`http://omniroute:20129/v1`) for LLM summarization and dedup.

**Scheduling:** OpenClaw Gateway Cron Jobs trigger one-shot runs at
`08:00, 11:00, 14:00, 17:00, 21:00 MSK`. No long-running daemon.

**Digest types (auto-selected by hour):**

| Hour | Type | Format |
|------|------|--------|
| 08:00 | morning | Compact snapshot, 1-2 messages |
| 11/14/17 | interval | Per-folder Tier A detail + Tier B summary |
| 21:00 | editorial | Full editorial: summary → themes → must-read → low signal → watchpoints |

### Deploy

```bash
export OPENCLAW_HOST="deploy@<server-host>"
bash scripts/deploy-telethon-digest.sh
```

The script: rsyncs source, fills secrets from `/opt/openclaw/.env`, rebuilds image,
stops the old daemon if any, removes legacy `/etc/cron.d/telethon-digest`, and syncs
the five OpenClaw Cron Jobs into the Gateway store so they appear in Control → Cron Jobs.

**Managed OpenClaw jobs:**

- `Telethon Digest · 08:00 Morning brief`
- `Telethon Digest · 11:00 Regular digest`
- `Telethon Digest · 14:00 Regular digest`
- `Telethon Digest · 17:00 Regular digest`
- `Telethon Digest · 21:00 Evening editorial`

Each job runs as an **isolated OpenClaw cron run** and sends one authenticated
HTTP trigger from the gateway container to `telethon-digest-cron-bridge` inside
`openclaw_default`. The bridge then runs `python digest_worker.py --now` with an
explicit `DIGEST_TYPE_OVERRIDE`, which keeps the run type stable even if the
gateway retries a job later than the scheduled hour.

The cron sync script also sets a longer OpenClaw run timeout (`1800` seconds by
default) so the cron run can wait for the digest to finish instead of reporting
the bridge as "hung" while the worker is still processing a large window.

On this deployment, `openclaw cron list` may hang even when the gateway itself is
healthy. Because of that, the sync helpers patch the cron store (`jobs.json`)
directly, back it up first, then restart the gateway container so it reloads the
managed jobs.

This workflow is also captured as the repo skill
`skills/openclaw-cron-maintenance/SKILL.md`, so future schedule or cron-store
changes can follow one stable procedure instead of re-discovering the recovery
path each time.

### How `Пульс дня` is selected

`Пульс дня` is no longer a plain "most repeated news" block. The editorial layer now does:

1. take the strong scored post pool after `reader.py` → `scorer.py` → `dedup.py`
2. build pulse candidates from LLM `themes`, local extraction, and fallback storyline lines
3. rank candidates by:
   - repeated / cross-channel signal
   - fit to Denis-interest buckets (`AI`, `Telegram/privacy`, `fintech`, `geopolitics`, `creator`, `product`, `science`)
   - novelty vs recently published pulse lines
   - line quality (prefer storyline/theme, avoid source-like labels)
   - diversity bonus so one category does not flood the block
4. publish one strong line per bucket first, then fill remaining slots with the next best lines

The bucket profile is persisted in `/app/state/pulse-profile.json` inside the shared `telethon-state`
volume. It is updated after each digest from the current strong-post pool and stores:

- bucket momentum from recent windows
- learned bucket terms discovered from recurring posts
- recent pulse signatures to suppress stale repetition

This ranking/profile layer is intentionally generic and can later be reused for `inbox-email` or
`work-email` recaps.

**Important:** the target OpenClaw agent must be allowed to use `exec` and must
have access to `/opt/telethon-digest`. The sync script defaults to agent `main`,
but you can override it with `OPENCLAW_CRON_AGENT=ops` before deploy if your
server uses a dedicated ops agent. The sync script reads existing jobs from
`/opt/openclaw/config/cron/jobs.json` by default; override with
`OPENCLAW_CRON_STORE=...` if your gateway uses a custom cron store path.

**Bridge diagnostics:**

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'curl -s http://127.0.0.1:8091/health && echo && curl -s http://127.0.0.1:8091/status'
```

- `GET /health` — quick liveness + last run snapshot
- `GET /status` — current or last run payload with timestamps, digest type, exit code, and tail
- `POST /trigger` — synchronous run; returns `409 digest_already_running` if another digest is still in flight

### One-time Telethon authorization

```bash
ssh -t -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'cd /opt/telethon-digest && sudo docker compose run --rm telethon-digest python auth.py'
```

### Sync Telegram folders (run after auth, and after folder changes)

```bash
# Dry-run
ssh -t -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'cd /opt/telethon-digest && sudo docker compose run --rm telethon-digest python sync_channels.py --dry-run'

# Write config.json (adds position + username per channel)
ssh -t -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'cd /opt/telethon-digest && sudo docker compose run --rm telethon-digest python sync_channels.py'
```

Read scope config (`config.json` — not committed):

```json
{
  "read_only": true,
  "require_explicit_allowlist": true,
  "read_broadcast_channels_only": true,
  "allowed_folder_names": ["news", "evolution", "startups", "growth.me", "fintech", "investing", "work", "eb1", "гребенюк", "personal", "faang"]
}
```

### Run digest immediately

```bash
# Auto-detect type by current hour
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'sudo /opt/telethon-digest/cron-digest.sh'

# Force a specific type for testing
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'cd /opt/telethon-digest && sudo docker compose run --rm \
   -e DIGEST_TYPE_OVERRIDE=morning telethon-digest python digest_worker.py --now'
```

### Watch logs

```bash
# Digest log (one line per run)
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'sudo tail -f /var/log/telethon-digest-cron.log'

# Detailed docker log from last run
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'cd /opt/telethon-digest && sudo docker compose logs --tail=100'
```

### Check OpenClaw cron schedule

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'sudo cat /opt/openclaw/config/cron/jobs.json 2>/dev/null || sudo cat /home/deploy/.openclaw/cron/jobs.json'
```

## AgentMail Inbox Email

AgentMail Inbox Email polls the personal inbox every 5 minutes through a standalone Python
bridge that talks to the AgentMail HTTP API directly, uses an internal 5-minute scheduler for
poll-based state/labeling only, and publishes scheduled recaps to the `inbox-email` topic at
`08:00`, `13:00`, `16:00`, and `20:00` MSK. OpenClaw is only used for JSON-only poll
classification, and the poll path now runs a deterministic prefilter so obvious empty / low-signal
windows can skip the LLM entirely. Scheduled digests render directly from the mailbox window so
they always reflect the actual message count and senders.

If a scheduled digest window has no messages, the bridge now still posts a short
"empty window" message to Telegram instead of silently skipping the slot.

Scheduled digest windows are anchored to the fixed Moscow schedule boundaries
(`08:00 → 13:00 → 16:00 → 20:00`) rather than the timestamp of the previous manual run.

### Deploy

```bash
export OPENCLAW_HOST="deploy@<server-host>"
bash scripts/deploy-agentmail-email.sh
```

Local gitignored secret source:

```text
secrets/agentmail-email/email.env
```

Do not place real AgentMail keys in tracked docs, templates, or repo-root shell history. The only
allowed locations are the gitignored local secret file above and `/opt/agentmail-email/email.env`
on the server. The live `work-email` bridge follows the same pattern under
`secrets/agentmail-work-email/email.env` locally and `/opt/agentmail-work-email/email.env` on the server.

Required local keys:

- `AGENTMAIL_API_KEY`
- `AGENTMAIL_INBOX_REF`
- `EMAIL_DIGEST_SUPERGROUP_ID`
- `EMAIL_DIGEST_TOPIC_ID`

The deploy script:

- rsyncs `/opt/agentmail-email`
- hydrates `TELEGRAM_BOT_TOKEN` from `/opt/openclaw/.env`
- keeps `AGENTMAIL_API_KEY` inside `/opt/agentmail-email/email.env`
- removes stale AgentMail-specific coupling from the central OpenClaw config
- rebuilds the lightweight Python `agentmail-email-bridge`
- materializes the real `AGENTMAIL_INBOX_REF` into `/opt/agentmail-email/config.json`
- removes stale `/opt/agentmail-email/openclaw-config` leftovers from the old embedded-runtime design
- prunes dangling Docker image/build artifacts after a successful rebuild
- syncs the four digest OpenClaw Cron Jobs
- validates that no 5-minute poll cron job remains and that each digest cron job still has a next scheduled run

Architecture note:

- `agentmail-email-bridge` no longer carries its own OpenClaw runtime or copied auth store.
- Mailbox access now happens inside the bridge itself via the AgentMail HTTP API.
- The bridge remains responsible for Redis orchestration, Telegram posting, mailbox labels,
  and derived event persistence.
- The shared `openclaw-openclaw-gateway-1` container is used only for LLM steps over prepared
  thread snapshots or derived events.
- The 5-minute poll no longer relies on OpenClaw Cron Jobs; it is scheduled internally by the bridge.

Current validation snapshot:

- the rebuilt bridge image is about `229 MB` on server (down from the earlier embedded-runtime build)
- direct AgentMail API reads and label updates work from the bridge container
- manual `/trigger` → `poll` enqueue works
- a clean empty-window poll finished with `exit_code=0` on `2026-04-11`
- on `2026-04-12`, a manual `poll lookback=1440` finished with `exit_code=0`, scanned `32` threads,
  produced `1` publishable event, and tolerated one missing message id during label commit
- on `2026-04-12`, a manual `editorial` digest finished with `exit_code=0`, rendered from the
  mailbox window, and applied `benka/digested=1`
- on `2026-04-13`, the internal scheduler successfully self-enqueued a poll after bridge restart,
  the run finished with `exit_code=0`, and `/status` showed the new prefilter diagnostics directly
  in `poll summary` (`prefilter_scanned`, `skipped_handled`, `skipped_low_signal`,
  `candidate_threads`, `llm_skipped`)
- on `2026-04-13`, server-side image tests passed: `python -m unittest discover -s /app/tests`
  → `Ran 5 tests ... OK`

### Managed OpenClaw jobs

- `AgentMail Inbox · 08:00 Morning brief`
- `AgentMail Inbox · 13:00 Regular digest`
- `AgentMail Inbox · 16:00 Regular digest`
- `AgentMail Inbox · 20:00 Evening editorial`

## AgentMail Work Email

AgentMail Work Email is a second live runtime that reuses the same Python bridge codebase but runs
separately from the personal inbox at `/opt/agentmail-work-email`. It talks directly to the
AgentMail HTTP API for `workmail.denny@agentmail.to`, uses its own internal 5-minute scheduler for
poll-based state/labeling, and publishes scheduled digests to Telegram topic `work-email` at
`08:30`, `10:00`, `11:30`, `13:00`, `14:30`, `16:00`, `17:30`, and `19:00` MSK.

Unlike the personal `inbox-email` runtime, the work digest can resolve the original sender from
forwarded-message headers inside the email body. This is enabled only for `work-email`, so a mail
forwarded by Denis still renders under the underlying author such as `Elena Zabrodina` when the
message body contains a forwarded header block (`От:` / `From:`).

Isolation guarantees:

- separate Redis jobs stream: `ingest:jobs:email:work`
- separate derived events stream: `ingest:events:email:work`
- separate DLQ stream: `dlq:failed:email:work`
- separate consumer group: `email-workers-work`
- separate Redis status key: `status:email:work:latest`
- separate labels: `workmail/polled`, `workmail/low-signal`, `workmail/digested`
- separate Docker container / volume / localhost port (`agentmail-work-email-bridge`, `8094`)

### Deploy

```bash
export OPENCLAW_HOST="deploy@<server-host>"
bash scripts/deploy-agentmail-work-email.sh
```

Local gitignored secret source:

```text
secrets/agentmail-work-email/email.env
```

Required local keys:

- `AGENTMAIL_API_KEY`
- `AGENTMAIL_INBOX_REF`
- `EMAIL_DIGEST_SUPERGROUP_ID`
- `EMAIL_DIGEST_TOPIC_ID`

Current validation snapshot:

- on `2026-04-13`, `/opt/agentmail-work-email` deployed successfully with eight managed cron jobs
- `agentmail-work-email-bridge` came up healthy on `127.0.0.1:8094`
- internal scheduler ran a successful poll with `exit_code=0`, scanned `10` threads, emitted `6`
  derived events into `ingest:events:email:work`, and applied `workmail/polled` / `workmail/low-signal`
- server-side image tests passed: `python -m unittest discover -s /app/tests` → `Ran 5 tests ... OK`
- a manual `digest interval lookback=240` trigger finished with `exit_code=0` and applied
  `workmail/digested=1`
- on `2026-04-14`, `scripts/deploy-agentmail-work-email.sh` redeployed the bridge with
  forwarded-sender resolution enabled only for `work-email`; `GET /health` and `GET /status`
  returned `last_exit_code=0`, the internal 5-minute poll completed cleanly after restart, and all
  eight managed cron jobs remained present with `enabled=true`
- on `2026-04-14`, a live mailbox-window check inside the running bridge showed forwarded CNews
  invitations under `Elena Zabrodina` while calendar forwards still rendered as `Яндекс.Календарь`

### Managed OpenClaw jobs

- `AgentMail Work Email · 08:30 Morning triage`
- `AgentMail Work Email · 10:00 Regular digest`
- `AgentMail Work Email · 11:30 Regular digest`
- `AgentMail Work Email · 13:00 Regular digest`
- `AgentMail Work Email · 14:30 Regular digest`
- `AgentMail Work Email · 16:00 Regular digest`
- `AgentMail Work Email · 17:30 Regular digest`
- `AgentMail Work Email · 19:00 End-of-day wrap-up`

### Bridge diagnostics

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'curl -s http://127.0.0.1:8094/health && echo && curl -s http://127.0.0.1:8094/status'
```

### Integration bus checks

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XLEN ingest:jobs:email:work
  docker exec integration-bus-redis redis-cli XLEN ingest:events:email:work
  docker exec integration-bus-redis redis-cli GET status:email:work:latest
'
```

### Bridge diagnostics

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'curl -s http://127.0.0.1:8092/health && echo && curl -s http://127.0.0.1:8092/status'
```

- `GET /health` — quick liveness + last poll/digest snapshot
- `GET /status` — current or last run payload with timestamps, job type, exit code, and tail
- `POST /trigger` — enqueue `poll` or `digest` into `ingest:jobs:email`
- Optional trigger override: `lookback_minutes` for manual catch-up/backfill without editing Redis state

### Integration bus checks

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XLEN ingest:jobs:email
  docker exec integration-bus-redis redis-cli XLEN ingest:events:email
  docker exec integration-bus-redis redis-cli XPENDING ingest:jobs:email email-workers - + 10
  docker exec integration-bus-redis redis-cli XLEN dlq:failed
'
```

### Manual enqueue examples

```bash
# Poll now
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XADD ingest:jobs:email "*" \
    run_id manual-poll \
    job_type poll \
    inbox_ref <agentmail-inbox-ref> \
    requested_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    requested_by manual
'

# Poll now with a wider catch-up window
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XADD ingest:jobs:email "*" \
    run_id manual-poll-backfill \
    job_type poll \
    lookback_minutes 1440 \
    inbox_ref <agentmail-inbox-ref> \
    requested_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    requested_by manual
'

# Digest now
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XADD ingest:jobs:email "*" \
    run_id manual-digest \
    job_type digest \
    digest_type interval \
    inbox_ref <agentmail-inbox-ref> \
    requested_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    requested_by manual
'
```

### Watch logs

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'cd /opt/agentmail-email && sudo docker compose logs --tail=100 agentmail-email-bridge'
```

### Cleanup old install leftovers

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  sudo rm -rf /opt/agentmail-email/openclaw-config
  sudo docker image prune -af
  sudo docker builder prune -af
'
```

Use this after migrating away from the old embedded-runtime design or after repeated failed image builds.

## Signals Bridge

Signals Bridge polls allowlisted email + Telegram sources every 5 minutes through its own internal
Python scheduler and publishes compact mini-batches into the `signals` topic. This service does not
use OpenClaw Cron Jobs and does not use GPT-5.4 in the ingestion path; enrichment is limited to
cheap `OmniRoute light` calls with low token budgets and a local fallback.

Delivery format:

- Telegram-derived signal items include a direct source link to the originating post when one can be constructed.
- Email-derived signal items retain a compact excerpt in the rendered batch so the operator can read the core message without opening the raw mailbox.

### Deploy

```bash
export OPENCLAW_HOST="deploy@<server-host>"
bash scripts/deploy-signals-bridge.sh
```

Local gitignored secret source:

```text
secrets/signals-bridge/signals.env
secrets/signals-bridge/config.json
secrets/signals-bridge/rules/*.json
```

Required local keys:

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_PHONE`
- `SIGNALS_SUPERGROUP_ID`
- `SIGNALS_TOPIC_ID`
- `AGENTMAIL_API_KEY`

Recommended local keys:

- `OMNIROUTE_API_KEY`
- `TELEGRAM_BOT_TOKEN` if you do not want the deploy script to hydrate it from `/opt/openclaw/.env`

The deploy script:

- rsyncs `/opt/signals-bridge`
- syncs local `secrets/signals-bridge/config.json`
- syncs local `secrets/signals-bridge/rules/*.json`
- hydrates `TELEGRAM_BOT_TOKEN` from `/opt/openclaw/.env` when missing
- hydrates `OMNIROUTE_API_KEY` from `/opt/openclaw/.env` when missing
- generates `SIGNALS_BRIDGE_TOKEN` when missing
- keeps the bridge standalone; there is no OpenClaw cron-store sync step
- rebuilds the lightweight Python `signals-bridge`
- starts `signals-bridge` and validates `GET /health`

Architecture note:

- polling cadence is every 5 minutes, not every 30 seconds
- scheduling is internal to `signals-bridge`
- public docs/templates stay generic; real local rules live in separate JSON files under `secrets/signals-bridge/rules/`
- AgentMail and Telethon reads happen inside the bridge itself
- the only LLM path is cheap `OmniRoute light` enrichment for already matched candidates
- if OmniRoute is unavailable, the bridge falls back to local rule-based summaries and can still post

### Bridge diagnostics

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'curl -s http://127.0.0.1:8093/health && echo && curl -s http://127.0.0.1:8093/status'
```

- `GET /health` — quick liveness + last signals run summary
- `GET /status` — current or last run payload with ruleset id, posted count, and tail
- `POST /trigger` — enqueue a manual ruleset run into `ingest:jobs:signals`
- Optional trigger overrides:
  - `lookback_minutes` for manual catch-up/backfill
  - `source_id` to limit a manual run to one configured source

### Integration bus checks

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XLEN ingest:jobs:signals
  docker exec integration-bus-redis redis-cli XLEN ingest:events:signals
  docker exec integration-bus-redis redis-cli XPENDING ingest:jobs:signals signals-workers - + 10
  docker exec integration-bus-redis redis-cli XLEN dlq:failed
'
```

### Manual enqueue examples

```bash
# Run the whole trading ruleset now
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XADD ingest:jobs:signals "*" \
    run_id manual-signals \
    ruleset_id trading \
    requested_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    requested_by manual
'

# Run one source with a wider lookback
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XADD ingest:jobs:signals "*" \
    run_id manual-signals-backfill \
    ruleset_id trading \
    source_id telegram-trader-speki \
    lookback_minutes 60 \
    requested_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    requested_by manual
'
```

### Watch logs

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'cd /opt/signals-bridge && sudo docker compose logs --tail=100 signals-bridge'
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
  TARGET_TAG=v3.6.3
  cd /opt/openclaw/omniroute-src &&
  sudo git fetch --tags origin &&
  sudo git checkout -B "deploy/${TARGET_TAG#v}" "$TARGET_TAG"
  cd /opt/openclaw && sudo docker compose build --no-cache omniroute
  sudo docker compose up -d --force-recreate omniroute
'
```

The `omniroute-data` volume persists auth tokens and settings across rebuilds.

---

## Integration Bus (Redis Streams)

Redis runs as a standalone Docker Compose project at `/opt/integration-bus/`.

### Start / status

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/integration-bus && sudo docker compose ps
'
```

### Deploy (first time or after config change)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/integration-bus && sudo docker compose up -d
'
```

### Ping Redis

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli ping
'
```

### Check stream lengths

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XLEN ingest:jobs:telegram
  docker exec integration-bus-redis redis-cli XLEN dlq:failed
'
```

### Check pending (jobs in-flight)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli \
    XPENDING ingest:jobs:telegram digest-workers - + 10
'
```

### Inspect dead letter queue

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli \
    XRANGE dlq:failed - + COUNT 20
'
```

### Manually enqueue a digest job (bypass cron_bridge)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XADD ingest:jobs:telegram "*" \
    run_id manual-test \
    digest_type interval \
    requested_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    requested_by manual
'
```

### Trim stream (keep last 1000 entries)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XTRIM ingest:jobs:telegram MAXLEN 1000
'
```

### Check ingest:rag:queue (LightRAG upload queue)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  echo "=== RAG queue total ==="
  docker exec integration-bus-redis redis-cli XLEN ingest:rag:queue
  echo "=== Pending (in-flight) ==="
  docker exec integration-bus-redis redis-cli XPENDING ingest:rag:queue rag-workers - + 10
'
```

### Manually enqueue a file for LightRAG ingest

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XADD ingest:rag:queue "*" \
    source manual \
    file_path "/app/obsidian/Telegram Digest/Derived/2026-04-11/interval-0800-1200.md" \
    file_name "interval-0800-1200.md" \
    enqueued_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
'
```

### LightRAG WebUI (SSH tunnel)

```bash
ssh -i ~/.ssh/id_rsa -L 9621:127.0.0.1:8020 "$OPENCLAW_HOST" -N &
# → open http://127.0.0.1:9621
kill %1  # close tunnel when done
```

### LightRAG health and document status

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf http://127.0.0.1:8020/health | python3 -m json.tool
'
```

### Trigger LightRAG reprocess of failed documents

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf -X POST http://127.0.0.1:8020/documents/reprocess_failed
'
```
