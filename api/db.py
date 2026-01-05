"""
Database module for Nayti-Lyudey MVP.

Manages persistent storage for:
- sessions (profession query, chat state, vacancy KB, free report)
- messages (user/assistant conversation history)

Uses psycopg2 for PostgreSQL connection (no ORM).
"""

import os
import json
import time
from datetime import datetime
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Union

JsonType = Union[Dict[str, Any], List[Any]]


def safe_json(value: Any, default: JsonType) -> JsonType:
    """Decode JSON from DB safely, tolerating NULL/blank/invalid."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return default
    return default


def _log_event(event: str, level: str = "info", **fields):
    payload = {
        "event": event,
        "level": level,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, datetime):
            payload[key] = value.isoformat()
        else:
            payload[key] = value
    print(json.dumps(payload, ensure_ascii=False))

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/nlyudi"
)


@contextmanager
def get_db_connection():
    """Context manager for database connections."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize database schema on startup."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        # Create sessions table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                profession_query TEXT NOT NULL,
                chat_state TEXT,
                vacancy_kb JSONB NOT NULL DEFAULT '{}'::jsonb,
                free_report JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        
        # Create messages table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id BIGSERIAL PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                text TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        
        # Create index on session_id for faster queries
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session_id
            ON messages(session_id)
        """)
        
        conn.commit()


def health_check(request_id: str = "unknown") -> bool:
    """Check if database is accessible."""
    start = time.perf_counter()
    _log_event("db_query_start", query_name="health_check", request_id=request_id)
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            _log_event(
                "db_query_ok",
                query_name="health_check",
                request_id=request_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return True
    except Exception as e:
        _log_event(
            "db_query_error",
            level="error",
            query_name="health_check",
            request_id=request_id,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            error=str(e),
        )
        return False


# ============================================================================
# Session operations
# ============================================================================

def create_session(
    session_id: str,
    profession_query: str,
    vacancy_kb: Optional[Dict[str, Any]] = None,
    request_id: str = "unknown",
) -> Dict[str, Any]:
    """Create a new session in database."""
    start = time.perf_counter()
    _log_event("db_query_start", query_name="create_session", request_id=request_id, session_id=session_id)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("""
                INSERT INTO sessions (session_id, profession_query, vacancy_kb)
                VALUES (%s, %s, %s)
                RETURNING session_id, profession_query, chat_state, vacancy_kb, free_report, created_at
            """, (session_id, profession_query, psycopg2.extras.Json(vacancy_kb or {})))
            session = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="create_session",
                request_id=request_id,
                session_id=session_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(session) if session else {}
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="create_session",
                request_id=request_id,
                session_id=session_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def get_session(session_id: str, request_id: str = "unknown") -> Optional[Dict[str, Any]]:
    """Retrieve a session by ID."""
    start = time.perf_counter()
    _log_event("db_query_start", query_name="get_session", request_id=request_id, session_id=session_id)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("""
                SELECT session_id, profession_query, chat_state, vacancy_kb, free_report, created_at, updated_at
                FROM sessions
                WHERE session_id = %s
            """, (session_id,))
            session = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="get_session",
                request_id=request_id,
                session_id=session_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            if session:
                session = dict(session)
                session["vacancy_kb"] = safe_json(session.get("vacancy_kb"), {})
                session["free_report"] = safe_json(session.get("free_report"), {})
                return session
            return None
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="get_session",
                request_id=request_id,
                session_id=session_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def update_session(
    session_id: str,
    chat_state: Optional[str] = None,
    vacancy_kb: Optional[Dict[str, Any]] = None,
    free_report: Optional[Dict[str, Any]] = None,
    request_id: str = "unknown",
) -> None:
    """Update session fields."""
    start = time.perf_counter()
    _log_event("db_query_start", query_name="update_session", request_id=request_id, session_id=session_id)
    with get_db_connection() as conn:
        cur = conn.cursor()
        updates = []
        params = []
        
        if chat_state is not None:
            updates.append("chat_state = %s")
            params.append(chat_state)
        
        if vacancy_kb is not None:
            updates.append("vacancy_kb = %s")
            params.append(psycopg2.extras.Json(vacancy_kb or {}))
        
        if free_report is not None:
            updates.append("free_report = %s")
            params.append(psycopg2.extras.Json(free_report or {}))
        
        if updates:
            updates.append("updated_at = now()")
            params.append(session_id)
            
            query = f"""
                UPDATE sessions
                SET {', '.join(updates)}
                WHERE session_id = %s
            """
            try:
                cur.execute(query, params)
                _log_event(
                    "db_query_ok",
                    query_name="update_session",
                    request_id=request_id,
                    session_id=session_id,
                    duration_ms=round((time.perf_counter() - start) * 1000, 2),
                    rowcount=cur.rowcount,
                )
            except Exception as e:
                _log_event(
                    "db_query_error",
                    level="error",
                    query_name="update_session",
                    request_id=request_id,
                    session_id=session_id,
                    duration_ms=round((time.perf_counter() - start) * 1000, 2),
                    error=str(e),
                )
                raise


# ============================================================================
# Message operations
# ============================================================================

def add_message(session_id: str, role: str, text: str, request_id: str = "unknown") -> int:
    """Add a message to a session. Returns message ID."""
    start = time.perf_counter()
    _log_event("db_query_start", query_name="add_message", request_id=request_id, session_id=session_id)
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO messages (session_id, role, text)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (session_id, role, text))
            msg_id = cur.fetchone()[0]
            _log_event(
                "db_query_ok",
                query_name="add_message",
                request_id=request_id,
                session_id=session_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return msg_id
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="add_message",
                request_id=request_id,
                session_id=session_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def get_session_messages(session_id: str, limit: Optional[int] = None, request_id: str = "unknown") -> List[Dict[str, Any]]:
    """Retrieve messages for a session in chronological order with optional limit."""
    start = time.perf_counter()
    _log_event("db_query_start", query_name="get_session_messages", request_id=request_id, session_id=session_id)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        params = [session_id]
        limit_clause = ""
        if limit:
            limit_clause = " LIMIT %s"
            params.append(limit)
        
        try:
            cur.execute(f"""
                SELECT id, session_id, role, text, created_at
                FROM messages
                WHERE session_id = %s
                ORDER BY created_at ASC{limit_clause}
            """, params)
            messages = cur.fetchall()
            _log_event(
                "db_query_ok",
                query_name="get_session_messages",
                request_id=request_id,
                session_id=session_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=len(messages),
            )
            return [dict(msg) for msg in messages]
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="get_session_messages",
                request_id=request_id,
                session_id=session_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def delete_session(session_id: str, request_id: str = "unknown") -> None:
    """Delete a session and all its messages (cascade)."""
    start = time.perf_counter()
    _log_event("db_query_start", query_name="delete_session", request_id=request_id, session_id=session_id)
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
            _log_event(
                "db_query_ok",
                query_name="delete_session",
                request_id=request_id,
                session_id=session_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="delete_session",
                request_id=request_id,
                session_id=session_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise
