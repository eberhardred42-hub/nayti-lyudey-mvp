# Stage 4: Free Report Generation

## Overview

Stage 4 adds intelligent free report generation from the Vacancy Knowledge Base (created in Stage 3). The free report provides actionable hiring guidance without ML, using domain detection and simple heuristics.

## What is Free Report?

A free report is a structured JSON document that contains hiring recommendations based on:
- The job role and domain (IT, Creative, Sales, etc.)
- Candidate search channels (HH, LinkedIn, specialized communities)
- Screening criteria tailored to the role
- Budget reality checks and scaling strategies
- Step-by-step hiring process guide

The report is generated instantly (no backend processing needed) and cached in the session.

## Inputs from Vacancy KB

The report generator reads from the vacancy KB (from Stage 3):

```
vacancy_kb structure:
├── role
│   ├── role_title: string (e.g., "Senior Engineer")
│   ├── role_domain: string (inferred from role_title or tasks)
│   └── role_seniority: string
├── company
│   ├── company_location_city: string (e.g., "москва")
│   ├── company_location_region: string
│   └── work_format: string (office|hybrid|remote|unknown)
├── compensation
│   ├── salary_min_rub: int (e.g., 200000)
│   ├── salary_max_rub: int (e.g., 300000)
│   └── salary_comment: string
├── employment
│   ├── employment_type: string (full-time|part-time|project|unknown)
│   └── schedule_comment: string
├── responsibilities
│   ├── tasks: list[string]
│   └── raw_vacancy_text: string (full vacancy text if provided)
└── meta
    ├── filled_fields_count: int
    └── missing_fields: list[string]
```

## Report Structure

### Response JSON Format

```json
{
  "session_id": "uuid",
  "free_report": {
    "headline": "string (greeting + role context)",
    "where_to_search": [
      {
        "title": "string (section name)",
        "bullets": ["string", "string", ...]
      }
    ],
    "what_to_screen": ["string", "string", ...],
    "budget_reality_check": {
      "status": "ok|low|high|unknown",
      "bullets": ["string", ...]
    },
    "next_steps": ["string", ...]
  },
  "generated_at_iso": "2026-01-05T12:34:56Z",
  "kb_meta": {
    "missing_fields": ["role.title", ...],
    "filled_fields_count": 8
  }
}
```

### Section Details

#### 1. Headline
- **Purpose**: Warm, encouraging greeting personalized to the role
- **Logic**: "Держи бесплатный результат поиска" + role_title/role_domain + emoji
- **Example**: "Держи бесплатный результат поиска по Senior Engineer 🎯"

#### 2. Where to Search
- **Purpose**: Platform recommendations based on domain, location, format
- **Always Included**: HeadHunter (HH) as baseline + LinkedIn
- **Domain-Specific Detection**:
  - **IT** (keywords: python, java, golang, разработка, backend, frontend):
    - Habr Career
    - Telegram IT-чаты
    - GitHub (для поиска по профилям)
  - **Creative** (keywords: дизайн, маркетинг, реклама, контент):
    - Behance, Dribbble
    - Telegram творческих сообществ
    - TikTok/YouTube (for content creators)
  - **Sales** (keywords: продажа, sales, менеджер, бизнес-развитие):
    - LinkedIn (networking)
    - Telegram бизнес-сообществ
    - Рефералы
- **Location-Aware**: If office/hybrid + city → add local Telegram/VK channels
- **Fallback**: If no domain detected → general list with recs and referrals

#### 3. What to Screen
- **Purpose**: Screening criteria for reviewing candidates
- **Universal Criteria** (always included):
  - Резюме/портфолио: актуальность, ясность стека
  - Примеры работ/кейсы: релевантность к задачам
  - Мягкие навыки: общительность, ответственность
  - Понимание твоих задач
  - Honesty red flags
  - Этика найма
- **Domain-Specific Additions**:
  - **IT**: Knowledge of tools/stack, pet projects
  - **Creative**: Sense of style, process explanation
  - **Sales**: Track record (numbers), energy, ambition
- **Total**: 6-10 points depending on domain

#### 4. Budget Reality Check
- **Purpose**: Salary strategy and scaling options
- **If salary provided**: Shows budget + strategies for scaling
  - "Если бюджет ниже—рассмотри джуна с потенциалом"
  - "Опцион: наставничество может быть экономичнее"
  - "Не боись тестового задания"
- **If budget unknown**: Recommends market research + testing
- **Status**: Always "unknown" (conservative approach)

#### 5. Next Steps
- **Purpose**: Actionable hiring process guide
- **Always Included**:
  1. Формирование вакансии: ясные требования, стек, условия
  2. Выбор каналов: начни с 2–3 основных
  3. Быстрый скрининг резюме: "может ли он/она это делать?"
  4. Первое интервью
  5. Тестовое задание (if appropriate)
- **Conditional**: Add office/equipment note if office/hybrid

## Heuristics and Domain Detection

### Work Format Awareness
- **Remote**: Focus on online platforms (HH, LinkedIn, GitHub)
- **Hybrid/Office + city**: Add local channels (Telegram, VK, Avito)
- **Unknown**: Default to online-first approach

### Domain Detection Algorithm

Domain detection scans:
1. `role_title` (if set)
2. `role_domain` (if set)
3. `raw_vacancy_text` for keywords
4. `profession_query` from session

**Keywords**:
- **IT**: python, java, golang, программ, разработ, backend, frontend, react, node, devops, kubernetes, docker, database, sql
- **Creative**: дизайн, маркетинг, реклам, контент, visual, design, graphics, ui, ux, figma, adobe
- **Sales**: продажа, sales, менеджер, бизнес-развитие, business development, account manager, key account

If multiple domains detected → use first match (order: IT > Creative > Sales)

## Caching Strategy

### Session Storage

The free report is cached in the session after generation:

```python
session["free_report"] = report_dict
session["free_report_generated_at"] = "2026-01-05T12:34:56Z"
```

### Benefits
- Avoid regenerating on repeated requests
- Fast response time for frontend
- Includes generation timestamp for transparency

### Cache Lifetime
- Duration of session (session is in-memory)
- Cache is optional optimization (endpoint can always regenerate)

## Backend Implementation

### Function: `generate_free_report(vacancy_kb, profession_query="")`

**Parameters**:
- `vacancy_kb`: dict (from session)
- `profession_query`: string (user's search term, for context)

**Returns**:
- dict with structure defined above

**Processing**:
1. Extract data from KB (title, domain, format, location, salary, tasks)
2. Convert text to lowercase for case-insensitive keyword matching
3. Detect domain from keywords
4. Generate headline (greeting + role + emoji)
5. Build where_to_search based on domain + location
6. Build what_to_screen (universal + domain-specific)
7. Build budget_reality_check (if salary info) or strategy bullets
8. Build next_steps (5-6 standard + conditional additions)
9. Return structured report

### Endpoint: `GET /report/free?session_id=...`

**Handler**: `get_free_report(session_id: str)`

**Logic**:
1. Ensure session exists (create empty if needed)
2. Get KB from session
3. Call `generate_free_report(kb, profession_query)`
4. Cache result in session
5. Return response with report + metadata

**Error Handling**:
- Invalid session_id: Create new session with empty KB
- Missing KB: Use empty KB (generate generic report)
- No errors thrown (always return valid report)

## Frontend Implementation

### Proxy Route: `GET /api/report/free?session_id=...`

**File**: `front/src/app/api/report/free/route.ts`

**Logic**:
1. Validate session_id parameter (400 if missing)
2. Forward GET to `${BACKEND_URL}/report/free?session_id=...`
3. Return JSON response (status matched from backend)
4. Catch errors → return 500 with error message

### UI Rendering

**Trigger**: When `should_show_free_result=true` from chat endpoint

**Flow**:
1. User completes chat flow
2. Backend responds with `should_show_free_result=true`
3. Frontend calls `fetchFreeReport(sessionId)`
4. Show loading state: "⏳ Загружаю отчёт..."
5. On success: Render full report (5 sections)
6. On error: Show "⚠️ Не удалось загрузить, попробуй обновить"

**Rendering Details**:

```
Headline: <h3>{report.headline}</h3>

Where to Search:
  for each section in where_to_search:
    <div><b>{section.title}</b></div>
    <ul>
      {section.bullets}
    </ul>

What to Screen:
  <ul>{what_to_screen items}</ul>

Budget Reality Check:
  <div>Status: {status}</div>
  <ul>{bullets}</ul>

Next Steps:
  <ol>{numbered steps}</ol>
```

### Error Handling
- Network error → Show fallback message
- Empty report → Show fallback message
- UI doesn't crash on missing fields

## Data Flow Diagram

```
User starts chat
    ↓
User chooses "Есть текст вакансии" or "Нет вакансии, есть задачи"
    ↓
Chat flow (Stage 2) updates session state
    ↓
Vacancy KB progressively fills (Stage 3)
    ↓
User provides clarifications
    ↓
Backend returns should_show_free_result=true
    ↓
Frontend detects should_show_free_result=true
    ↓
Frontend calls GET /api/report/free?session_id=...
    ↓
Proxy forwards to backend GET /report/free?session_id=...
    ↓
Backend extracts KB from session
    ↓
generate_free_report(kb, profession_query)
    ↓
Report is cached in session
    ↓
Frontend receives structured JSON
    ↓
Frontend renders 5 sections
    ↓
User sees actionable recommendations
```

## Testing

### Unit Tests (test-free-report.py)
- Validates report structure (5 required sections)
- Checks non-empty headlines
- Verifies where_to_search not empty
- Confirms budget_reality_check.status is valid
- Tests with various KB states

### Integration Tests (test-stage4.sh)
- Creates session
- Sends chat messages
- Calls GET /report/free
- Validates JSON keys using grep

### Manual Verification

See [STAGE4_SUMMARY.md](STAGE4_SUMMARY.md) and [RUNBOOK.md](RUNBOOK.md).

## No New Dependencies

- Report generation uses only Python stdlib (re, datetime)
- Frontend proxy uses only Next.js built-ins
- Tests use only bash + grep (no jq or external tools)

## Backward Compatibility

- Stage 2 chat flow: Unchanged
- Stage 3 KB: Fully compatible
- Existing endpoints: Still working
- Session structure: Extended (new fields: free_report, free_report_generated_at)

## What's Not Included

- ML/NLP for domain detection (using keyword matching instead)
- Paid/premium report features (Stage 4.2+)
- Report PDF generation (future feature)
- Report history/archiving (session-only for now)
