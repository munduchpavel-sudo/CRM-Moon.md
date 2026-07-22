import { Router } from 'express';
import fetch from 'node-fetch';
import pool from '../pg.js';

const router = Router();

router.get('/google/authorize', (_req, res) => {
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
  if (!code) return res.status(400).send('code missing');

  try {
    const response = await fetch('https://oauth2.googleapis.com/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        code,
        client_id: clientId || '',
        client_secret: clientSecret || '',
        redirect_uri: redirect,
        grant_type: 'authorization_code'
      })
    });
    const data = await response.json();
    await pool.query(
      'INSERT INTO google_tokens (user_id, provider_account_id, access_token, refresh_token, scope, token_type, expiry) VALUES ($1, $2, $3, $4, $5, $6, $7)',
      [null, data.id_token || null, data.access_token, data.refresh_token, data.scope, data.token_type, data.expires_in ? new Date(Date.now() + data.expires_in * 1000) : null]
    );
    res.send('Google tokens stored. You can close this window.');
  } catch (e) {
    console.error(e);
    res.status(500).send('token exchange failed');
  }
});

router.post('/create-event', async (req, res) => {
  const { calendarId = 'primary', summary, description, start, end } = req.body;
  try {
    const result = await pool.query('SELECT * FROM google_tokens LIMIT 1');
    const tokenRow = result.rows[0];
    if (!tokenRow) return res.status(400).json({ error: 'no google token stored' });

    const response = await fetch(`https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(calendarId)}/events`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + tokenRow.access_token
      },
      body: JSON.stringify({ summary, description, start: { dateTime: start }, end: { dateTime: end } })
    });
    const event = await response.json();
    await pool.query(
      'INSERT INTO google_events (user_id, external_id, calendar_id, summary, description, start_ts, end_ts, raw) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)',
      [null, event.id, calendarId, event.summary, event.description, event.start?.dateTime || event.start?.date, event.end?.dateTime || event.end?.date, event]
    );
    res.json(event);
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: 'create event failed', details: String(e) });
  }
});

export default router;
