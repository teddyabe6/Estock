#!/usr/bin/env sh
# Apply migrations, then start the API. Migrations are safe to re-run.
set -e
echo "Applying database migrations..."
alembic upgrade head
if [ "${SEED_ON_START}" = "true" ]; then
  echo "Seeding demo data..."
  python -m app.seed
fi
exec "$@"
