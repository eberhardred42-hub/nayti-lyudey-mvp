# Stage 3: Vacancy Knowledge Base (KB) Implementation

## Overview

Stage 3 adds a "Vacancy Knowledge Base" (KB) that progressively fills with information from user input during the chat. This KB captures structured data about job openings without relying on ML models, using simple heuristics and pattern matching.

## Changes Made

### 1. API Backend (`api/main.py`)

#### New Functions:

- **`make_empty_vacancy_kb()`** - Creates an empty KB with the following structure:
  - `role`: role_title, role_domain, role_seniority
  - `company`: company_location_city, company_location_region, work_format
  - `compensation`: salary_min_rub, salary_max_rub, salary_comment
  - `employment`: employment_type, schedule_comment
  - `requirements`: experience_years_min, education_level, hard_skills, soft_skills
  - `responsibilities`: tasks (list), raw_vacancy_text
  - `sourcing`: suggested_channels
  - `meta`: filled_fields_count, missing_fields, last_updated_iso

- **`compute_missing_fields(kb)`** - Identifies required fields that are still empty. MVP requires:
  - role_title OR tasks not empty
  - work_format
  - company_location_city OR company_location_region
  - employment_type
  - compensation (at least one of min/max/comment)

- **`update_meta(kb)`** - Updates metadata: filled fields count, missing fields, and last update timestamp

- **`parse_work_format(text)`** - Heuristic parser for work format:
  - "удал" / "remote" → `remote`
  - "гибрид" → `hybrid`
  - "офис" / "office" → `office`

- **`parse_employment_type(text)`** - Heuristic parser for employment type:
  - "фулл" / "full" → `full-time`
  - "парт" / "part" → `part-time`
  - "проект" / "project" → `project`

- **`parse_salary(text)`** - Extracts salary range from text:
  - Handles formats: "200к", "200 000", "200-300к", "150k-200k"
  - Returns (min_salary_rub, max_salary_rub, salary_comment)

- **`parse_location(text)`** - Simple city dictionary matching:
  - Recognizes: москва, спб, санкт-петербург, питер, екатеринбург, казань, новосибирск
  - Returns (city, region)

#### Modified Endpoints:

- **`POST /chat/message`** - Extended to progressively fill KB:
  - When vacancy text is submitted (>200 chars): extracts tasks, stores raw text
  - When tasks are submitted: parses into list
  - When clarifications submitted: parses location, work format, employment type, salary
  - Calls `update_meta()` after each update

- **`POST /sessions`** - Now initializes session with empty `vacancy_kb`

#### New Endpoints:

- **`GET /vacancy?session_id=...`** - Returns current KB state:
  ```json
  {
    "session_id": "...",
    "vacancy_kb": {...},
    "missing_fields": [...],
    "filled_fields_count": N
  }
  ```

### 2. Frontend Proxy (`front/src/app/api/vacancy/route.ts`)

New proxy route that forwards GET requests to the backend:
- Accepts `session_id` query parameter
- Returns parsed vacancy KB as JSON
- Handles errors gracefully

## Session Structure

Sessions now maintain:
```python
{
  "profession_query": str,
  "state": str,  # awaiting_flow, awaiting_vacancy_text, awaiting_tasks, awaiting_clarifications, free_ready
  "vacancy_text": str | None,
  "tasks": str | None,
  "clarifications": list[str],
  "vacancy_kb": dict,  # Main KB structure
}
```

## Testing

Two test files provided:

1. **`test-parsing.py`** - Tests parsing functions directly:
   ```bash
   python3 test-parsing.py
   ```

2. **`test-stage3.sh`** - End-to-end curl tests (requires running backend):
   ```bash
   bash test-stage3.sh
   ```

## Backward Compatibility

- All Stage 2 features preserved: `reply`, `quick_replies`, `should_show_free_result`
- State machine logic unchanged
- No new dependencies added
- `infra/docker-compose.yml` untouched

## KB Fill Flow Example

1. User starts: `state = "awaiting_flow"`
2. Chooses "Есть текст вакансии": `state = "awaiting_vacancy_text"`
3. Submits vacancy text (>200 chars):
   - KB: `responsibilities.raw_vacancy_text` = full text
   - KB: `responsibilities.tasks` = extracted tasks
   - `state = "awaiting_clarifications"`
4. Submits clarifications "Москва, гибридно, 200-300к, фулл тайм":
   - KB: `company.company_location_city` = "москва"
   - KB: `company.work_format` = "hybrid"
   - KB: `compensation.salary_min_rub` = 200000, `max_rub` = 300000
   - KB: `employment.employment_type` = "full-time"
   - `state = "free_ready"`
   - KB meta updated with filled count, missing fields, timestamp

## API Examples

### Create Session
```bash
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"profession_query": "Senior Engineer"}'
```

### Get Current KB
```bash
curl http://localhost:8000/vacancy?session_id=<uuid>
```

### Via Frontend Proxy
```bash
curl http://localhost:3000/api/vacancy?session_id=<uuid>
```

## Files Changed

- `api/main.py` - Added KB functions and extended /chat/message
- `front/src/app/api/vacancy/route.ts` - New proxy endpoint
- `test-parsing.py` - Unit tests for parsing functions
- `test-stage3.sh` - Integration test script

## Files Not Changed

- `infra/docker-compose.yml` (untouched)
- `api/Dockerfile` (untouched)
- `api/requirements.txt` (untouched - no new dependencies)
