#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="infra/docker-compose.yml"
BASE_URL="http://localhost:8000"

export DEBUG=1
export SMS_PROVIDER=mock

export S3_PROVIDER=s3
export S3_ENDPOINT=http://minio:9000
export S3_PRESIGN_ENDPOINT=http://localhost:9000
export S3_REGION=us-east-1
export S3_BUCKET=nayti-lyudey
export S3_ACCESS_KEY=minioadmin
export S3_SECRET_KEY=minioadmin
export S3_USE_SSL=0

# IMPORTANT: consumed inside the `api` container.
export DATABASE_URL=postgresql://postgres:postgres@db:5432/nlyudi

export REDIS_URL=redis://redis:6379/0
export RENDER_URL=http://render:8000
export RENDER_TIMEOUT_SEC=120

fail() {
  echo "[smoke] FAIL: $*" >&2
  echo "[smoke] logs (tail=300):" >&2
  docker compose -f "$COMPOSE_FILE" logs --tail=120 api render render-worker redis db minio || true
  echo "[smoke] teardown (failure)" >&2
  docker compose -f "$COMPOSE_FILE" down -v --remove-orphans || true
  exit 1
}

trap 'fail "unexpected error (line $LINENO)"' ERR

jq_get() {
  python3 -c "import sys,json; obj=json.load(sys.stdin); print($1)"
}

curl_json() {
  # Fail fast on non-2xx; still print errors.
  # NOTE: command substitutions in bash can mask failures under `set -e`,
  # so always wrap calls to this function with `|| fail ...`.
  curl --show-error --silent --fail "$@"
}

echo "[smoke] docker compose up -d --build"
docker compose -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
docker compose -f "$COMPOSE_FILE" up -d --build

echo "[smoke] waiting for API health..."
for i in $(seq 1 60); do
  if curl -sf "$BASE_URL/health" >/dev/null; then
    break
  fi
  sleep 1
  if [[ $i -eq 60 ]]; then
    fail "API did not become ready"
  fi
done

curl -sf "$BASE_URL/health" >/dev/null || fail "/health"
curl -sf "$BASE_URL/health/db" >/dev/null || fail "/health/db"
curl -sf "$BASE_URL/health/sms" >/dev/null || fail "/health/sms"
curl -sf "$BASE_URL/health/s3" >/dev/null || fail "/health/s3"

echo "[smoke] auth (mock OTP)"
PHONE="+79990000000"

curl -sf -X POST "$BASE_URL/auth/otp/request" \
  -H 'Content-Type: application/json' \
  --data "{\"phone\":\"$PHONE\"}" >/dev/null || fail "otp request"

CODE=$(curl_json "$BASE_URL/debug/otp/latest?phone=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$PHONE")" | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["code"])') || fail "otp latest"

CODE=${CODE:-}
if [[ -z "$CODE" ]]; then
  fail "otp latest returned empty/invalid JSON"
fi

TOKEN=$(curl_json -X POST "$BASE_URL/auth/otp/verify" \
  -H 'Content-Type: application/json' \
  --data "{\"phone\":\"$PHONE\",\"code\":\"$CODE\"}" | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])') || fail "otp verify"

TOKEN=${TOKEN:-}
if [[ -z "$TOKEN" ]]; then
  fail "otp verify returned empty/invalid JSON"
fi

AUTHZ="Authorization: Bearer $TOKEN"

curl -sf -X POST "$BASE_URL/legal/offer/accept" -H "$AUTHZ" >/dev/null || fail "offer accept"

echo "[smoke] create session"
SESSION_ID=$(curl -sf -X POST "$BASE_URL/sessions" \
  -H "$AUTHZ" \
  -H 'Content-Type: application/json' \
  --data '{"profession_query":"QA инженер"}' | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["session_id"])')

if [[ -z "$SESSION_ID" ]]; then
  fail "no session_id"
fi

echo "[smoke] create pack via /ml/job (mock)"
PACK_ID=$(curl -sf -X POST "$BASE_URL/ml/job" \
  -H "$AUTHZ" \
  -H 'Content-Type: application/json' \
  --data "{\"session_id\":\"$SESSION_ID\"}" | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["pack_id"])')

if [[ -z "$PACK_ID" ]]; then
  fail "no pack_id"
fi

echo "[smoke] trigger pack render"
curl -sf -X POST "$BASE_URL/packs/$PACK_ID/render" -H "$AUTHZ" >/dev/null || fail "pack render"

echo "[smoke] poll pack documents for a ready PDF"
READY_FILE_ID=""
for i in $(seq 1 90); do
  DOCS_JSON=$(curl_json "$BASE_URL/packs/$PACK_ID/documents" -H "$AUTHZ") || fail "GET /packs/$PACK_ID/documents"
  READY_FILE_ID=$(python3 -c "import sys, json; obj=json.load(sys.stdin); docs=obj.get('documents') or []; print(next((d.get('file_id') for d in docs if d.get('status')=='ready' and d.get('file_id')), ''))" <<<"$DOCS_JSON") || fail "invalid JSON from /packs/$PACK_ID/documents"

  if [[ -n "$READY_FILE_ID" ]]; then
    break
  fi
  sleep 2
  if [[ $i -eq 90 ]]; then
    fail "no ready document after waiting"
  fi
done

echo "[smoke] download ready PDF"
DL_JSON=$(curl -sf "$BASE_URL/files/$READY_FILE_ID/download" -H "$AUTHZ")
DOWNLOAD_URL=$(python3 -c 'import sys,json; print(json.load(sys.stdin)["url"])' <<<"$DL_JSON")

if [[ -z "${DOWNLOAD_URL:-}" ]]; then
  fail "download URL missing"
fi

MAGIC=$(curl -sfL "$DOWNLOAD_URL" | head -c 4)
if [[ "$MAGIC" != "%PDF" ]]; then
  fail "downloaded content is not a PDF (magic=$MAGIC)"
fi

echo "[smoke] teardown"
docker compose -f "$COMPOSE_FILE" down -v

echo "[smoke] OK"
