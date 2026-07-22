-- Tabulka nemovitostí / objektů
CREATE TABLE IF NOT EXISTS properties (
    id SERIAL PRIMARY KEY,
    owner_id UUID REFERENCES users(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    property_type VARCHAR(50) NOT NULL, -- 'family_house', 'apartment_building', 'office', 'factory'
    address VARCHAR(255) NOT NULL,
    gps_latitude DECIMAL(10, 8),
    gps_longitude DECIMAL(11, 8),
    ean_code VARCHAR(50) UNIQUE, -- Identifikátor odběrného místa pro elektřinu
    distribution_tariff VARCHAR(20), -- Např. 'D57d', 'C02d'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabulka nájemců v rámci konkrétního objektu (pro vnitřní rozúčtování)
CREATE TABLE IF NOT EXISTS property_tenants (
    id SERIAL PRIMARY KEY,
    property_id INT REFERENCES properties(id) ON DELETE CASCADE,
    tenant_id UUID REFERENCES users(id) ON DELETE CASCADE,
    space_identifier VARCHAR(100), -- Číslo bytu, označení haly (např. 'Dílna A')
    fixed_energy_price_kwh DECIMAL(10, 2) NOT NULL, -- Smluvní cena (např. 7.00 Kč)
    valid_from DATE NOT NULL,
    valid_to DATE
);
