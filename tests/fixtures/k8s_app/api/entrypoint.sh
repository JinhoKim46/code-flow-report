#!/bin/sh
set -e
python -m api.migrate
exec gunicorn -b 0.0.0.0:8000 "api.wsgi:create_app()"
