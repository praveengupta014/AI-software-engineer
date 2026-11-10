#!/bin/sh
# Creates .env with strong random values for a Docker deployment. Safe to run twice.
set -e
cd "$(dirname "$0")"

if [ -f .env ] && grep -q '^POSTGRES_PASSWORD=' .env; then
  echo ".env is already set up. Nothing changed."
  exit 0
fi

umask 077
{
  echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
  echo "COUNTERSIGN_AUDIT_KEY=$(openssl rand -hex 32)"
} >> .env
echo "Created .env. Keep it safe: COUNTERSIGN_AUDIT_KEY verifies your audit trail."
echo "Next: docker compose up --build -d"
