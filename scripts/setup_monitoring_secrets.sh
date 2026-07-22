#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-munduchpavel-sudo/CRM-Moon.md}"

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh CLI is not installed"
  exit 1
fi

if [[ -z "${STAGING_BASE_URL:-}" ]]; then
  echo "ERROR: STAGING_BASE_URL is not set"
  echo "Example: export STAGING_BASE_URL=https://staging.example.com"
  exit 1
fi

gh secret set STAGING_BASE_URL --repo "$REPO" --body "$STAGING_BASE_URL"
echo "Set STAGING_BASE_URL"

if [[ -n "${MONITOR_WEBHOOK_URL:-}" ]]; then
  gh secret set MONITOR_WEBHOOK_URL --repo "$REPO" --body "$MONITOR_WEBHOOK_URL"
  echo "Set MONITOR_WEBHOOK_URL"
else
  echo "MONITOR_WEBHOOK_URL not set; skipping webhook secret"
fi

echo "Secrets configured."
echo "You can now trigger monitor manually:"
echo "  gh workflow run uptime-monitor.yml --repo $REPO -f base_url=$STAGING_BASE_URL"
