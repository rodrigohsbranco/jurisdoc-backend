#!/bin/sh
set -e

# Run database migrations on deploy/startup by default.
if [ "${RUN_DB_MIGRATIONS:-true}" = "true" ]; then
  python manage.py migrate --noinput
  # Sincroniza o catálogo de capacidades (idempotente) — garante que novas
  # capacidades (ex.: kits.honorarios_iniciais) existam no banco após o deploy.
  python manage.py sync_capacidades
fi

exec gunicorn \
  --workers 2 \
  --timeout 120 \
  -b 0.0.0.0:8000 \
  --log-level debug \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  jurisdoc.wsgi:application
