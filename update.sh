#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${PROJECT_DIR}"

git pull --ff-only
mkdir -p data knowledge
docker compose up -d --build
docker image prune -f

echo "ExpertBoat AI updated. Check logs with: docker compose logs -f"
