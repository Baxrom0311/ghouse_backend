# AgroAI Backend

FastAPI backend for the AgroAI smart greenhouse SaaS. It handles authentication,
tenant-aware greenhouse management, telemetry, MQTT device commands, and AI chat.

## Local Development

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements2.txt
uvicorn app.main:app --reload
```

The development configuration defaults to SQLite and local CORS origins. Create
`.env` only when you need to override defaults.

Useful checks:

```sh
.venv/bin/pytest -q
curl -s http://127.0.0.1:8000/health
```

## Production Compose

Copy `.env.example` to `.env`, replace every placeholder, then run:

```sh
docker compose up -d --build
docker compose ps
```

The production stack contains:

- `frontend`: nginx serving the React app and proxying `/api`, `/docs`,
  `/openapi.json`, `/health`, and websocket traffic to the backend.
- `web`: FastAPI served by Gunicorn with Uvicorn workers.
- `migrate`: one-shot Alembic migration runner before `web` and `worker`.
- `worker`: MQTT telemetry ingestion.
- `db`: PostgreSQL, reachable only inside the Docker network.
- `mqtt`: Mosquitto broker for devices.

Production requires:

- PostgreSQL `DATABASE_URL`; SQLite is rejected when `APP_ENV=production`.
- Strong `SECRET_KEY`; example placeholder keys are rejected.
- Real `DEEPSEEK_API_KEY`; example placeholder keys are rejected.
- Explicit `CORS_ORIGINS` and `ALLOWED_HOSTS`; wildcard hosts are rejected.
- Real MQTT credentials and AI API keys.

See `../PRODUCTION.md` for deployment notes.

## Main Endpoints

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/tenants/current`
- `GET /api/greenhouses`
- `POST /api/greenhouses`
- `POST /api/ai/chat`
- `POST /api/greenhouses/{greenhouse_id}/ai/chat`
- `GET /health`
- `GET /health/ready`
