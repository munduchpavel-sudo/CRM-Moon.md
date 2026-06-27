from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_hardware_telemetry_endpoint_returns_data():
    response = client.get('/hardware/telemetry/1')
    assert response.status_code == 200
    body = response.json()
    assert body['property_name']
    assert 'protocols_ingestion' in body


def test_client_payout_endpoint_returns_clean_payout():
    response = client.get('/agregator/client-payout/1?battery_capacity_mwh=2.5')
    assert response.status_code == 200
    body = response.json()
    assert 'client_dashboard_display' in body
    assert 'INTERNAL_LOG' in body
