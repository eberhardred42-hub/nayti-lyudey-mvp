#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="infra/docker-compose.yml"
BASE_URL="http://localhost:8000"

export DEBUG=1
export SMS_PROVIDER=mock
export CONFIG_SOURCE=db

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
  echo "[smoke-admin] FAIL: $*" >&2
  echo "[smoke-admin] logs (tail=300):" >&2
  docker compose -f "$COMPOSE_FILE" logs --tail=200 api render render-worker redis db minio front || true
  echo "[smoke-admin] teardown (failure)" >&2
  docker compose -f "$COMPOSE_FILE" down -v --remove-orphans || true
  exit 1
}

trap 'fail "unexpected error (line $LINENO)"' ERR

curl_json() {
  curl --show-error --silent --fail "$@"
}

py_get() {
  python3 -c "import sys,json; obj=json.load(sys.stdin); print($1)"
}

echo "[smoke-admin] docker compose up -d --build"
docker compose -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true

echo "[smoke-admin] configuring admin auth env"
PHONE="+79990000000"
ADMIN_PASSWORD="admin123"
export ADMIN_PHONE_ALLOWLIST="$PHONE"
export ADMIN_PASSWORD_SALT="smoke-salt"
export ADMIN_PASSWORD_HASH=$(python3 - <<'PY'
import hashlib
pwd = "admin123"
salt = "smoke-salt"
dk = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt.encode("utf-8"), 100_000)
print(dk.hex())
PY
)

if [[ -z "${ADMIN_PASSWORD_HASH:-}" ]]; then
  fail "failed to compute ADMIN_PASSWORD_HASH"
fi

docker compose -f "$COMPOSE_FILE" up -d --build

echo "[smoke-admin] waiting for API health..."
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

echo "[smoke-admin] auth (mock OTP)"

OTP_JSON=$(curl_json -X POST "$BASE_URL/auth/otp/request" \
  -H 'Content-Type: application/json' \
  --data "{\"phone\":\"$PHONE\"}") || fail "otp request"

CODE=$(python3 -c 'import sys,json; print((json.load(sys.stdin) or {}).get("code") or "")' <<<"$OTP_JSON")

if [[ -z "${CODE:-}" ]]; then
  CODE=$(curl_json "$BASE_URL/debug/otp/latest?phone=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$PHONE")" | \
    python3 -c 'import sys,json; print(json.load(sys.stdin)["code"])') || fail "otp latest"
fi

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

echo "[smoke-admin] admin login"
ADMIN_TOKEN=$(curl_json -X POST "$BASE_URL/admin/login" \
  -H "$AUTHZ" \
  -H 'Content-Type: application/json' \
  --data "{\"admin_password\":\"$ADMIN_PASSWORD\"}" | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["admin_token"])') || fail "admin login"

ADMIN_TOKEN=${ADMIN_TOKEN:-}
if [[ -z "$ADMIN_TOKEN" ]]; then
  fail "no admin_token"
fi

XADMIN="X-Admin-Token: $ADMIN_TOKEN"

curl -sf "$BASE_URL/admin/me" -H "$XADMIN" >/dev/null || fail "/admin/me"
curl -sf "$BASE_URL/admin/overview" -H "$XADMIN" >/dev/null || fail "/admin/overview"

echo "[smoke-admin] trigger config fallback (should record alert_event)"
# This endpoint loads documents_registry via resolve_config; with CONFIG_SOURCE=db and no active config it will fallback and emit an alert.
DOCS_JSON=$(curl_json "$BASE_URL/admin/documents" -H "$XADMIN") || fail "/admin/documents"
DOC_ID=$(python3 -c 'import sys,json; obj=json.load(sys.stdin); items=obj.get("items") or []; print((items[0] or {}).get("doc_id") or "")' <<<"$DOCS_JSON")
if [[ -z "$DOC_ID" ]]; then
  fail "no doc_id from /admin/documents"
fi

echo "[smoke-admin] list + ack latest alert"
ALERTS_JSON=$(curl_json "$BASE_URL/admin/alerts?limit=5" -H "$XADMIN") || fail "/admin/alerts"
ALERT_ID=$(python3 -c 'import sys,json; obj=json.load(sys.stdin); items=obj.get("items") or []; print((items[0] or {}).get("id") or "")' <<<"$ALERTS_JSON")
if [[ -n "$ALERT_ID" ]]; then
  curl -sf -X POST "$BASE_URL/admin/alerts/$ALERT_ID/ack" -H "$XADMIN" >/dev/null || fail "ack alert"
fi

echo "[smoke-admin] config lifecycle (documents_registry): draft -> update -> validate -> dry-run -> publish"
DRAFT_VERSION=$(curl_json -X POST "$BASE_URL/admin/config/documents_registry/draft" -H "$XADMIN" | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["version"])') || fail "config draft"

UPDATE_BODY=$(python3 - <<'PY'
import json
with open('api/documents.v1.json', 'r', encoding='utf-8') as f:
    obj = json.load(f)
payload_text = json.dumps(obj, ensure_ascii=False)
print(json.dumps({"payload_text": payload_text, "comment": "smoke-admin"}, ensure_ascii=False))
PY
)

curl -sf -X POST "$BASE_URL/admin/config/documents_registry/update" \
  -H "$XADMIN" -H 'Content-Type: application/json' --data "$UPDATE_BODY" >/dev/null || fail "config update"

curl -sf -X POST "$BASE_URL/admin/config/documents_registry/validate?version=$DRAFT_VERSION" -H "$XADMIN" >/dev/null || fail "config validate"

curl -sf -X POST "$BASE_URL/admin/config/documents_registry/dry-run?version=$DRAFT_VERSION" -H "$XADMIN" >/dev/null || fail "config dry-run"

curl -sf -X POST "$BASE_URL/admin/config/documents_registry/publish?version=$DRAFT_VERSION" -H "$XADMIN" >/dev/null || fail "config publish"

echo "[smoke-admin] documents edit (metadata/access)"
curl -sf -X POST "$BASE_URL/admin/documents/$DOC_ID/metadata" \
  -H "$XADMIN" -H 'Content-Type: application/json' \
  --data '{"description":"(smoke-admin)"}' >/dev/null || fail "doc metadata"

# Toggle access (disable -> enable) to exercise endpoints.
curl -sf -X POST "$BASE_URL/admin/documents/$DOC_ID/access" \
  -H "$XADMIN" -H 'Content-Type: application/json' \
  --data '{"enabled":false,"tier":"free"}' >/dev/null || fail "doc access disable"

curl -sf -X POST "$BASE_URL/admin/documents/$DOC_ID/access" \
  -H "$XADMIN" -H 'Content-Type: application/json' \
  --data '{"enabled":true,"tier":"free"}' >/dev/null || fail "doc access enable"

echo "[smoke-admin] logs endpoint"
curl -sf "$BASE_URL/admin/logs?limit=20" -H "$XADMIN" >/dev/null || fail "/admin/logs"

echo "[smoke-admin] create session"
SESSION_ID=$(curl -sf -X POST "$BASE_URL/sessions" \
  -H "$AUTHZ" \
  -H 'Content-Type: application/json' \
  --data '{"profession_query":"QA инженер"}' | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["session_id"])') || fail "create session"

if [[ -z "$SESSION_ID" ]]; then
  fail "no session_id"
fi

echo "[smoke-admin] create pack via /ml/job (mock)"
PACK_ID=$(curl -sf -X POST "$BASE_URL/ml/job" \
  -H "$AUTHZ" \
  -H 'Content-Type: application/json' \
  --data "{\"session_id\":\"$SESSION_ID\"}" | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["pack_id"])') || fail "create pack"

if [[ -z "$PACK_ID" ]]; then
  fail "no pack_id"
fi

echo "[smoke-admin] trigger pack render"
curl -sf -X POST "$BASE_URL/packs/$PACK_ID/render" -H "$AUTHZ" >/dev/null || fail "pack render"

echo "[smoke-admin] poll pack documents for a ready PDF"
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

echo "[smoke-admin] download ready PDF"
DL_JSON=$(curl -sf "$BASE_URL/files/$READY_FILE_ID/download" -H "$AUTHZ")
DOWNLOAD_URL=$(python3 -c 'import sys,json; print(json.load(sys.stdin)["url"])' <<<"$DL_JSON")

if [[ -z "${DOWNLOAD_URL:-}" ]]; then
  fail "download URL missing"
fi

MAGIC=$(curl -sfL --range 0-3 "$DOWNLOAD_URL")
if [[ "$MAGIC" != "%PDF" ]]; then
  fail "downloaded content is not a PDF (magic=$MAGIC)"
fi

echo "[smoke-admin] teardown"
docker compose -f "$COMPOSE_FILE" down -v

echo "[smoke-admin] OK"
