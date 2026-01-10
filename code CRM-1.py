version: '3.8'
services:
  db:
    image: postgres:15
    restart: always
    environment:
      POSTGRES_USER: crm
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: crmdb
    volumes:
      - db_data:/var/lib/postgresql/data

  backend:
    build: ./backend
    restart: always
    environment:
      DATABASE_URL: postgres://crm:${POSTGRES_PASSWORD}@db:5432/crmdb
      PORT: 4000
      JWT_SECRET: ${JWT_SECRET}
      NODE_ENV: production
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID}
      GOOGLE_CLIENT_SECRET: ${GOOGLE_CLIENT_SECRET}
      GOOGLE_REDIRECT_URI: https://crm.moon-sun.cz/api/calendar/google/callback
    depends_on:
      - db
    networks:
      - webnet

  frontend:
    build: ./frontend
    restart: always
    networks:
      - webnet

  nginx:
    image: nginx:stable-alpine
    restart: always
    volumes:
      - ./infra/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
      - ./infra/nginx/certs:/etc/letsencrypt
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - frontend
      - backend
    networks:
      - webnet

volumes:
  db_data:

networks:
  webnet:


server {
    listen 80;
    server_name crm.moon-sun.cz;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name crm.moon-sun.cz;

    ssl_certificate /etc/letsencrypt/live/crm.moon-sun.cz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/crm.moon-sun.cz/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;

    location /api/ {
        proxy_pass http://backend:4000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://frontend:3000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}


CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  full_name TEXT,
  role TEXT DEFAULT 'admin',
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);


CREATE TABLE IF NOT EXISTS google_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  provider_account_id TEXT,
  access_token TEXT,
  refresh_token TEXT,
  scope TEXT,
  token_type TEXT,
  expiry TIMESTAMP WITH TIME ZONE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);


CREATE TABLE IF NOT EXISTS google_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  external_id TEXT,
  calendar_id TEXT,
  summary TEXT,
  description TEXT,
  start_ts TIMESTAMP WITH TIME ZONE,
  end_ts TIMESTAMP WITH TIME ZONE,
  raw JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);


backend/
  package.json
  tsconfig.json
  Dockerfile
  migrations/
    001_create_users.sql
    002_google_tokens.sql
    003_google_events.sql
  src/
    index.ts
    pg.ts
    routes/
      auth.ts
      calendar.ts
      ai.ts
      clients.ts
    middleware/
      auth.ts
    seed_admin.js
  openapi.yaml


import pkg from 'pg';
const { Pool } = pkg;
const pool = new Pool({
  connectionString: process.env.DATABASE_URL || 'postgres://crm:crm_password@localhost:5432/crmdb'
});
export default pool;


import express from 'express';
import dotenv from 'dotenv';
import clientsRouter from './routes/clients';
import authRouter from './routes/auth';
import aiRouter from './routes/ai';
import calendarRouter from './routes/calendar';
import pool from './pg';
import swaggerUi from 'swagger-ui-express';
import YAML from 'yamljs';
import path from 'path';
dotenv.config();

const app = express();
app.use(express.json());

app.get('/health', (req, res) => res.json({ status: 'ok' }));

app.use('/api/auth', authRouter);
app.use('/api/clients', clientsRouter);
app.use('/api/ai', aiRouter);
app.use('/api/calendar', calendarRouter);

// Swagger UI
const swaggerPath = path.join(__dirname, '..', 'openapi.yaml');
try {
  const swaggerDoc = YAML.load(swaggerPath);
  app.use('/api/docs', swaggerUi.serve, swaggerUi.setup(swaggerDoc));
} catch (e) {
  console.warn('Swagger file not found or invalid', e.message);
}

// Simple migration runner
import fs from 'fs';
async function runMigrations(){
  const dir = path.join(__dirname, '..', 'migrations');
  if(!fs.existsSync(dir)) return;
  const files = fs.readdirSync(dir).filter(f=>f.endsWith('.sql')).sort();
  for(const f of files){
    const sql = fs.readFileSync(path.join(dir,f),'utf8');
    try{
      await pool.query(sql);
      console.log('applied', f);
    }catch(e){
      console.error('migration error', f, e.message);
    }
  }
}
runMigrations().catch(console.error);

const port = process.env.PORT || 4000;
app.listen(port, () => console.log(`Backend listening on ${port}`));


import { Router } from 'express';
import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';
import pool from '../pg';
const router = Router();
const JWT_SECRET = process.env.JWT_SECRET || 'please_change_me';

router.post('/register', async (req, res) => {
  const { email, password, full_name } = req.body;
  if (!email || !password) return res.status(400).json({ error: 'email+password required' });
  const hashed = await bcrypt.hash(password, 10);
  try {
    const result = await pool.query('INSERT INTO users (email, password_hash, full_name) VALUES ($1,$2,$3) RETURNING id,email,full_name,role', [email, hashed, full_name]);
    const user = result.rows[0];
    res.status(201).json(user);
  } catch (e) {
    console.error(e);
    res.status(400).json({ error: 'could not create user' });
  }
});

router.post('/login', async (req, res) => {
  const { email, password } = req.body;
  if (!email || !password) return res.status(400).json({ error: 'email+password required' });
  try {
    const result = await pool.query('SELECT * FROM users WHERE email = $1', [email]);
    const user = result.rows[0];
    if (!user) return res.status(401).json({ error: 'invalid credentials' });
    const ok = await bcrypt.compare(password, user.password_hash);
    if (!ok) return res.status(401).json({ error: 'invalid credentials' });
    const token = jwt.sign({ sub: user.id, email: user.email, role: user.role }, JWT_SECRET, { expiresIn: '8h' });
    res.json({ accessToken: token });
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: 'server error' });
  }
});

export default router;


import { Request, Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';
const JWT_SECRET = process.env.JWT_SECRET || 'please_change_me';

export interface AuthRequest extends Request {
  user?: any
}

export function authMiddleware(req: AuthRequest, res: Response, next: NextFunction) {
  const auth = req.headers['authorization'] as string;
  if (!auth) return res.status(401).json({ error: 'missing token' });
  const parts = auth.split(' ');
  if (parts.length !== 2) return res.status(401).json({ error: 'invalid auth header' });
  const token = parts[1];
  try {
    const payload = jwt.verify(token, JWT_SECRET);
    req.user = payload;
    next();
  } catch (e) {
    return res.status(401).json({ error: 'invalid token' });
  }
}


import { Router } from 'express';
import fetch from 'node-fetch';
import pool from '../pg';
const router = Router();

router.get('/google/authorize', (req, res) => {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const redirect = process.env.GOOGLE_REDIRECT_URI || 'https://crm.moon-sun.cz/api/calendar/google/callback';
  const scope = encodeURIComponent('openid email profile https://www.googleapis.com/auth/calendar.events');
  const url = `https://accounts.google.com/o/oauth2/v2/auth?response_type=code&client_id=${clientId}&redirect_uri=${encodeURIComponent(redirect)}&scope=${scope}&access_type=offline&prompt=consent`;
  res.json({ url });
});

router.get('/google/callback', async (req, res) => {
  const code = req.query.code as string;
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  const redirect = process.env.GOOGLE_REDIRECT_URI || 'https://crm.moon-sun.cz/api/calendar/google/callback';
  if(!code) return res.status(400).send('code missing');

  try {
    const resp = await fetch('https://oauth2.googleapis.com/token', {
      method: 'POST',
      headers: { 'Content-Type':'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        code,
        client_id: clientId,
        client_secret: clientSecret,
        redirect_uri: redirect,
        grant_type: 'authorization_code'
      })
    });
    const data = await resp.json();
    // TODO: link to authenticated user (req.user). For now, store without user.
    await pool.query(
      'INSERT INTO google_tokens (user_id, provider_account_id, access_token, refresh_token, scope, token_type, expiry) VALUES ($1,$2,$3,$4,$5,$6,$7)',
      [null, data.id_token || null, data.access_token, data.refresh_token, data.scope, data.token_type, data.expires_in ? (new Date(Date.now()+data.expires_in*1000)) : null]
    );
    res.send('Google tokens stored. You can close this window.');
  } catch (e) {
    console.error(e);
    res.status(500).send('token exchange failed');
  }
});

router.post('/create-event', async (req, res) => {
  const { calendarId='primary', summary, description, start, end } = req.body;
  try {
    const r = await pool.query('SELECT * FROM google_tokens LIMIT 1');
    const tokenRow = r.rows[0];
    if(!tokenRow) return res.status(400).json({ error: 'no google token stored' });
    const accessToken = tokenRow.access_token;
    const resp = await fetch(`https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(calendarId)}/events`, {
      method: 'POST',
      headers: { 'Content-Type':'application/json', 'Authorization': 'Bearer ' + accessToken },
      body: JSON.stringify({ summary, description, start: { dateTime: start }, end: { dateTime: end } })
    });
    const ev = await resp.json();
    await pool.query('INSERT INTO google_events (user_id, external_id, calendar_id, summary, description, start_ts, end_ts, raw) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)', [null, ev.id, calendarId, ev.summary, ev.description, ev.start?.dateTime || ev.start?.date, ev.end?.dateTime || ev.end?.date, ev]);
    res.json(ev);
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: 'create event failed', details: String(e) });
  }
});

export default router;


import { Router } from 'express';
import fetch from 'node-fetch';
const router = Router();

router.post('/summarize', async (req, res) => {
  const { text } = req.body;
  if (!text) return res.status(400).json({ error: 'text required' });
  const apiKey = process.env.OPENAI_API_KEY;
  if(!apiKey) return res.status(500).json({ error: 'OPENAI_API_KEY not configured on server' });

  try {
    const resp = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type':'application/json', 'Authorization': 'Bearer ' + apiKey },
      body: JSON.stringify({
        model: 'gpt-4o-mini',
        messages: [{ role: 'user', content: 'Please summarize the following text in Czech concisely:\\n' + text }],
        max_tokens: 200
      })
    });
    const data = await resp.json();
    const summary = data?.choices?.[0]?.message?.content || data?.choices?.[0]?.text || JSON.stringify(data);
    res.json({ summary });
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: 'AI request failed', details: String(e) });
  }
});

export default router;


const { Client } = require('pg');
const bcrypt = require('bcryptjs');
(async ()=> {
  const client = new Client({ connectionString: process.env.DATABASE_URL });
  await client.connect();
  const email = process.env.ADMIN_EMAIL || 'admin@moon-sun.cz';
  const pw = process.env.ADMIN_PASSWORD || 'ChangeMe123!';
  const hashed = await bcrypt.hash(pw, 10);
  const res = await client.query('SELECT id FROM users WHERE email=$1', [email]);
  if(res.rowCount===0){
    await client.query('INSERT INTO users (email, password_hash, full_name, role) VALUES ($1,$2,$3,$4)', [email, hashed, 'Admin', 'admin']);
    console.log('admin user created:', email);
  } else {
    console.log('admin exists');
  }
  await client.end();
})().catch(e=>{ console.error(e); process.exit(1); });


frontend/
  package.json
  vite.config.js
  index.html
  src/
    main.jsx
    App.jsx


import React from 'react';
export default function App(){ return (<div style={{padding:20}}>CRM Moon&Sun — frontend build placeholder</div>); }


FROM node:18-alpine as build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

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



