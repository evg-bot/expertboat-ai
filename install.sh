#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo ./install.sh"
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${PROJECT_DIR}"
EXPERTBOAT_DATA_DIR="${EXPERTBOAT_DATA_DIR:-/data/expertboat-data}"

apt-get update
apt-get install -y ca-certificates curl git gnupg
install -m 0755 -d /etc/apt/keyrings

if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
fi

. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

mkdir -p data knowledge
mkdir -p "${EXPERTBOAT_DATA_DIR}"/{avito,telegram,processed,review,faq,chunks}
mkdir -p "${EXPERTBOAT_DATA_DIR}"/manuals/{lowrance,garmin,simrad,flir,minnkota,mercury,yamaha}

if [[ ! -f .env ]]; then
  cp .env.example .env
  sed -i "s|^EXPERTBOAT_DATA_DIR=.*|EXPERTBOAT_DATA_DIR=${EXPERTBOAT_DATA_DIR}|" .env
  echo "Created .env from .env.example. Fill real credentials, then run: docker compose up -d --build"
fi

docker compose up -d --build

echo "ExpertBoat AI deployment finished. Check logs with: docker compose logs -f"
