#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <image-uri> <env-file>"
  exit 1
fi

IMAGE_URI="$1"
ENV_FILE="$2"
CONTAINER_NAME="${CONTAINER_NAME:-kairo-backend}"
APP_PORT="${APP_PORT:-8000}"
# Safe here because the API is published only on 127.0.0.1 and should be
# reached through nginx / a trusted reverse proxy, not directly from the public
# internet.
FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"

docker pull "${IMAGE_URI}"
docker stop "${CONTAINER_NAME}" || true
docker rm "${CONTAINER_NAME}" || true

docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  --env-file "${ENV_FILE}" \
  -e "FORWARDED_ALLOW_IPS=${FORWARDED_ALLOW_IPS}" \
  -p "127.0.0.1:${APP_PORT}:8000" \
  "${IMAGE_URI}"

# Health checks stay on loopback because public traffic should come through the
# HTTPS reverse-proxy path, not directly to the application port.
curl --fail "http://127.0.0.1:${APP_PORT}/api/v1/health/live"
