import express from 'express';
import dotenv from 'dotenv';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import swaggerUi from 'swagger-ui-express';
import YAML from 'yamljs';
import clientsRouter from './routes/clients.js';
import authRouter from './routes/auth.js';
import aiRouter from './routes/ai.js';
import calendarRouter from './routes/calendar.js';
import pool from './pg.js';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
app.use(express.json());

app.get('/health', (_req, res) => res.json({ status: 'ok' }));
app.get('/api/health', (_req, res) => res.json({ status: 'ok' }));

app.use('/api/auth', authRouter);
app.use('/api/clients', clientsRouter);
app.use('/api/ai', aiRouter);
app.use('/api/calendar', calendarRouter);

const swaggerPath = path.join(__dirname, '..', 'openapi.yaml');
try {
  const swaggerDoc = YAML.load(swaggerPath);
  app.use('/api/docs', swaggerUi.serve, swaggerUi.setup(swaggerDoc));
} catch (e) {
  console.warn('Swagger file not found or invalid', e);
}

async function runMigrations() {
  const dir = path.join(__dirname, '..', 'migrations');
  if (!fs.existsSync(dir)) return;
  const files = fs.readdirSync(dir).filter((f) => f.endsWith('.sql')).sort();
  for (const file of files) {
    const sql = fs.readFileSync(path.join(dir, file), 'utf8');
    await pool.query(sql);
    console.log('applied', file);
  }
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForDatabase() {
  const retries = Number(process.env.DB_CONNECT_RETRIES || 30);
  const delayMs = Number(process.env.DB_CONNECT_DELAY_MS || 2000);

  for (let attempt = 1; attempt <= retries; attempt += 1) {
    try {
      await pool.query('SELECT 1');
      console.log('database ready');
      return;
    } catch (error) {
      const isLast = attempt === retries;
      console.warn(`database not ready (${attempt}/${retries})`);
      if (isLast) {
        throw error;
      }
      await sleep(delayMs);
    }
  }
}

async function bootstrap() {
  await waitForDatabase();
  await runMigrations();

  const port = process.env.PORT || 4000;
  app.listen(port, () => console.log(`Backend listening on ${port}`));
}

bootstrap().catch((error) => {
  console.error('backend bootstrap failed', error);
  process.exit(1);
});
