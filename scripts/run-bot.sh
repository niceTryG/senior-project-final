#!/usr/bin/env bash
set -euo pipefail

export FLASK_CONFIG="${FLASK_CONFIG:-config.ProdConfig}"

exec python telegram_bot.py
