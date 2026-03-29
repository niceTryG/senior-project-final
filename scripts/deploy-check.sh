#!/usr/bin/env bash
set -euo pipefail

export FLASK_CONFIG="${FLASK_CONFIG:-config.ProdConfig}"

python -m flask --app wsgi db-upgrade
python -m flask --app wsgi deploy-preflight "$@"
