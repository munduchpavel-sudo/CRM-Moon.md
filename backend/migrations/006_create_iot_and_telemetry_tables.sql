-- Hardwarová zařízení (Střídače SolarEdge, podružné měřiče, baterie)
CREATE TABLE IF NOT EXISTS iot_devices (
    id SERIAL PRIMARY KEY,
    property_id INT REFERENCES properties(id) ON DELETE CASCADE,
    device_type VARCHAR(100) NOT NULL, -- 'solaredge_inverter', 'mbus_water_meter', 'modbus_emeter'
    serial_number VARCHAR(100) UNIQUE NOT NULL,
    local_ip VARCHAR(50),
    api_key_encrypted VARCHAR(255), -- Pro cloudové vyčítání
    status VARCHAR(50) DEFAULT 'active'
);

-- Telemetrická data (Časové řady - v produkci doporučuji TimescaleDB rozšíření)
CREATE TABLE IF NOT EXISTS telemetry_data (
    id BIGSERIAL,
    device_id INT REFERENCES iot_devices(id) ON DELETE CASCADE,
    timestamp TIMESTAMP NOT NULL,
    power_generation_kw DECIMAL(10, 3) DEFAULT 0.0, -- Aktuální výroba FVE
    power_consumption_kw DECIMAL(10, 3) DEFAULT 0.0, -- Celková spotřeba objektu
    battery_soc_percent DECIMAL(5, 2), -- Stav nabití baterie
    PRIMARY KEY (id, timestamp)
);

-- Podružné měření konkrétních nájemců
CREATE TABLE IF NOT EXISTS tenant_consumption_logs (
    id BIGSERIAL,
    tenant_space_id INT REFERENCES property_tenants(id) ON DELETE CASCADE,
    timestamp TIMESTAMP NOT NULL,
    consumed_kwh_total DECIMAL(12, 3) NOT NULL, -- Kumulativní stav elektroměru
    PRIMARY KEY (id, timestamp)
);

-- Ceny na spotovém trhu (Zrcadlo dat z OTE)
CREATE TABLE IF NOT EXISTS spot_market_prices (
    id SERIAL PRIMARY KEY,
    market_date DATE NOT NULL,
    market_hour INT NOT NULL, -- 0 až 23
    price_eur_mwh DECIMAL(10, 2) NOT NULL,
    price_czk_kwh DECIMAL(10, 4) NOT NULL, -- Přepočtená cena pro algoritmus
    CONSTRAINT unique_date_hour UNIQUE (market_date, market_hour)
);

-- Servisní a revizní plány / Alerting
CREATE TABLE IF NOT EXISTS service_alerts (
    id SERIAL PRIMARY KEY,
    property_id INT REFERENCES properties(id) ON DELETE CASCADE,
    device_id INT REFERENCES iot_devices(id) ON DELETE SET NULL,
    alert_type VARCHAR(50) NOT NULL, -- 'error_code', 'annual_revision', 'anomaly'
    title VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'open', -- 'open', 'in_progress', 'resolved'
    due_date DATE, -- Termín povinné revize
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
