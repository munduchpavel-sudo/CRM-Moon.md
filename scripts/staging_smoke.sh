#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-}"
MODE="${2:---full}"

if [[ -z "$BASE_URL" ]]; then
  echo "Usage: $0 <base-url> [--full|--readiness-only]"
  exit 1
fi

BASE_URL="${BASE_URL%/}"

expect_200() {
  local path="$1"
  local code
  : > /tmp/smoke.out
  code=$(curl -sS --max-time 10 -o /tmp/smoke.out -w "%{http_code}" "$BASE_URL$path" || true)
  if [[ "$code" != "200" ]]; then
    echo "ERROR: $path returned HTTP $code"
    if [[ -s /tmp/smoke.out ]]; then
      cat /tmp/smoke.out || true
    fi
    exit 1
  fi
  echo "OK 200: $path"
}

expect_200 "/api/health"
expect_200 "/pyapi/openapi.json"
expect_200 "/pyapi/system/metrics.prom"

if [[ "$MODE" == "--readiness-only" ]]; then
  echo "Readiness-only smoke passed for $BASE_URL"
  exit 0
fi

if [[ "$MODE" != "--full" ]]; then
  echo "ERROR: Unknown mode $MODE"
  exit 1
fi

EMAIL="release.smoke.$(date +%s)@example.com"
PASS="ReleaseSmoke123!"

reg_code=$(curl -sS --max-time 10 -o /tmp/reg.json -w "%{http_code}" \
  -X POST "$BASE_URL/api/auth/register" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\",\"full_name\":\"Release Smoke\"}")
if [[ "$reg_code" != "201" ]]; then
  echo "ERROR: register returned HTTP $reg_code"
  cat /tmp/reg.json || true
  exit 1
fi
echo "OK 201: /api/auth/register"

login_code=$(curl -sS --max-time 10 -o /tmp/login.json -w "%{http_code}" \
  -X POST "$BASE_URL/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}")
if [[ "$login_code" != "200" ]]; then
  echo "ERROR: login returned HTTP $login_code"
  cat /tmp/login.json || true
  exit 1
fi

token=$(sed -n 's/.*"accessToken":"\([^"]*\)".*/\1/p' /tmp/login.json)
if [[ -z "$token" ]]; then
  echo "ERROR: login response does not include accessToken"
  cat /tmp/login.json || true
  exit 1
fi
echo "OK 200 + token: /api/auth/login"

google_code=$(curl -sS --max-time 10 -o /tmp/google.json -w "%{http_code}" "$BASE_URL/api/calendar/google/authorize" || true)
if [[ "$google_code" != "200" ]]; then
  echo "ERROR: /api/calendar/google/authorize returned HTTP $google_code"
  cat /tmp/google.json || true
  exit 1
fi
echo "OK 200: /api/calendar/google/authorize"

echo "Full staging smoke passed for $BASE_URL"
