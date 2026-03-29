#!/usr/bin/env bash
set -euo pipefail

export FLASK_CONFIG="${FLASK_CONFIG:-config.ProdConfig}"
export PORT="${PORT:-5000}"

exec python -m gunicorn --bind "0.0.0.0:${PORT}" wsgi:app
