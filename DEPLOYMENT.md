# Deployment Checklist

## Before You Deploy

1. Rotate exposed secrets before using production.
2. Set `FLASK_CONFIG=config.ProdConfig`.
3. Set a strong `SECRET_KEY`.
4. Set a real production `DATABASE_URL`.
5. Set `TELEGRAM_BOT_TOKEN` if the bot will run.
6. Keep `AUTO_DB_BOOTSTRAP=0` in production.
7. Keep `SESSION_COOKIE_SECURE=1` and `REMEMBER_COOKIE_SECURE=1`.

## Required Commands

Run these from the project root after environment variables are ready:

```powershell
.\venv\Scripts\python.exe -m flask --app wsgi db-upgrade
.\venv\Scripts\python.exe -m flask --app wsgi deploy-preflight
```

If you want the helper script instead:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy-check.ps1
```

## Start Commands

### Windows local/service-style start

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-web.ps1 -Mode prod -Port 5000
powershell -ExecutionPolicy Bypass -File .\scripts\run-bot.ps1
```

### Linux / server start

```bash
./scripts/run-web.sh
./scripts/run-bot.sh
```

The `Procfile` uses the same production commands for platforms that support it.

## Safe Release Order

1. Pull latest code.
2. Install dependencies: `pip install -r requirements.txt`
3. Run DB migration: `flask --app wsgi db-upgrade`
4. Run safety gate: `flask --app wsgi deploy-preflight`
5. Start web.
6. Start bot.
7. Verify login, `/profile`, a public page, and one Telegram bot command.

## Recommended Post-Deploy Checks

- Web app responds on the expected port.
- Bot starts without token/config errors.
- `flask --app wsgi migration-status` shows all legacy migrations applied.
- `flask --app wsgi db heads` shows the Alembic head.
- One shop sale and one Telegram notification still work.

## Notes

- The project still keeps the legacy `schema_migrations` table for compatibility.
- New schema changes should go through `flask db migrate` and `flask db upgrade`.
- Do not rely on `run.py` for internet-facing Linux production hosting; use Gunicorn or the `Procfile` command.
