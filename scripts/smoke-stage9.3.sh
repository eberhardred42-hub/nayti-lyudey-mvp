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

# IMPORTANT: this value is consumed inside the `api` container. Use the docker-compose
# service name `db` (not localhost) so the API can reach Postgres over the compose network.
export DATABASE_URL=postgresql://postgres:postgres@db:5432/nlyudi

fail() {
  echo "[smoke] FAIL: $*" >&2
  echo "[smoke] logs (tail=300):" >&2
  docker compose -f "$COMPOSE_FILE" logs --tail=300 api db minio || true
  echo "[smoke] teardown (failure)" >&2
  docker compose -f "$COMPOSE_FILE" down -v --remove-orphans || true
  exit 1
}

trap 'fail "unexpected error (line $LINENO)"' ERR

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

CODE=$(curl -sf "$BASE_URL/debug/otp/latest?phone=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$PHONE")" | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["code"])')

TOKEN=$(curl -sf -X POST "$BASE_URL/auth/otp/verify" \
  -H 'Content-Type: application/json' \
  --data "{\"phone\":\"$PHONE\",\"code\":\"$CODE\"}" | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')

AUTHZ="Authorization: Bearer $TOKEN"

curl -sf -X POST "$BASE_URL/legal/offer/accept" -H "$AUTHZ" >/dev/null || fail "offer accept"

echo "[smoke] S3 put-test PDF"
RESP=$(curl -sf -X POST "$BASE_URL/debug/s3/put-test-pdf" -H "$AUTHZ")

DOWNLOAD_URL=$(python3 -c 'import sys,json; print(json.load(sys.stdin)["download_url"])' <<<"$RESP")

MAGIC=$(curl -sfL "$DOWNLOAD_URL" | head -c 4)
if [[ "$MAGIC" != "%PDF" ]]; then
  fail "downloaded content is not a PDF (magic=$MAGIC)"
fi

echo "[smoke] user library"
FILES_JSON=$(curl -sf "$BASE_URL/me/files" -H "$AUTHZ")
COUNT=$(python3 -c 'import sys,json; obj=json.load(sys.stdin); print(len(obj.get("files") or []))' <<<"$FILES_JSON")

if [[ "$COUNT" -lt 1 ]]; then
  fail "/me/files returned no files"
fi

echo "[smoke] teardown"
docker compose -f "$COMPOSE_FILE" down -v

echo "[smoke] OK"
