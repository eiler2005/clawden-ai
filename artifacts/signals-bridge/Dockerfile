FROM python:3.12-slim

ARG LAST30DAYS_COMMIT=01812ec1851e5c3d92a9049a41b7da4adbfbcb5d

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    nodejs \
    npm \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt yt-dlp

COPY last30days_patches /app/last30days_patches

RUN git clone https://github.com/mvanhorn/last30days-skill.git /opt/last30days-skill \
 && cd /opt/last30days-skill \
 && git checkout "$LAST30DAYS_COMMIT" \
 && python - <<'PY'
from pathlib import Path

path = Path("/opt/last30days-skill/scripts/lib/env.py")
text = path.read_text()
needle = "        ('BSKY_APP_PASSWORD', None),\n"
insert = "        ('GITHUB_TOKEN', None),\n"
if insert not in text:
    if needle not in text:
        raise SystemExit("Failed to locate insertion point for GITHUB_TOKEN in env.py")
    text = text.replace(needle, needle + insert, 1)
    path.write_text(text)
PY

RUN python /app/last30days_patches/patch_last30days_skill.py /opt/last30days-skill

COPY *.py ./
COPY entrypoint.sh ./

RUN chmod +x /app/entrypoint.sh

VOLUME ["/app/sessions", "/app/state"]

CMD ["/app/entrypoint.sh"]
