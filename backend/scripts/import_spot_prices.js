import dotenv from 'dotenv';
import fetch from 'node-fetch';
import fs from 'fs/promises';
import path from 'path';
import pool from '../src/pg.js';

dotenv.config();

function parseDate(value) {
  const normalized = value.trim().replace(/"/g, '');
  const dotDate = normalized.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
  if (dotDate) {
    const [, day, month, year] = dotDate;
    return `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
  }
  return normalized;
}

function normalizeNumber(value) {
  if (typeof value !== 'string') return Number(value);
  return Number(value.replace(',', '.').replace(/[^0-9.+-]/g, ''));
}

function parseOteCsv(csvText) {
  const lines = csvText
    .trim()
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  if (lines.length === 0) {
    throw new Error('CSV source is empty');
  }

  const header = lines[0].split(/;|,|\t/).map((cell) => cell.trim().replace(/^"|"$/g, '').toLowerCase());
  const dateIndex = header.findIndex((h) => h.includes('datum') || h.includes('date'));
  const hourIndex = header.findIndex((h) => h.includes('hodina') || h.includes('hour'));
  const eurIndex = header.findIndex((h) => h.includes('eur') && h.includes('mwh'));
  const czkIndex = header.findIndex((h) => h.includes('czk') && h.includes('kwh'));

  if (dateIndex === -1 || hourIndex === -1 || eurIndex === -1 || czkIndex === -1) {
    throw new Error('CSV header does not contain expected OTE columns: Datum/Hodina/EUR MWh/CZK kWh');
  }

  return lines.slice(1).map((line) => {
    const cells = line.split(/;|,|\t/).map((cell) => cell.trim());
    const rawDate = parseDate(cells[dateIndex] || '');
    let hour = parseInt(cells[hourIndex] || '0', 10);
    let marketDate = rawDate;

    if (hour === 24) {
      const dateObject = new Date(`${rawDate}T00:00:00Z`);
      dateObject.setUTCDate(dateObject.getUTCDate() + 1);
      marketDate = dateObject.toISOString().slice(0, 10);
      hour = 0;
    }

    return {
      market_date: marketDate,
      market_hour: hour,
      price_eur_mwh: normalizeNumber(cells[eurIndex] || '0'),
      price_czk_kwh: normalizeNumber(cells[czkIndex] || '0')
    };
  });
}

async function loadSource(source) {
  if (!source) {
    throw new Error('No source URL or file path provided');
  }

  if (source.startsWith('http://') || source.startsWith('https://')) {
    const response = await fetch(source, { timeout: 15000 });
    if (!response.ok) {
      throw new Error(`Failed to download CSV from ${source}: ${response.status} ${response.statusText}`);
    }
    return response.text();
  }

  const filePath = path.isAbsolute(source) ? source : path.resolve(process.cwd(), source);
  return fs.readFile(filePath, 'utf8');
}

async function importSpotPrices(source) {
  const csvText = await loadSource(source);
  const rows = parseOteCsv(csvText);

  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    for (const row of rows) {
      await client.query(
        `INSERT INTO spot_market_prices (market_date, market_hour, price_eur_mwh, price_czk_kwh)
         VALUES ($1, $2, $3, $4)
         ON CONFLICT (market_date, market_hour) DO UPDATE
         SET price_eur_mwh = EXCLUDED.price_eur_mwh,
             price_czk_kwh = EXCLUDED.price_czk_kwh`,
        [row.market_date, row.market_hour, row.price_eur_mwh, row.price_czk_kwh]
      );
    }
    await client.query('COMMIT');
    console.log(`Imported ${rows.length} spot price rows from ${source}`);
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}

const args = process.argv.slice(2);
const urlArgIndex = args.findIndex((arg) => arg === '--url');
const fileArgIndex = args.findIndex((arg) => arg === '--file');
const source = urlArgIndex !== -1 ? args[urlArgIndex + 1] : fileArgIndex !== -1 ? args[fileArgIndex + 1] : process.env.OTE_SPOT_CSV_URL;

if (!source) {
  console.error('Usage: npm run import:spot-prices -- --url <csv-url> OR --file <csv-path>');
  process.exit(1);
}

importSpotPrices(source)
  .then(() => process.exit(0))
  .catch((err) => {
    console.error('Import failed:', err.message || err);
    process.exit(1);
  });
