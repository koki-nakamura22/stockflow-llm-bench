#!/bin/bash
set -e
docker compose up -d 2>&1
sleep 5
alembic upgrade head 2>&1
echo "Migration done"