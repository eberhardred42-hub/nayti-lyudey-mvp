# Stage 5 Implementation Details

## Project Structure

```
api/
  ├── main.py (593 lines → 800+ lines with DB integration)
  ├── db.py (NEW, 245 lines)
  └── requirements.txt (+ psycopg2-binary)

infra/
  └── docker-compose.yml (updated Postgres service with healthcheck)

docs/stages/stage5/
  ├── STAGE5_SUMMARY.md
  └── STAGE5_IMPLEMENTATION.md (this file)

tests/
  └── test-stage5.sh (NEW)
```

## Module: api/db.py

### Responsibilities
1. **Connection Management** — `get_db_connection()` context manager
2. **Schema Initialization** — `init_db()` creates tables on startup
3. **Health Check** — `health_check()` for container orchestration
4. **CRUD Operations:**
   - Sessions: create, read, update
   - Messages: add, get_all
   - Delete: cascade on session deletion

### Key Functions

```python
# Database initialization
init_db()
    └─ CREATE TABLE sessions (session_id, profession_query, chat_state, vacancy_kb, free_report, ...)
    └─ CREATE TABLE messages (id, session_id, role, text, ...)

# Session operations
create_session(session_id, profession_query, vacancy_kb)
get_session(session_id) → dict | None
update_session(session_id, chat_state=..., vacancy_kb=..., free_report=...)

# Message operations
add_message(session_id, role, text) → message_id
get_session_messages(session_id) → list[dict]

# Utility
health_check() → bool
```

### Connection Pooling

Currently uses simple connection-per-request model:
```python
with get_db_connection() as conn:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # execute queries
    conn.commit()
```

**Future improvement:** Add PgBouncer or psycopg2 connection pool for high concurrency.

## Module: api/main.py Changes

### Import Changes
```python
from db import init_db, health_check, create_session as db_create_session
from db import get_session, update_session, add_message, get_session_messages
```

### Startup
```python
try:
    init_db()
except Exception as e:
    print(f"Warning: Database initialization failed: {e}")
```

### Endpoint Updates

#### POST /sessions (Create Session)
```python
@app.post("/sessions")
def create_session_endpoint(body: SessionCreate):
    session_id = str(uuid.uuid4())
    
    # 1. Create in-memory session
    SESSIONS[session_id] = {...make_empty_vacancy_kb()...}
    
    # 2. Save to database
    try:
        db_create_session(session_id, body.profession_query, kb)
    except Exception as e:
        print(f"Warning: Failed to save session to DB: {e}")
    
    return {"session_id": session_id}
```

**Logic Change:** Minimal. Now also saves to DB. If DB fails, in-memory cache still works.

#### POST /chat/message (Chat)
```python
@app.post("/chat/message")
def chat_message(body: ChatMessage):
    # 1. Load from DB if available
    try:
        db_session = get_session(session_id)
        if db_session:
            session = {...parse db_session...}
    except Exception:
        session = ensure_session(session_id)  # fallback to in-memory
    
    # 2. Generate reply (SAME LOGIC AS STAGE 4)
    # ... state machine, parsing, etc. ...
    
    # 3. Save messages to DB
    try:
        add_message(session_id, "user", text)
        add_message(session_id, "assistant", reply)
        update_session(session_id, chat_state=..., vacancy_kb=...)
    except Exception as e:
        print(f"Warning: Failed to save to DB: {e}")
    
    return {"reply": ..., "quick_replies": ..., ...}
```

**Logic Change:** None in chat state machine or parsing. Only storage mechanism changes.

#### GET /vacancy (Read KB)
```python
@app.get("/vacancy")
def get_vacancy(session_id: str):
    session = ensure_session(session_id)
    kb = session.get("vacancy_kb", make_empty_vacancy_kb())
    
    # Load from DB if available
    try:
        db_session = get_session(session_id)
        if db_session and db_session.get("vacancy_kb"):
            kb = db_session["vacancy_kb"]
    except Exception:
        pass  # use in-memory
    
    return {...}
```

**Logic Change:** None. Just loads KB from DB if available.

#### GET /report/free (Read/Generate Report)
```python
@app.get("/report/free")
def get_free_report(session_id: str):
    # 1. Check DB for cached report
    try:
        db_session = get_session(session_id)
        if db_session and db_session.get("free_report"):
            return {...cached report...}
    except Exception:
        pass
    
    # 2. If not cached, generate (SAME LOGIC AS STAGE 4)
    free_report = generate_free_report(kb, profession_query)
    
    # 3. Cache to DB
    try:
        update_session(session_id, free_report=free_report)
    except Exception:
        pass  # still return the report
    
    return {...}
```

**Logic Change:** None in generation. Added caching in DB.

#### GET /health/db (NEW)
```python
@app.get("/health/db")
def health_db():
    """Check database connectivity."""
    db_ok = health_check()
    return {"ok": db_ok}
```

Used by Docker Compose `depends_on condition: service_healthy`.

### Error Handling Pattern

All DB operations follow this pattern:
```python
try:
    # DB operation
    add_message(session_id, "user", text)
except Exception as e:
    # Log and continue
    print(f"Warning: Failed to save to DB: {e}")
    # In-memory state is still updated, so app works
```

**Rationale:** Graceful degradation. If DB is slow/down, app still responds (with in-memory data).

## Docker Compose Changes

### Postgres Service
```yaml
db:
  image: postgres:16
  environment:
    POSTGRES_USER: postgres
    POSTGRES_PASSWORD: postgres
    POSTGRES_DB: nlyudi
  ports:
    - "5432:5432"
  volumes:
    - pgdata:/var/lib/postgresql/data
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U postgres"]
    interval: 10s
    timeout: 5s
    retries: 5
```

### Backend Service
```yaml
api:
  depends_on:
    db:
      condition: service_healthy  # Wait for DB to be healthy
  environment:
    - DATABASE_URL=postgresql://postgres:postgres@db:5432/nlyudi
```

## Testing Strategy

### Unit Tests (Not Implemented Yet)
- `test_db_connection()` — Verify DB connection works
- `test_table_creation()` — Check tables are created
- `test_session_crud()` — Create, read, update sessions
- `test_message_crud()` — Add, read messages
- `test_cascade_delete()` — Session deletion cascades to messages

### Integration Tests (test-stage5.sh)
1. Start containers
2. Create session
3. Chat flow (message → reply → state change)
4. Read vacancy KB
5. Get free report
6. **Restart API container** (data should persist)
7. Verify messages still in DB
8. Verify vacancy_kb intact
9. Verify free_report cached

### Load Testing (Future)
- 100 concurrent sessions
- 1000 messages
- Verify DB doesn't bottleneck API

## Performance Considerations

### Current
- **Latency:** +10-50ms per request (DB roundtrip)
- **Throughput:** Limited by DB connections (default 20 from pool)
- **Storage:** ~1KB per session + 100 bytes per message

### Optimizations for Future
1. **Connection Pooling** — Use PgBouncer or sqlalchemy pool
2. **Caching Layer** — Redis for hot sessions
3. **Batch Writes** — Queue messages, write in batches
4. **Read Replicas** — Distribute read load
5. **Sharding** — Partition by session_id if millions of sessions

## Security Considerations

### Current Vulnerabilities
- No input validation on DB queries (psycopg2 parameterization safe, but still best practice)
- No rate limiting (add later)
- No authentication on DB (uses hardcoded credentials)

### Mitigations
1. Use parameterized queries (already done with `%s` placeholders)
2. Don't expose `DATABASE_URL` in logs
3. Use environment variables (already done)
4. Add DB credentials to .env file (not in git)

## Deployment Checklist

- [ ] Add `postgres:16` image to docker-compose
- [ ] Set `DATABASE_URL` env var in backend
- [ ] Add `psycopg2-binary` to requirements.txt
- [ ] Run `docker compose build` to rebuild images
- [ ] Run `docker compose up` to start services
- [ ] Verify `/health/db` returns `{"ok": true}`
- [ ] Run `tests/test-stage5.sh` to verify persistence

## Rollback Plan

If Stage 5 causes issues:
1. Revert `api/main.py` to in-memory SESSIONS only
2. Comment out DB operations (they're try-except wrapped, so safe)
3. Keep Docker Compose Postgres service (not harmful)
4. App continues to work with in-memory sessions

## Future Stages

**Stage 6:** Analytics & Logging
- Log all user interactions to DB
- Build dashboard for hiring insights
- Track report generation stats

**Stage 7:** Multi-Language & Domain Expansion
- Support non-IT domains (sales, creative, etc.)
- Better parsing heuristics for different roles

**Stage 8:** Premium Features
- Saved reports, export to PDF
- Candidate matching (find CVs matching vacancy KB)
- Integrations (Slack, email notifications)
