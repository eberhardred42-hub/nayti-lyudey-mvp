#!/usr/bin/env bash
set -euo pipefail

DOMAIN_ARG="${1:-}"
DOMAIN_ENV="${DOMAIN:-}"
DOMAIN="${DOMAIN_ARG:-$DOMAIN_ENV}"

if [[ -z "$DOMAIN" ]]; then
  echo "Usage: DOMAIN=example.com $0  OR  $0 example.com" >&2
  exit 2
fi

API_BASE="https://api.${DOMAIN}"
USER_ID="staging-smoke-$(date +%s)"

WORKDIR="$(mktemp -d)"
cleanup() {
  rm -rf "$WORKDIR" >/dev/null 2>&1 || true
}

dump_logs() {
  echo ""
  echo "[smoke] --- docker logs (tail=300): api/worker/render ---" >&2

  if command -v docker >/dev/null 2>&1; then
    if [[ -f "deploy/staging/docker-compose.staging.yml" && -f "deploy/staging/.env.staging" ]]; then
      docker compose \
        --env-file deploy/staging/.env.staging \
        -f deploy/staging/docker-compose.staging.yml \
        logs --tail 300 api worker render >/dev/null 2>&1 || true
      docker compose \
        --env-file deploy/staging/.env.staging \
        -f deploy/staging/docker-compose.staging.yml \
        logs --tail 300 api worker render || true
      return 0
    fi

    # Fallback (if script is copied outside repo or compose files missing)
    docker compose logs --tail 300 api worker render >/dev/null 2>&1 || true
    docker compose logs --tail 300 api worker render || true
  fi
}

on_exit() {
  rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "[smoke] FAIL (rc=$rc)" >&2
    dump_logs
  else
    echo "[smoke] OK"
  fi
  cleanup
  exit $rc
}
trap on_exit EXIT

step() {
  echo "[smoke] $*"
}

json_get() {
  # Usage: echo '{...}' | json_get 'obj["key"]'
  python3 -c "import sys,json; obj=json.load(sys.stdin); print(${1})"
}

curl_json() {
  curl --show-error --silent --fail "$@"
}

step "health: ${API_BASE}/health"
curl -fsS "${API_BASE}/health" >/dev/null

step "create session"
SESSION_JSON="$(curl_json -X POST "${API_BASE}/sessions" \
  -H 'Content-Type: application/json' \
  -H "X-User-Id: ${USER_ID}" \
  --data '{"profession_query":"Staging smoke"}')"
SESSION_ID="$(printf '%s' "$SESSION_JSON" | json_get 'obj.get("session_id", "")')"
if [[ -z "$SESSION_ID" ]]; then
  echo "[smoke] session_id missing" >&2
  exit 1
fi
step "session_id=${SESSION_ID}"

step "chat flow (minimal)"
# Start
curl_json -X POST "${API_BASE}/chat/message" \
  -H 'Content-Type: application/json' \
  -H "X-User-Id: ${USER_ID}" \
  --data "{\"session_id\":\"${SESSION_ID}\",\"type\":\"start\"}" >/dev/null
# One user message
curl_json -X POST "${API_BASE}/chat/message" \
  -H 'Content-Type: application/json' \
  -H "X-User-Id: ${USER_ID}" \
  --data "{\"session_id\":\"${SESSION_ID}\",\"type\":\"message\",\"text\":\"Нет вакансии, есть задачи\"}" >/dev/null

step "accept offer (required for pack/render)"
curl_json -X POST "${API_BASE}/legal/offer/accept" \
  -H "X-User-Id: ${USER_ID}" >/dev/null

step "create pack via /ml/job"
PACK_JSON="$(curl_json -X POST "${API_BASE}/ml/job" \
  -H 'Content-Type: application/json' \
  -H "X-User-Id: ${USER_ID}" \
  --data "{\"session_id\":\"${SESSION_ID}\"}")"
PACK_ID="$(printf '%s' "$PACK_JSON" | json_get 'obj.get("pack_id", "")')"
if [[ -z "$PACK_ID" ]]; then
  echo "[smoke] pack_id missing" >&2
  exit 1
fi
step "pack_id=${PACK_ID}"

step "trigger render for pack"
curl_json -X POST "${API_BASE}/packs/${PACK_ID}/render" \
  -H "X-User-Id: ${USER_ID}" >/dev/null

step "wait for a ready document"
READY_FILE_ID=""
for i in $(seq 1 90); do
  DOCS_JSON="$(curl_json "${API_BASE}/packs/${PACK_ID}/documents" -H "X-User-Id: ${USER_ID}")"
  READY_FILE_ID="$(printf '%s' "$DOCS_JSON" | python3 -c 'import sys,json; obj=json.load(sys.stdin); docs=obj.get("documents") or []; print(next((d.get("file_id") for d in docs if d.get("status")=="ready" and d.get("file_id")), ""))')"
  if [[ -n "$READY_FILE_ID" ]]; then
    break
  fi
  sleep 2
  if [[ $i -eq 90 ]]; then
    echo "[smoke] no ready document after waiting" >&2
    exit 1
  fi
done
step "ready_file_id=${READY_FILE_ID}"

step "download PDF via presigned URL and verify magic %PDF"
DL_JSON="$(curl_json "${API_BASE}/files/${READY_FILE_ID}/download" -H "X-User-Id: ${USER_ID}")"
DOWNLOAD_URL="$(printf '%s' "$DL_JSON" | json_get 'obj.get("url", "")')"
if [[ -z "${DOWNLOAD_URL:-}" ]]; then
  echo "[smoke] download URL missing" >&2
  exit 1
fi

# Avoid full download: fetch first bytes and check PDF magic.
PDF_HEAD_FILE="${WORKDIR}/pdf_head.bin"
curl -fsSL --range 0-15 "$DOWNLOAD_URL" -o "$PDF_HEAD_FILE"
MAGIC="$(head -c 4 "$PDF_HEAD_FILE" || true)"
if [[ "$MAGIC" != "%PDF" ]]; then
  echo "[smoke] downloaded content is not a PDF (magic=$MAGIC)" >&2
  exit 1
fi

step "PDF magic OK"
