#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8100}"
ROLE_QUERY="${ROLE_QUERY:-Маркетолог}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required" >&2
  exit 1
fi

post_json() {
  local url="$1"
  local body="$2"
  curl -sS -H 'Content-Type: application/json' -X POST "${url}" -d "${body}"
}

get_field_py='import json,sys
obj=json.loads(sys.stdin.read() or "{}")
# prefer assistant_text, then reply
val=obj.get("assistant_text") or obj.get("reply") or ""
print(val if isinstance(val,str) else "")'

get_llm_used_py='import json,sys
obj=json.loads(sys.stdin.read() or "{}")
v=obj.get("llm_used")
print("true" if v is True else "false")'

# 1) Create session
sess_json=$(post_json "${BASE_URL}/sessions" "{\"profession_query\": \"${ROLE_QUERY}\", \"flow\": \"intro\", \"entry_mode\": \"C\"}")
session_id=$(python3 - <<PY
import json,sys
obj=json.loads('''${sess_json}''')
print(obj.get('session_id',''))
PY
)

if [[ -z "${session_id}" ]]; then
  echo "Failed to create session. Response: ${sess_json}" >&2
  exit 1
fi

echo "session_id=${session_id}" >&2

# 2) Start
start_json=$(post_json "${BASE_URL}/chat/message" "{\"session_id\": \"${session_id}\", \"type\": \"intro_start\", \"profession_query\": \"${ROLE_QUERY}\"}")
# We don't assert on start response.

# 3) Select mode string (questions)
step3_json=$(post_json "${BASE_URL}/chat/message" "{\"session_id\": \"${session_id}\", \"type\": \"intro_message\", \"text\": \"Нет текста — отвечу на вопросы\"}")
q1=$(printf '%s' "${step3_json}" | python3 -c "${get_field_py}")
llm_used_1=$(printf '%s' "${step3_json}" | python3 -c "${get_llm_used_py}")

if [[ ${#q1} -lt 10 ]]; then
  echo "Expected non-empty assistant_text/reply (>=10 chars). Got: '${q1}'. Full JSON: ${step3_json}" >&2
  exit 1
fi

if [[ "${llm_used_1}" != "true" ]]; then
  echo "LLM was not used (llm_used=false). Likely missing LLM config (DEV_LLM_* or local LLM_*)." >&2
  echo "Full JSON: ${step3_json}" >&2
  exit 2
fi

echo "Q1: ${q1}" >&2

# 4) Answer anything
step4_json=$(post_json "${BASE_URL}/chat/message" "{\"session_id\": \"${session_id}\", \"type\": \"intro_message\", \"text\": \"Бюджет до 150k\"}")
q2=$(printf '%s' "${step4_json}" | python3 -c "${get_field_py}")
llm_used_2=$(printf '%s' "${step4_json}" | python3 -c "${get_llm_used_py}")

if [[ ${#q2} -lt 10 ]]; then
  echo "Expected non-empty assistant_text/reply (>=10 chars) on step 4. Got: '${q2}'. Full JSON: ${step4_json}" >&2
  exit 1
fi

if [[ "${llm_used_2}" != "true" ]]; then
  echo "LLM was not used on step 4 (llm_used=false)." >&2
  echo "Full JSON: ${step4_json}" >&2
  exit 2
fi

if [[ "${q2}" == "${q1}" ]]; then
  echo "Expected second question to differ from first. q1 == q2 == '${q1}'" >&2
  exit 1
fi

echo "Q2: ${q2}" >&2
echo "ok"