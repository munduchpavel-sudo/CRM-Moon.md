# Release Checklist

Tento checklist slouží pro finální uvedení projektu do provozu.

## 1) Security preflight

1. Zkopíruj produkční env šablonu:
   - `cp .env.prod.example .env.prod`
2. Doplň reálné hodnoty (žádné `change_me`):
   - `POSTGRES_PASSWORD`
   - `JWT_SECRET`
   - `DATABASE_URL`
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
3. Ověř konfiguraci:
   - `bash scripts/security_preflight.sh .env.prod`

## 2) Staging smoke test

1. Ověř jen readiness:
   - `bash scripts/staging_smoke.sh https://staging.example.com --readiness-only`
2. Ověř full smoke:
   - `bash scripts/staging_smoke.sh https://staging.example.com --full`

## 3) Monitoring + alerting

1. Nastav secrets (je potřeba přístup s oprávněním pro repo secrets):
   - `export STAGING_BASE_URL=https://staging.example.com`
   - `export MONITOR_WEBHOOK_URL=https://hooks.example.com/monitor`
   - `bash scripts/setup_monitoring_secrets.sh munduchpavel-sudo/CRM-Moon.md`
2. Manuálně spusť monitor workflow:
   - `gh workflow run uptime-monitor.yml --repo munduchpavel-sudo/CRM-Moon.md -f base_url=https://staging.example.com`
3. Ověř, že run prošel:
   - `gh run list --repo munduchpavel-sudo/CRM-Moon.md --workflow uptime-monitor.yml --limit 5`

## 4) Finální merge gate

1. CI checky musí být zelené:
   - `workflow-lint`
   - `test (3.12)`
   - `compose-validate`
   - `nginx-validate`
   - `e2e-docker-smoke`
2. Po merge spusť ještě jednou readiness smoke proti produkční doméně.
