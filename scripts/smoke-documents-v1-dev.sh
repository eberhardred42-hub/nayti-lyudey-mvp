#!/usr/bin/env bash
set -euo pipefail

# Smoke for an already deployed DEV environment.
# Uses header-based auth (X-User-Id) and hits backend via Caddy /api/* routing.

BASE_URL=${BASE_URL:-"https://dev.naitilyudei.ru/api"}

fail() {
  echo "[smoke-docs-dev] FAIL: $*" >&2
  exit 1
}

curl_json() {
  curl --show-error --silent --fail "$@"
}

py_get() {
  python3 -c "import sys,json; obj=json.load(sys.stdin); $1"
}

echo "[smoke-docs-dev] base: $BASE_URL"

USER_ID="smoke-dev-$(date +%s)"
HDR_USER=("-H" "X-User-Id: $USER_ID")

TMP_PDF=$(mktemp)
trap 'rm -f "$TMP_PDF" || true' EXIT

echo "[smoke-docs-dev] health"
curl -sf "${BASE_URL%/}/health" >/dev/null || fail "health"

echo "[smoke-docs-dev] create session"
SESSION_ID=$(curl_json -X POST "${BASE_URL%/}/sessions" \
  "${HDR_USER[@]}" \
  -H 'Content-Type: application/json' \
  --data '{"profession_query":"QA инженер","flow":"intro"}' | \
  py_get 'print(obj.get("session_id") or "")')

if [[ -z "$SESSION_ID" ]]; then
  fail "no session_id"
fi

echo "[smoke-docs-dev] intro_start"
curl_json -X POST "${BASE_URL%/}/chat/message" \
  "${HDR_USER[@]}" \
  -H 'Content-Type: application/json' \
  --data "{\"session_id\":\"$SESSION_ID\",\"type\":\"intro_start\"}" >/dev/null || fail "intro_start"

intro_msg() {
  local text="$1"
  curl_json -X POST "${BASE_URL%/}/chat/message" \
    "${HDR_USER[@]}" \
    -H 'Content-Type: application/json' \
    --data "{\"session_id\":\"$SESSION_ID\",\"type\":\"intro_message\",\"text\":$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$text")}" \
    | cat
}

RESP=$(intro_msg "Ищем Senior QA инженера") || fail "intro role"
READY=$(py_get 'print(str(obj.get("ready_to_search") or False).lower())' <<<"$RESP")

RESP=$(intro_msg "B — своими словами") || fail "intro mode"
READY=$(py_get 'print(str(obj.get("ready_to_search") or False).lower())' <<<"$RESP")

RESP=$(intro_msg "Senior QA инженер; удалённо; полный день; бюджет 250к") || fail "intro details"
READY=$(py_get 'print(str(obj.get("ready_to_search") or False).lower())' <<<"$RESP")

RESP=$(intro_msg "Да, всё верно") || fail "intro confirm"
READY=$(py_get 'print(str(obj.get("ready_to_search") or False).lower())' <<<"$RESP")

if [[ "$READY" != "true" ]]; then
  fail "intro did not reach ready_to_search"
fi

echo "[smoke-docs-dev] generate_pack"
GEN=$(curl_json -X POST "${BASE_URL%/}/documents/generate_pack" \
  "${HDR_USER[@]}" \
  -H 'Content-Type: application/json' \
  --data "{\"session_id\":\"$SESSION_ID\"}") || fail "documents/generate_pack"

DOC_ID=$(python3 -c 'import sys,json; obj=json.load(sys.stdin); res=obj.get("results") or []; print(next(((r.get("artifact_id") or "") for r in res if (r.get("doc_id") or "")=="candidate_onepager"), ""))' <<<"$GEN")
STATUS=$(python3 -c 'import sys,json; obj=json.load(sys.stdin); res=obj.get("results") or []; print(next(((r.get("status") or "") for r in res if (r.get("doc_id") or "")=="candidate_onepager"), ""))' <<<"$GEN")

if [[ -z "$DOC_ID" ]]; then
  fail "no document id"
fi
if [[ "$STATUS" == "failed" ]]; then
  fail "candidate_onepager failed"
fi

echo "[smoke-docs-dev] download pdf"
curl -sf "${BASE_URL%/}/documents/$DOC_ID/download" "${HDR_USER[@]}" -o "$TMP_PDF" || fail "download"
MAGIC=$(head -c 4 "$TMP_PDF")
if [[ "$MAGIC" != "%PDF" ]]; then
  fail "not a PDF (magic=$MAGIC)"
fi

echo "[smoke-docs-dev] list me/documents"
ME=$(curl_json "${BASE_URL%/}/me/documents" "${HDR_USER[@]}") || fail "me/documents"
FOUND=$(python3 -c 'import sys,json; obj=json.load(sys.stdin); doc_id=sys.argv[1]; docs=(obj.get("documents") or []); print("true" if any((d.get("type")=="pdf" and str(d.get("id"))==doc_id) for d in docs) else "false")' "$DOC_ID" <<<"$ME")
if [[ "$FOUND" != "true" ]]; then
  fail "generated document not found in /me/documents"
fi

echo "[smoke-docs-dev] OK"
