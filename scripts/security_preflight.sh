#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-.env.prod}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: Env file not found: $ENV_FILE"
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

errors=0

require_var() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR: Missing required variable: $name"
    errors=$((errors + 1))
  fi
}

check_not_placeholder() {
  local name="$1"
  local value="${!name:-}"
  if [[ "$value" =~ change_me|please_change_me|demo-google|demo- ]]; then
    echo "ERROR: Placeholder value detected in $name"
    errors=$((errors + 1))
  fi
}

require_var POSTGRES_PASSWORD
require_var JWT_SECRET
require_var DATABASE_URL
require_var GOOGLE_CLIENT_ID
require_var GOOGLE_CLIENT_SECRET

check_not_placeholder POSTGRES_PASSWORD
check_not_placeholder JWT_SECRET
check_not_placeholder DATABASE_URL
check_not_placeholder GOOGLE_CLIENT_ID
check_not_placeholder GOOGLE_CLIENT_SECRET

if [[ ${#JWT_SECRET:-0} -lt 32 ]]; then
  echo "ERROR: JWT_SECRET must be at least 32 characters"
  errors=$((errors + 1))
fi

if [[ ! "${DATABASE_URL:-}" =~ ^postgres(ql)?:// ]]; then
  echo "ERROR: DATABASE_URL must start with postgres:// or postgresql://"
  errors=$((errors + 1))
fi

if [[ "${DEMO_AUTH_ENABLED:-false}" =~ ^(1|true|yes|on)$ ]]; then
  echo "ERROR: DEMO_AUTH_ENABLED must stay false for production"
  errors=$((errors + 1))
fi

if [[ "$errors" -gt 0 ]]; then
  echo "\nPreflight failed with $errors error(s)."
  exit 1
fi

echo "Security preflight passed for $ENV_FILE"
