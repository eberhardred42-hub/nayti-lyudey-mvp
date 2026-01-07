#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

# Explicitly force mock providers (must not require external keys).
export SMS_PROVIDER="${SMS_PROVIDER:-mock}"
export LLM_PROVIDER="${LLM_PROVIDER:-mock}"

fail() {
  echo "[first-run] FAIL: $*" >&2
  exit 1
}

curl_json() {
  curl --show-error --silent --fail "$@"
}

urlencode() {
  python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$1"
}

echo "[first-run] waiting for API health..."
for i in $(seq 1 90); do
  if curl -sf "$BASE_URL/health" >/dev/null 2>&1; then
    break
  fi
  echo "[first-run] waiting... ($i/90)"
  sleep 1
  if [[ $i -eq 90 ]]; then
    fail "API did not become ready"
  fi
done

curl -sf "$BASE_URL/health" >/dev/null || fail "/health"
curl -sf "$BASE_URL/health/db" >/dev/null || fail "/health/db"
curl -sf "$BASE_URL/health/llm" >/dev/null || fail "/health/llm"
curl -sf "$BASE_URL/health/sms" >/dev/null || fail "/health/sms"
curl -sf "$BASE_URL/health/s3" >/dev/null || fail "/health/s3"

echo "[first-run] auth (mock OTP)"
PHONE="+79990000000"

curl -sf -X POST "$BASE_URL/auth/otp/request" \
  -H 'Content-Type: application/json' \
  --data "{\"phone\":\"$PHONE\"}" >/dev/null || fail "otp request"

CODE=$(curl_json "$BASE_URL/debug/otp/latest?phone=$(urlencode "$PHONE")" | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["code"])') || fail "otp latest"

if [[ -z "${CODE:-}" ]]; then
  fail "otp latest returned empty/invalid JSON"
fi

TOKEN=$(curl_json -X POST "$BASE_URL/auth/otp/verify" \
  -H 'Content-Type: application/json' \
  --data "{\"phone\":\"$PHONE\",\"code\":\"$CODE\"}" | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])') || fail "otp verify"

if [[ -z "${TOKEN:-}" ]]; then
  fail "otp verify returned empty/invalid JSON"
fi

AUTHZ="Authorization: Bearer $TOKEN"

curl -sf -X POST "$BASE_URL/legal/offer/accept" -H "$AUTHZ" >/dev/null || fail "offer accept"

echo "[first-run] create session"
SESSION_ID=$(curl_json -X POST "$BASE_URL/sessions" \
  -H "$AUTHZ" \
  -H 'Content-Type: application/json' \
  --data '{"profession_query":"QA инженер"}' | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["session_id"])') || fail "create session"

if [[ -z "${SESSION_ID:-}" ]]; then
  fail "no session_id"
fi

echo "[first-run] create pack"
PACK_ID=$(curl_json -X POST "$BASE_URL/ml/job" \
  -H "$AUTHZ" \
  -H 'Content-Type: application/json' \
  --data "{\"session_id\":\"$SESSION_ID\"}" | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["pack_id"])') || fail "create pack"

if [[ -z "${PACK_ID:-}" ]]; then
  fail "no pack_id"
fi

echo "[first-run] trigger pack render"
curl -sf -X POST "$BASE_URL/packs/$PACK_ID/render" -H "$AUTHZ" >/dev/null || fail "pack render"

echo "[first-run] poll pack documents for a ready PDF"
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

echo "[first-run] download ready PDF"
DL_JSON=$(curl_json "$BASE_URL/files/$READY_FILE_ID/download" -H "$AUTHZ") || fail "download meta"
DOWNLOAD_URL=$(python3 -c 'import sys,json; print(json.load(sys.stdin)["url"])' <<<"$DL_JSON") || fail "download url parse"

if [[ -z "${DOWNLOAD_URL:-}" ]]; then
  fail "download URL missing"
fi

MAGIC=$(curl -sfL "$DOWNLOAD_URL" | head -c 4)
if [[ "$MAGIC" != "%PDF" ]]; then
  fail "downloaded content is not a PDF (magic=$MAGIC)"
fi

echo "[first-run] OK"
