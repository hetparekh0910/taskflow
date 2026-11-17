#!/bin/sh
set -e
# Only the API container migrates; worker/beat set RUN_MIGRATIONS=0 so they never race it.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi
exec "$@"
