-- Komunikační historie (CRM timeline)
CREATE TABLE IF NOT EXISTS crm_interactions (
    id SERIAL PRIMARY KEY,
    property_id INT REFERENCES properties(id) ON DELETE CASCADE,
    created_by UUID REFERENCES users(id),
    channel VARCHAR(50) NOT NULL, -- 'phone_ai', 'email', 'chat', 'web_form'
    direction VARCHAR(10) NOT NULL, -- 'inbound', 'outbound'
    summary TEXT NOT NULL, -- AI shrnutí nebo text zprávy
    raw_transcript TEXT, -- Přepis hlasového hovoru nebo tělo e-mailu
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Digitální stavební deník
CREATE TABLE IF NOT EXISTS construction_logs (
    id SERIAL PRIMARY KEY,
    property_id INT REFERENCES properties(id) ON DELETE CASCADE,
    author_id UUID REFERENCES users(id),
    log_date DATE NOT NULL,
    weather_info VARCHAR(255),
    workforce_count INT,
    machinery_used TEXT,
    work_description TEXT NOT NULL,
    is_locked BOOLEAN DEFAULT FALSE, -- Po podpisu se uzamkne pro editaci
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_property_date UNIQUE (property_id, log_date)
);

-- Elektronické podpisy ke stavebnímu deníku
CREATE TABLE IF NOT EXISTS log_signatures (
    id SERIAL PRIMARY KEY,
    log_id INT REFERENCES construction_logs(id) ON DELETE CASCADE,
    signer_id UUID REFERENCES users(id),
    signature_hash VARCHAR(255) NOT NULL, -- Kryptografický otisk eIDAS
    signed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Fotodokumentace k projektům a deníkům
CREATE TABLE IF NOT EXISTS project_photos (
    id SERIAL PRIMARY KEY,
    property_id INT REFERENCES properties(id) ON DELETE CASCADE,
    log_id INT REFERENCES construction_logs(id) ON DELETE SET NULL,
    file_url VARCHAR(512) NOT NULL,
    ai_description TEXT, -- Automatický popisek vygenerovaný Vision AI
    gps_lat DECIMAL(10, 8),
    gps_lng DECIMAL(11, 8),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
