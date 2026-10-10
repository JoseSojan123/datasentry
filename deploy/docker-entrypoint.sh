#!/bin/sh
# Optionally apply database migrations before starting (for single-service hosts without a release step).
set -e
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "Applying database migrations"
  alembic upgrade head
fi
exec "$@"
