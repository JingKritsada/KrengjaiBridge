#!/usr/bin/env bash
# Sync the repo to the ECS and rebuild the stack. Usage: deploy/deploy.sh [host]
set -euo pipefail
HOST="${1:-root@119.13.81.32}"
cd "$(dirname "$0")/.."
rsync -az --delete \
  --exclude .venv --exclude .git --exclude data/runtime --exclude .pytest_cache \
  --exclude __pycache__ --exclude .playwright-mcp --exclude .impeccable --exclude eval/cache \
  --exclude '/.env' --exclude '/.env.line' --exclude '/.env.cloud' --exclude '/deploy/.env' \
  ./ "$HOST:/srv/kjb/"
ssh "$HOST" 'cd /srv/kjb/deploy && docker compose up -d --build app 2>&1 | tail -2'
sleep 6
curl -fsS https://119-13-81-32.sslip.io/api/health && echo
