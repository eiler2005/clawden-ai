# Rollback and backup

The 2026.9.1 Gateway upgrade is a state migration. Rolling back the image alone is unsafe because Gateway startup can change SQLite databases, auth profiles, conversation history, cron data, plugin state, and workspace files.

Use `scripts/upgrade-openclaw-2026-9-1.sh` only in an approved maintenance window. It is a thin Mac wrapper around a server-side state runner. It never uses `docker compose down`, never recreates OmniRoute, and recreates only `openclaw-gateway` with `--no-deps`. The prior image remains locally available throughout the window.

## Before maintenance

Stage the pinned candidate assets and run preflight. Before stopping a writer, preflight records the container image ID, label-derived active Compose chain and `.env`, effective Compose config, all Gateway mounts, active bridge callers, named host cron files, and whether `syncthing@deploy.service` is active. Those private records include credentials and are kept in a `0700` run directory with `0600` files; neither values nor Compose output belong in logs or Git.

Preflight rejects an unexpected rollback image, missing candidate assets, unknown writable mounts, overlapping host sources, a missing read-only wiki token mount, failed candidate identity checks, or insufficient disk. In normal mode, capacity must cover the candidate image, one complete mutable-state copy, and a 1 GiB reserve before a build and after it. The candidate is checked by image ID, `2026.9.1` version, and RootFS-layer prefix against the pinned base rather than a mutable tag.

The mutable set is `/opt/openclaw/config`, `/opt/openclaw/workspace`, and `/opt/obsidian-vault`, plus the read-only wiki token, Compose files, `.env`, prior cron helpers, and recorded caller/host-cron state. Syncthing is a vault writer and is paused only when `syncthing@deploy.service` was running.

## Cold archive and rehearsal

Pause only recorded callers, Syncthing when active, named host cron files, and the Gateway. Stream one uncompressed `tar --acls --xattrs --numeric-owner` archive from the stopped server directly to an ignored `0700` Mac backup directory. The pre-migration archive has its own 14-minute transfer deadline; verify it with `tar -tf` and SHA-256 before arming the candidate watchdog. Do not use `--ignore-failed-read`, compression, hard links, or an archive extraction on the VPS.

The server maintains exactly one additional state copy at a time. It makes a `cp -a` rehearsal clone so uid/gid, modes, ACLs, xattrs, WAL/SHM files, and node ownership survive. The candidate Gateway runs on all cloned mounts with no Docker network, no published port or Docker socket, production CPU/memory/PID limits, a copied read-only wiki token, and a private copy of required container environment. Clone config disables supported cron, channel, and hook switches while retaining bindings.

The rehearsal waits for in-container `/startupz`, then validates config. SQLite is inspected with `mode=ro` while WAL remains visible; no checkpoint or direct SQL write is allowed. Preserve and compare auth, history, and job inventories, then perform migration and real isolated startup a second time. The unique rehearsal container is journaled and forcibly removed on every success, timeout, or error.

### Mac-archive rollback mode

`UPGRADE_MAC_ROLLBACK_ONLY=2026.9.1` is an approved capacity exception for this
server. It skips the server-side rehearsal and candidate-state copy because there
is not enough disk for them. The stopped server state is archived to the Mac,
listed with `tar -tf`, and recorded by SHA-256 before the live Gateway is allowed
to migrate it. Keep the Mac awake, its archive directory connected, and the SSH
route available throughout the window.

If the candidate fails, the runner stops it, pauses state writers, removes the
candidate image to make room, and moves its migrated state to a retained failure
directory. The wrapper then streams the verified Mac archive back and starts the
captured 2026.6.9 image. The remote watchdog can stop a late candidate, but it
cannot restore an archive held on the Mac. This mode is therefore less resilient
than the normal server-copy procedure and is used only because the capacity gate
cannot be met.

The hold and restore paths must be idempotent: a recorded caller that is already
stopped is not an error. This permits an automatic hold followed by explicit Mac
archive preparation without leaving the Gateway or bridge callers down.

If post-build capacity proves that even this retention is impossible, the operator
may explicitly set `UPGRADE_MAC_DISCARD_FAILED_STATE=2026.9.1` before a new
preflight. This stricter low-disk variant records the archive first, then deletes
only the stopped candidate's migrated state during rollback to make room for the
original archive. It cannot retain failed-candidate diagnostics and must not be
enabled without that deliberate acknowledgement.

## Promotion, acceptance, and rollback

After rehearsal, make one fresh candidate copy. Rename untouched originals to the rollback location and rename each candidate mount into place; never overlay migrated SQLite files. The runner uses a Gateway-only Compose health override with a 180-second start period, starts the Gateway with `--no-deps`, and waits on `/healthz`, `/startupz`, and `/readyz` against a monotonic five-minute deadline. Any failure restores originals by rename and retains the failed candidate separately.

After archive verification, arm the independent 15-minute watchdog before migration. After the Gateway is stable, restore only previously running bridge containers for bridge smoke tests; leave host cron and Syncthing paused until acceptance. All acceptance gates, including the complete 300-second observation with zero restarts and no OOM, must complete before that candidate deadline. Acceptance also requires pinned image/version and health evidence, config/plugin/cron and Knowledgebase checks, primary and reserve model checks, bridge checks, and manual Telegram UI proof: a fresh request and a follow-up in an existing conversation must each show inbound handling and an outbound reply. MTProto automation is not a substitute.

Only the structured acceptance record disarms the watchdog. It restores only prior host-cron and Syncthing state. If acceptance is absent or any gate fails, the watchdog or explicit rollback stops the Gateway, preserves candidate state, restores original state/Compose/env/helper files with recorded metadata, verifies the captured rollback image ID, recreates only the old Gateway, and restores precisely the callers, host cron files, and Syncthing unit active before the window. Rollback is idempotent.

Keep one verified Mac cold archive, the original image, private manifest, and failed-candidate directory until a later release is production-verified. They contain chat history, auth, and secrets; never track them in Git or copy them into command output or tickets. After a verified recovery, delete superseded Mac archives and candidate artifacts, but retain the single archive that restored or can restore the current known-good state. An ignored, `0700` local backup directory is allowed.

## Command sequence

Use one stable, operator-chosen run ID for the whole window. The local archive directory may be an ignored, `0700` directory inside the repository's approved local backup area or any protected Mac location.

```bash
export UPGRADE_RUN_ID=20260905T120000Z
export OPENCLAW_LOCAL_BACKUP_DIR=/private/protected/openclaw-upgrades
# Capacity exception approved for this server. It requires the Mac archive for rollback.
export UPGRADE_MAC_ROLLBACK_ONLY=2026.9.1
# Only if the preflight reports that failed candidate state cannot be retained:
# export UPGRADE_MAC_DISCARD_FAILED_STATE=2026.9.1
scripts/upgrade-openclaw-2026-9-1.sh preflight
# Build the pinned candidate before maintenance; preflight already staged the assets.
export UPGRADE_CONFIRMED=2026.9.1
scripts/upgrade-openclaw-2026-9-1.sh build
# During the approved maintenance window:
scripts/upgrade-openclaw-2026-9-1.sh deploy
# Supply structured, completed manual and automated gates only after the five-minute observation:
scripts/upgrade-openclaw-2026-9-1.sh accept "$UPGRADE_RUN_ID" /private/protected/acceptance.json
# If a gate fails or the operator chooses recovery:
scripts/upgrade-openclaw-2026-9-1.sh rollback "$UPGRADE_RUN_ID"
```

Run the server-side contract probe from the staged directory after the candidate Gateway is ready and before acceptance:

```bash
sudo python3 /opt/openclaw/.upgrade-2026.9.1/check-openclaw-agent-contract.py
```

The runner independently verifies image identity, health, restart/OOM state, deadline, and the completed five-minute observation. The JSON records the operator-attested functional and manual gates; setting a boolean is never automatic proof. Start every field as `false` and set it to `true` only after its corresponding gate passes:

```json
{
  "models": false,
  "bridges": false,
  "config": false,
  "plugins": false,
  "cron": false,
  "knowledgebase": false,
  "five_minute_observation": false,
  "manual_telegram": {
    "fresh_request": false,
    "existing_conversation": false,
    "inbound": false,
    "outbound": false
  }
}
```
