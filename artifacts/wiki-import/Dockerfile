FROM python:3.12-slim

ARG DEBIAN_MIRROR=https://mirror.yandex.ru/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirror.yandex.ru/debian-security

WORKDIR /app

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i \
        -e "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        -e "s|http://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|http://security.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources; \
    fi; \
    apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY entrypoint.sh ./

RUN chmod +x /app/entrypoint.sh

VOLUME ["/app/state", "/app/obsidian", "/host-opt"]

CMD ["/app/entrypoint.sh"]
