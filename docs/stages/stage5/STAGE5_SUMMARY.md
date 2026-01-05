# Stage 5: Postgres Persistence for Sessions/Messages/KB/Reports

## Overview

Stage 5 adds persistent storage using PostgreSQL to replace the in-memory `SESSIONS` dictionary. All user sessions, chat messages, vacancy knowledge bases, and cached free reports are now persisted to the database.

**Goal:** Ensure data survives API container restarts and enable multi-instance deployments.

## Architecture Changes

### New Components

1. **api/db.py** — Database abstraction layer
   - Connection management (context manager)
   - Schema initialization (tables: `sessions`, `messages`)
   - CRUD operations (no ORM, pure SQL + psycopg2)

2. **Postgres Service** in `infra/docker-compose.yml`
   - Image: postgres:16
   - Volume: `pgdata:/var/lib/postgresql/data` (persistent)
   - Healthcheck: pg_isready
   - Environment: POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

3. **Backend Updates** in `api/main.py`
   - Hybrid mode: in-memory cache + database persistence
   - All endpoints save to DB on state changes
   - `/health/db` endpoint for DB connectivity check

### Database Schema

#### `sessions` Table
```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    profession_query TEXT NOT NULL,
    chat_state TEXT,
    vacancy_kb JSONB,
    free_report JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
)
```

#### `messages` Table
```sql
CREATE TABLE messages (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
)
```

## API Endpoints (Updated)

### POST /sessions
- Creates new session in-memory and database
- Returns `session_id`

### POST /chat/message
- Reads session from DB (if available)
- Saves user message to DB
- Generates reply (same logic as Stage 4)
- Saves assistant reply to DB
- Updates `chat_state` and `vacancy_kb` in DB

### GET /vacancy
- Loads vacancy_kb from database (or in-memory fallback)
- Returns vacancy knowledge base + meta

### GET /report/free
- Checks DB for cached `free_report`
- If cached, returns immediately
- Otherwise generates, caches to DB, and returns

### GET /health/db *(New)*
- Returns `{"ok": true}` if DB is accessible
- Used for container orchestration healthchecks

## Implementation Details

### Hybrid In-Memory + Database Mode

**Why hybrid?**
- In-memory caching reduces DB queries
- Database persistence ensures durability
- Graceful degradation if DB is temporarily unavailable

**Flow:**
1. Request comes in → check in-memory SESSIONS
2. If not in memory, load from DB
3. Update both in-memory and DB
4. On error, fall back to in-memory (app still works)

### Failover Behavior

```python
# Example: loading session from DB
try:
    db_session = get_session(session_id)
    if db_session:
        session = {...parse db_session...}
except Exception as e:
    # Fall back to in-memory
    session = ensure_session(session_id)
```

### Error Handling

All DB operations are wrapped in try-except blocks. If DB write fails:
- Warning is logged
- In-memory state is still updated
- Request continues normally
- Data is not lost (in-memory is there as fallback)

## Dependencies

- **psycopg2-binary 2.9.9** — PostgreSQL driver for Python
  - Binary distribution (no compilation needed)
  - Minimal and well-tested

## Testing

Run `bash tests/test-stage5.sh` to:
1. Start docker containers (db + api + front + ml)
2. Create a session
3. Run through full chat flow (starts → vacancy text → clarifications)
4. Query `/vacancy` and `/report/free`
5. Restart API container
6. Verify data persists (messages, vacancy_kb, free_report still present)

**Expected result:** All data survives container restart.

## Backward Compatibility

- Frontend unchanged (same `/sessions`, `/chat/message`, `/vacancy`, `/report/free` contracts)
- Chat logic unchanged (only storage mechanism)
- All existing endpoints return same JSON structure
- In-memory mode still works if DB is down

## Known Limitations

- No message streaming (all at once)
- No concurrent session editing (single API instance assumed for now)
- No cleanup of old sessions (consider adding a retention policy later)
- JSONB queries not indexed (add index if sessions get very large)

## Future Improvements

1. Add database indexes for common queries
2. Implement session cleanup (e.g., delete sessions older than 30 days)
3. Add audit logging (who queried what, when)
4. Support multi-replica deployments with read replicas
5. Add database backup strategy

## Files Changed

- ✅ `infra/docker-compose.yml` — Added Postgres service + healthcheck
- ✅ `api/db.py` — New database module
- ✅ `api/main.py` — Updated all endpoints for database persistence
- ✅ `api/requirements.txt` — Added psycopg2-binary
- 🚫 `front/` — No changes
- 🚫 `ml/` — No changes
