# CRM Moon

[![CI](https://github.com/munduchpavel-sudo/CRM-Moon.md/actions/workflows/ci.yml/badge.svg)](https://github.com/munduchpavel-sudo/CRM-Moon.md/actions/workflows/ci.yml)

This repository contains a basic CRM scaffold with:
- Docker Compose setup for PostgreSQL, backend, frontend, and nginx
- Additional FastAPI service for EMS/observability endpoints (`/system/*`, `/ems/*`, `/telemetry/*`)
- Express backend with auth, calendar, and AI routes
- Vite React frontend scaffold

## Run locally

1. Install dependencies:
   - Backend: `cd backend && npm install`
   - Frontend: `cd frontend && npm install`
2. Prepare environment variables:
   - `cp .env.example .env`
   - adjust secrets/keys as needed
3. Start the backend:
   - `cd backend && npm run dev`
4. Start the frontend:
   - `cd frontend && npm run dev`
5. Optional: run with Docker:
   - `docker compose up --build`
   - health check via nginx: `http://localhost/pyapi/system/health`
   - metrics via nginx: `http://localhost/pyapi/system/metrics.prom`
   - note: dev uses HTTP-first nginx config (`infra/nginx/default.dev.conf`)
6. Production compose variant:
   - `cp .env.prod.example .env.prod`
   - fill production secrets and keys in `.env.prod`
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
});

export default router;


import { Request, Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';
const JWT_SECRET = process.env.JWT_SECRET || 'please_change_me';

export interface AuthRequest extends Request {
  user?: any
## Module Map

- **`app.py`**: hlavní FastAPI aplikace (testovaná aplikace). Obsahuje většinu endpointů (auth, agregátor, EMS, hardware, smlouvy, atd.) a zahrnuje router z `backend/fastapi_erp.py` pod prefixem `/erp`.
- **`backend/fastapi_erp.py`**: dříve samostatná FastAPI aplikace, nyní exportuje `APIRouter` (`/erp`) s legacy ERP endpointy (EMS analyzátor, stavební deník, atd.).
- **`backend/`**: Node.js/Express backend (TypeScript/JS) v `backend/src` — produkční REST API, migrace a Dockerfile.
- **`frontend/`**: Vite + React frontend scaffold.
- **`infra/nginx/default.dev.conf`**: nginx config pro lokální/dev provoz (HTTP).
- **`infra/nginx/default.prod.conf`**: nginx config pro produkci (HTTPS + certifikáty).
- **`docker-compose.prod.yml`**: produkční override (publikace portu 443).
- **`ai_assistant.py`**: lokální simulace AI asistenta pro CRM (Python helper).
- **`localization.py`**: lokalizační utilita.
- **`partner_commission.py`**: business logic pro rozdělení provize partnera.
- **`tests/`**: obsahuje testy (`tests/test_new_endpoints.py`) které používají `app` z `app.py`.
- **`backup/CODE_CRM-1.txt`**: záloha původního `code CRM-1.py` (obsahoval Docker Compose, nginx, SQL a ukázky JS/TS).

Pokud chcete, mohu provést další konsolidaci (sloučit endpointy do modulů `app/api/...`), nebo vytvořit samostatné podsložky pro každý modul.

FROM nginx:stable-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]


POSTGRES_PASSWORD=StrongPostgresPassword_here
JWT_SECRET=VerySecretJwtKey_here
ADMIN_EMAIL=admin@moon-sun.cz
ADMIN_PASSWORD=ChangeMe123!
OPENAI_API_KEY=sk-...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...


