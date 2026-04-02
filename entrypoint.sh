#!/bin/sh
set -e

# Run database migrations on deploy/startup by default.
if [ "${RUN_DB_MIGRATIONS:-true}" = "true" ]; then
  python manage.py migrate --noinput
fi

exec gunicorn \
  --workers 2 \
  -b 0.0.0.0:8000 \
  --log-level debug \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  jurisdoc.wsgi:application
