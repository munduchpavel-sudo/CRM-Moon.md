import { Router } from 'express';
import fetch from 'node-fetch';

const router = Router();

router.post('/summarize', async (req, res) => {
  const { text } = req.body;
  if (!text) return res.status(400).json({ error: 'text required' });

  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) return res.status(500).json({ error: 'OPENAI_API_KEY not configured on server' });

  try {
    const response = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + apiKey
      },
      body: JSON.stringify({
        model: 'gpt-4o-mini',
        messages: [{ role: 'user', content: 'Please summarize the following text in Czech concisely:\n' + text }],
        max_tokens: 200
      })
    });
    const data = await response.json();
    const summary = data?.choices?.[0]?.message?.content || data?.choices?.[0]?.text || JSON.stringify(data);
    res.json({ summary });
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: 'AI request failed', details: String(e) });
  }
});

export default router;
