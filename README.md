# CRM Moon

[![CI](https://github.com/munduchpavel-sudo/CRM-Moon.md/actions/workflows/ci.yml/badge.svg)](https://github.com/munduchpavel-sudo/CRM-Moon.md/actions/workflows/ci.yml)

This repository contains a basic CRM scaffold with:
- Docker Compose setup for PostgreSQL, backend, frontend, and nginx
- Additional FastAPI service for EMS/observability endpoints (`/system/*`, `/ems/*`, `/telemetry/*`)
- EMS umí při zapnutém live režimu automaticky pollovat Modbus gateway po startu i v běhu
- Express backend with auth, calendar, and AI routes
- Vite React frontend scaffold

## Run locally

1. Install dependencies:
   - Python: `/workspaces/CRM-Moon.md/.venv/bin/pip install -r requirements.txt`
   - Backend: `npm --prefix backend install`
   - Frontend: `npm --prefix frontend install`
2. Prepare environment variables:
   - `cp .env.example .env`
   - set real values for `JWT_SECRET`, `DATABASE_URL`, API keys
   - keep `DEMO_AUTH_ENABLED=false` for production-like runs
3. Start services separately (dev mode):
   - Backend API (Express): `npm --prefix backend run dev` (default port `4000`)
   - Frontend (Vite): `npm --prefix frontend run dev`
   - FastAPI (EMS): `/workspaces/CRM-Moon.md/.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000`
4. Or run the whole stack with Docker:
   - `docker compose up --build`
   - backend po startu automaticky čeká na DB a teprve pak aplikuje migrace
   - health check via nginx: `http://localhost/pyapi/system/health`
   - metrics via nginx: `http://localhost/pyapi/system/metrics.prom`
   - dev uses HTTP-first nginx config (`infra/nginx/default.dev.conf`)
   - pro live RTU/Modbus nastavte `MODBUS_LIVE_ENABLED=true`, `MODBUS_DEFAULT_GATEWAY_IP` na gateway/RTU adresu a případně `MODBUS_AUTO_POLL_INTERVAL_SEC`
5. Production compose variant:
   - `cp .env.prod.example .env.prod`
   - fill production secrets and keys in `.env.prod`
   - keep `DEMO_AUTH_ENABLED=false`
   - `docker compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
   - prod uses TLS-enabled nginx config (`infra/nginx/default.prod.conf`)

## API

- Health check: `/health`
- FastAPI health check: `/pyapi/system/health`
- FastAPI Prometheus metrics: `/pyapi/system/metrics.prom`
- Auth: `/api/auth/*`
- Clients: `/api/clients`
- Calendar: `/api/calendar/*`
- AI summary: `/api/ai/summarize`
- Swagger docs: `/api/docs`

## Module Map

- `app.py`: hlavní FastAPI aplikace (testovaná aplikace). Obsahuje většinu endpointů (auth, agregátor, EMS, hardware, smlouvy, atd.) a zahrnuje router z `backend/fastapi_erp.py` pod prefixem `/erp`.
- `backend/fastapi_erp.py`: dříve samostatná FastAPI aplikace, nyní exportuje `APIRouter` (`/erp`) s legacy ERP endpointy (EMS analyzátor, stavební deník, atd.).
- `backend/`: Node.js/Express backend (TypeScript/JS) v `backend/src` - produkční REST API, migrace a Dockerfile.
- `frontend/`: Vite + React frontend scaffold.
- `infra/nginx/default.dev.conf`: nginx config pro lokální/dev provoz (HTTP).
- `infra/nginx/default.prod.conf`: nginx config pro produkci (HTTPS + certifikáty).
- `docker-compose.prod.yml`: produkční override (publikace portu 443).
- `ai_assistant.py`: lokální simulace AI asistenta pro CRM (Python helper).
- `localization.py`: lokalizační utilita.
- `partner_commission.py`: business logika pro rozdělení provize partnera.
- `tests/`: testy (`tests/test_new_endpoints.py`, `tests/test_nexus_dispatcher.py`) používající `app` z `app.py`.
- `backup/CODE_CRM-1.txt`: záloha původního souboru.

## Go-Live (3 kroky)

1. Security preflight (secrets + kritická konfigurace)
   - `cp .env.prod.example .env.prod`
   - doplň reálné hodnoty
   - `bash scripts/security_preflight.sh .env.prod`

2. Staging smoke test
   - `bash scripts/staging_smoke.sh https://staging.example.com --full`

3. Průběžný monitoring + alerting
   - workflow: `.github/workflows/uptime-monitor.yml`
   - nastav GitHub secret `STAGING_BASE_URL`
   - volitelně nastav `MONITOR_WEBHOOK_URL` pro alert notifikace při failu
