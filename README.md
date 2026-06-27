# CRM Moon

This repository contains a basic CRM scaffold with:
- Docker Compose setup for PostgreSQL, backend, frontend, and nginx
- Express backend with auth, calendar, and AI routes
- Vite React frontend scaffold

## Run locally

1. Install dependencies:
   - Backend: `cd backend && npm install`
   - Frontend: `cd frontend && npm install`
2. Start the backend:
   - `cd backend && npm run dev`
3. Start the frontend:
   - `cd frontend && npm run dev`
4. Optional: run with Docker:
   - `docker compose up --build`

## API

- Health check: `/health`
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


