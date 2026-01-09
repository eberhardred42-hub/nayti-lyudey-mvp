#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="infra/docker-compose.yml"
API_URL="http://localhost:8000"
FRONT_URL="http://localhost:3000"

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

# LLM mode:
# - If caller provided any API key and did not force LLM_PROVIDER, use openai_compat.
# - Otherwise default to mock to keep smoke reliable/offline.
if [[ -z "${LLM_PROVIDER:-}" ]]; then
  if [[ -n "${OPENAI_API_KEY:-}" || -n "${LLM_API_KEY:-}" ]]; then
    export LLM_PROVIDER=openai_compat
  else
    export LLM_PROVIDER=mock
  fi
fi

export LLM_BASE_URL=${LLM_BASE_URL:-}
export LLM_API_KEY=${LLM_API_KEY:-}
export OPENAI_API_KEY=${OPENAI_API_KEY:-}
export OPENAI_API_KEY=${OPENAI_API_KEY:-}

TMP_PDF=""

fail() {
  echo "[smoke-docs] FAIL: $*" >&2
  echo "[smoke-docs] logs (tail=200):" >&2
  docker compose -f "$COMPOSE_FILE" logs --tail=200 api render render-worker front redis db minio || true
  if [[ -n "${TMP_PDF:-}" ]]; then
    rm -f "$TMP_PDF" || true
  fi
  echo "[smoke-docs] teardown (failure)" >&2
  docker compose -f "$COMPOSE_FILE" down -v --remove-orphans || true
  exit 1
}

trap 'fail "unexpected error (line $LINENO)"' ERR

curl_json() {
  curl --show-error --silent --fail "$@"
}

py_get() {
  python3 -c "import sys,json; obj=json.load(sys.stdin); $1"
}

echo "[smoke-docs] docker compose up -d --build"
docker compose -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
docker compose -f "$COMPOSE_FILE" up -d --build

echo "[smoke-docs] waiting for API health..."
for i in $(seq 1 60); do
  if curl -sf "$API_URL/health" >/dev/null; then
    break
  fi
  sleep 1
  if [[ $i -eq 60 ]]; then
    fail "API did not become ready"
  fi
done

curl -sf "$API_URL/health" >/dev/null || fail "/health"
curl -sf "$API_URL/health/db" >/dev/null || fail "/health/db"
curl -sf "$API_URL/health/s3" >/dev/null || fail "/health/s3"

echo "[smoke-docs] waiting for Front..."
for i in $(seq 1 90); do
  if curl -sf "$FRONT_URL" >/dev/null; then
    break
  fi
  sleep 1
  if [[ $i -eq 90 ]]; then
    fail "Front did not become ready"
  fi
done

USER_ID="smoke-user-$(date +%s)"
HDR_USER=("-H" "X-User-Id: $USER_ID")

echo "[smoke-docs] create session via front proxy"
SESSION_ID=$(curl_json -X POST "$FRONT_URL/api/sessions" \
  "${HDR_USER[@]}" \
  -H 'Content-Type: application/json' \
  --data '{"profession_query":"QA инженер","flow":"intro"}' | \
  py_get 'print(obj.get("session_id") or "")')

if [[ -z "$SESSION_ID" ]]; then
  fail "no session_id"
fi

echo "[smoke-docs] intro_start"
curl_json -X POST "$FRONT_URL/api/chat/message" \
  "${HDR_USER[@]}" \
  -H 'Content-Type: application/json' \
  --data "{\"session_id\":\"$SESSION_ID\",\"type\":\"intro_start\"}" >/dev/null || fail "intro_start"

intro_msg() {
  local text="$1"
  curl_json -X POST "$FRONT_URL/api/chat/message" \
    "${HDR_USER[@]}" \
    -H 'Content-Type: application/json' \
    --data "{\"session_id\":\"$SESSION_ID\",\"type\":\"intro_message\",\"text\":$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$text")}" \
    | cat
}

READY="false"

# Choose mode B (no vacancy text) and provide combined info.
RESP=$(intro_msg "B — своими словами") || fail "intro mode"
READY=$(py_get 'print(str(obj.get("ready_to_search") or False).lower())' <<<"$RESP")

RESP=$(intro_msg "Senior QA инженер; удалённо; полный день; бюджет 250к") || fail "intro details"
READY=$(py_get 'print(str(obj.get("ready_to_search") or False).lower())' <<<"$RESP")

RESP=$(intro_msg "Да, всё верно") || fail "intro confirm"
READY=$(py_get 'print(str(obj.get("ready_to_search") or False).lower())' <<<"$RESP")

if [[ "$READY" != "true" ]]; then
  fail "intro did not reach ready_to_search"
fi

echo "[smoke-docs] generate_pack via front proxy"
GEN=$(curl_json -X POST "$FRONT_URL/api/documents/generate_pack" \
  "${HDR_USER[@]}" \
  -H 'Content-Type: application/json' \
  --data "{\"session_id\":\"$SESSION_ID\"}") || fail "documents/generate_pack"

DOC_ID=$(python3 -c 'import sys,json; obj=json.load(sys.stdin); res=obj.get("results") or []; print(next(((r.get("artifact_id") or "") for r in res if (r.get("doc_id") or "")=="candidate_onepager"), ""))' <<<"$GEN")
STATUS=$(python3 -c 'import sys,json; obj=json.load(sys.stdin); res=obj.get("results") or []; print(next(((r.get("status") or "") for r in res if (r.get("doc_id") or "")=="candidate_onepager"), ""))' <<<"$GEN")

if [[ -z "$DOC_ID" ]]; then
  fail "no document id in generate_pack response"
fi
if [[ "$STATUS" == "failed" ]]; then
  fail "candidate_onepager failed"
fi

echo "[smoke-docs] download PDF via front proxy"
TMP_PDF=$(mktemp)
curl -sf "$FRONT_URL/api/documents/$DOC_ID/download" "${HDR_USER[@]}" -o "$TMP_PDF" || fail "download pdf"
MAGIC=$(head -c 4 "$TMP_PDF")
if [[ "$MAGIC" != "%PDF" ]]; then
  fail "downloaded content is not a PDF (magic=$MAGIC)"
fi

echo "[smoke-docs] list /me/documents via front proxy"
ME=$(curl_json "$FRONT_URL/api/me/documents" "${HDR_USER[@]}") || fail "me/documents"
FOUND=$(python3 -c 'import sys,json; obj=json.load(sys.stdin); doc_id=sys.argv[1]; docs=(obj.get("documents") or []); print("true" if any((d.get("type")=="pdf" and str(d.get("id"))==doc_id) for d in docs) else "false")' "$DOC_ID" <<<"$ME")
if [[ "$FOUND" != "true" ]]; then
  fail "generated document not found in /me/documents"
fi

echo "[smoke-docs] teardown"
rm -f "$TMP_PDF" || true
docker compose -f "$COMPOSE_FILE" down -v

echo "[smoke-docs] OK"
