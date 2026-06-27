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
