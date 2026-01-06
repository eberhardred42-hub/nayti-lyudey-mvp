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
import uuid
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

        # Stage 9.3.x: optional user ownership for sessions.
        cur.execute("""
            ALTER TABLE sessions
            ADD COLUMN IF NOT EXISTS user_id TEXT
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

        # Stage 9.3.x: artifacts table (links files to sessions).
        # Columns are nullable to keep it forward-compatible with older DBs.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS artifacts (
                id UUID PRIMARY KEY,
                session_id TEXT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                kind TEXT NULL,
                format TEXT NULL,
                payload_json JSONB NULL,
                meta JSONB NULL,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)

        cur.execute("""
            ALTER TABLE artifacts
            ADD COLUMN IF NOT EXISTS session_id TEXT
        """)
        cur.execute("""
            ALTER TABLE artifacts
            ADD COLUMN IF NOT EXISTS kind TEXT
        """)
        cur.execute("""
            ALTER TABLE artifacts
            ADD COLUMN IF NOT EXISTS format TEXT
        """)
        cur.execute("""
            ALTER TABLE artifacts
            ADD COLUMN IF NOT EXISTS payload_json JSONB
        """)

        cur.execute("""
            ALTER TABLE artifacts
            ADD COLUMN IF NOT EXISTS meta JSONB
        """)

        # Files stored in S3-compatible storage (MinIO locally), metadata in Postgres.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS artifact_files (
                id UUID PRIMARY KEY,
                artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
                storage TEXT NOT NULL DEFAULT 's3',
                bucket TEXT NOT NULL,
                object_key TEXT NOT NULL,
                content_type TEXT NOT NULL,
                size_bytes BIGINT NULL,
                etag TEXT NULL,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_artifact_files_artifact_id
            ON artifact_files(artifact_id)
        """)

        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_artifact_files_bucket_object_key
            ON artifact_files(bucket, object_key)
        """)

        # Stage 9.4.2: async render jobs.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS render_jobs (
                id UUID PRIMARY KEY,
                pack_id UUID NOT NULL,
                session_id UUID NOT NULL,
                user_id UUID NULL,
                doc_id TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INT NOT NULL DEFAULT 0,
                max_attempts INT NOT NULL DEFAULT 5,
                last_error TEXT NULL,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_render_jobs_status_updated
            ON render_jobs(status, updated_at)
        """)

        # Stage 9.4.3+: packs (group of documents to render).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS packs (
                pack_id UUID PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT NULL,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_packs_user_created
            ON packs(user_id, created_at)
        """)

        # Admin users (phone allowlist + sessions).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY,
                phone_e164 TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_sessions (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ DEFAULT now(),
                revoked_at TIMESTAMPTZ NULL
            )
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_admin_sessions_user_id
            ON admin_sessions(user_id)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires_at
            ON admin_sessions(expires_at)
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


# ============================================================================
# Artifact file operations
# ============================================================================

def create_artifact_file(
    artifact_id: str,
    bucket: str,
    object_key: str,
    content_type: str,
    size_bytes: Optional[int] = None,
    etag: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    request_id: str = "unknown",
) -> Dict[str, Any]:
    """Create a new artifact file record.

    Notes:
    - `meta` is accepted for forward-compatibility, but not persisted yet.
    """
    _ = meta
    file_id = str(uuid.uuid4())
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="create_artifact_file",
        request_id=request_id,
        artifact_id=artifact_id,
        file_id=file_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                INSERT INTO artifact_files (
                    id, artifact_id, bucket, object_key, content_type, size_bytes, etag
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, artifact_id, storage, bucket, object_key, content_type, size_bytes, etag, created_at
                """,
                (file_id, artifact_id, bucket, object_key, content_type, size_bytes, etag),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="create_artifact_file",
                request_id=request_id,
                artifact_id=artifact_id,
                file_id=file_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(row) if row else {}
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="create_artifact_file",
                request_id=request_id,
                artifact_id=artifact_id,
                file_id=file_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def get_artifact_file(file_id: str, request_id: str = "unknown") -> Optional[Dict[str, Any]]:
    """Get an artifact file record by its ID."""
    start = time.perf_counter()
    _log_event("db_query_start", query_name="get_artifact_file", request_id=request_id, file_id=file_id)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                SELECT id, artifact_id, storage, bucket, object_key, content_type, size_bytes, etag, created_at
                FROM artifact_files
                WHERE id = %s
                """,
                (file_id,),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="get_artifact_file",
                request_id=request_id,
                file_id=file_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(row) if row else None
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="get_artifact_file",
                request_id=request_id,
                file_id=file_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def get_artifact_file_by_artifact(artifact_id: str, request_id: str = "unknown") -> Optional[Dict[str, Any]]:
    """Get latest artifact file record for the given artifact."""
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="get_artifact_file_by_artifact",
        request_id=request_id,
        artifact_id=artifact_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                SELECT id, artifact_id, storage, bucket, object_key, content_type, size_bytes, etag, created_at
                FROM artifact_files
                WHERE artifact_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (artifact_id,),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="get_artifact_file_by_artifact",
                request_id=request_id,
                artifact_id=artifact_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(row) if row else None
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="get_artifact_file_by_artifact",
                request_id=request_id,
                artifact_id=artifact_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def list_user_files(user_id: str, request_id: str = "unknown") -> List[Dict[str, Any]]:
    """List artifact-backed files that belong to the given user."""
    start = time.perf_counter()
    _log_event("db_query_start", query_name="list_user_files", request_id=request_id, user_id=user_id)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                SELECT
                    af.id AS file_id,
                    af.artifact_id,
                    a.kind,
                    af.created_at,
                    af.content_type,
                    af.size_bytes,
                    (a.meta->>'doc_id') AS doc_id
                FROM artifact_files af
                JOIN artifacts a ON a.id = af.artifact_id
                JOIN sessions s ON s.session_id = a.session_id
                WHERE s.user_id = %s
                ORDER BY af.created_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
            _log_event(
                "db_query_ok",
                query_name="list_user_files",
                request_id=request_id,
                user_id=user_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=len(rows),
            )
            return [dict(r) for r in rows]
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="list_user_files",
                request_id=request_id,
                user_id=user_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def set_session_user(session_id: str, user_id: str, request_id: str = "unknown") -> None:
    """Attach a user_id to a session (best-effort; column is optional)."""
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="set_session_user",
        request_id=request_id,
        session_id=session_id,
        user_id=user_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE sessions
                SET user_id = %s, updated_at = now()
                WHERE session_id = %s
                """,
                (user_id, session_id),
            )
            _log_event(
                "db_query_ok",
                query_name="set_session_user",
                request_id=request_id,
                session_id=session_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="set_session_user",
                request_id=request_id,
                session_id=session_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def create_artifact(
    session_id: Optional[str],
    kind: str,
    format: str,
    payload_json: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
    request_id: str = "unknown",
) -> Dict[str, Any]:
    """Create an artifact record."""
    artifact_id = str(uuid.uuid4())
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="create_artifact",
        request_id=request_id,
        artifact_id=artifact_id,
        session_id=session_id,
        kind=kind,
        format=format,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                INSERT INTO artifacts (id, session_id, kind, format, payload_json, meta)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, session_id, kind, format, payload_json, meta, created_at
                """,
                (
                    artifact_id,
                    session_id,
                    kind,
                    format,
                    psycopg2.extras.Json(payload_json) if payload_json is not None else None,
                    psycopg2.extras.Json(meta) if meta is not None else None,
                ),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="create_artifact",
                request_id=request_id,
                artifact_id=artifact_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(row) if row else {}
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="create_artifact",
                request_id=request_id,
                artifact_id=artifact_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


# ==========================================================================
# Admin users + sessions
# ==========================================================================


def ensure_user(
    user_id: str,
    phone_e164: str,
    request_id: str = "unknown",
) -> Dict[str, Any]:
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="ensure_user",
        request_id=request_id,
        user_id=user_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                INSERT INTO users (id, phone_e164)
                VALUES (%s, %s)
                ON CONFLICT (phone_e164) DO UPDATE SET id = EXCLUDED.id
                RETURNING id, phone_e164, created_at
                """,
                (user_id, phone_e164),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="ensure_user",
                request_id=request_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(row) if row else {}
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="ensure_user",
                request_id=request_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def get_user_by_id(user_id: str, request_id: str = "unknown") -> Optional[Dict[str, Any]]:
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="get_user_by_id",
        request_id=request_id,
        user_id=user_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                SELECT id, phone_e164, created_at
                FROM users
                WHERE id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="get_user_by_id",
                request_id=request_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(row) if row else None
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="get_user_by_id",
                request_id=request_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def create_admin_session(
    user_id: str,
    token_hash: str,
    salt: str,
    expires_at: datetime,
    request_id: str = "unknown",
) -> Dict[str, Any]:
    session_id = str(uuid.uuid4())
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="create_admin_session",
        request_id=request_id,
        admin_session_id=session_id,
        user_id=user_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                INSERT INTO admin_sessions (id, user_id, token_hash, salt, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, user_id, expires_at, created_at, revoked_at
                """,
                (session_id, user_id, token_hash, salt, expires_at),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="create_admin_session",
                request_id=request_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(row) if row else {}
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="create_admin_session",
                request_id=request_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def get_admin_session_by_token_hash(
    token_hash: str,
    request_id: str = "unknown",
) -> Optional[Dict[str, Any]]:
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="get_admin_session_by_token_hash",
        request_id=request_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                SELECT id, user_id, token_hash, salt, expires_at, created_at, revoked_at
                FROM admin_sessions
                WHERE token_hash = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (token_hash,),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="get_admin_session_by_token_hash",
                request_id=request_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(row) if row else None
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="get_admin_session_by_token_hash",
                request_id=request_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def revoke_admin_session(admin_session_id: str, request_id: str = "unknown") -> int:
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="revoke_admin_session",
        request_id=request_id,
        admin_session_id=admin_session_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE admin_sessions
                SET revoked_at = now()
                WHERE id = %s AND revoked_at IS NULL
                """,
                (admin_session_id,),
            )
            _log_event(
                "db_query_ok",
                query_name="revoke_admin_session",
                request_id=request_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return int(cur.rowcount or 0)
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="revoke_admin_session",
                request_id=request_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def get_file_download_info_for_user(
    file_id: str,
    user_id: str,
    request_id: str = "unknown",
) -> Optional[Dict[str, Any]]:
    """Resolve (bucket, key) for a file_id if it belongs to the given user."""
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="get_file_download_info_for_user",
        request_id=request_id,
        file_id=file_id,
        user_id=user_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                SELECT
                    af.id AS file_id,
                    af.artifact_id,
                    af.bucket,
                    af.object_key,
                    af.content_type,
                    af.size_bytes,
                    af.etag,
                    af.created_at
                FROM artifact_files af
                JOIN artifacts a ON a.id = af.artifact_id
                JOIN sessions s ON s.session_id = a.session_id
                WHERE af.id = %s AND s.user_id = %s
                """,
                (file_id, user_id),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="get_file_download_info_for_user",
                request_id=request_id,
                file_id=file_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(row) if row else None
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="get_file_download_info_for_user",
                request_id=request_id,
                file_id=file_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


# ==========================================================================
# Pack operations (Stage 9.4.3+)
# ==========================================================================


def create_pack(
    session_id: str,
    user_id: Optional[str],
    request_id: str = "unknown",
) -> Dict[str, Any]:
    pack_id = str(uuid.uuid4())
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="create_pack",
        request_id=request_id,
        pack_id=pack_id,
        session_id=session_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                INSERT INTO packs (pack_id, session_id, user_id)
                VALUES (%s, %s, %s)
                RETURNING pack_id, session_id, user_id, created_at
                """,
                (pack_id, session_id, user_id),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="create_pack",
                request_id=request_id,
                pack_id=pack_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(row) if row else {}
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="create_pack",
                request_id=request_id,
                pack_id=pack_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def get_pack(pack_id: str, request_id: str = "unknown") -> Optional[Dict[str, Any]]:
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="get_pack",
        request_id=request_id,
        pack_id=pack_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                SELECT pack_id, session_id, user_id, created_at
                FROM packs
                WHERE pack_id = %s
                """,
                (pack_id,),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="get_pack",
                request_id=request_id,
                pack_id=pack_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(row) if row else None
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="get_pack",
                request_id=request_id,
                pack_id=pack_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def list_packs_for_user(user_id: str, request_id: str = "unknown") -> List[Dict[str, Any]]:
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="list_packs_for_user",
        request_id=request_id,
        user_id=user_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                SELECT pack_id, session_id, user_id, created_at
                FROM packs
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
            _log_event(
                "db_query_ok",
                query_name="list_packs_for_user",
                request_id=request_id,
                user_id=user_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=len(rows),
            )
            return [dict(r) for r in rows]
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="list_packs_for_user",
                request_id=request_id,
                user_id=user_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def list_latest_render_jobs_for_pack(pack_id: str, request_id: str = "unknown") -> List[Dict[str, Any]]:
    """Return latest job per doc_id for the pack."""
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="list_latest_render_jobs_for_pack",
        request_id=request_id,
        pack_id=pack_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                SELECT DISTINCT ON (doc_id)
                    id,
                    pack_id,
                    session_id,
                    user_id,
                    doc_id,
                    status,
                    attempts,
                    max_attempts,
                    last_error,
                    created_at,
                    updated_at
                FROM render_jobs
                WHERE pack_id = %s
                ORDER BY doc_id, created_at DESC
                """,
                (pack_id,),
            )
            rows = cur.fetchall()
            _log_event(
                "db_query_ok",
                query_name="list_latest_render_jobs_for_pack",
                request_id=request_id,
                pack_id=pack_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=len(rows),
            )
            return [dict(r) for r in rows]
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="list_latest_render_jobs_for_pack",
                request_id=request_id,
                pack_id=pack_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def get_latest_file_id_for_render_job(job_id: str, request_id: str = "unknown") -> Optional[str]:
    """Resolve file_id for a ready job using artifacts.meta.render_job_id."""
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="get_latest_file_id_for_render_job",
        request_id=request_id,
        render_job_id=job_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT af.id
                FROM artifacts a
                JOIN artifact_files af ON af.artifact_id = a.id
                WHERE (a.meta->>'render_job_id') = %s
                ORDER BY af.created_at DESC
                LIMIT 1
                """,
                (job_id,),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="get_latest_file_id_for_render_job",
                request_id=request_id,
                render_job_id=job_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return str(row[0]) if row else None
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="get_latest_file_id_for_render_job",
                request_id=request_id,
                render_job_id=job_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


# ==========================================================================
# Render job operations (Stage 9.4.2)
# ==========================================================================


def create_render_job(
    pack_id: str,
    session_id: str,
    doc_id: str,
    status: str = "queued",
    user_id: Optional[str] = None,
    max_attempts: int = 5,
    request_id: str = "unknown",
) -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="create_render_job",
        request_id=request_id,
        render_job_id=job_id,
        pack_id=pack_id,
        session_id=session_id,
        doc_id=doc_id,
        status=status,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                INSERT INTO render_jobs (
                    id, pack_id, session_id, user_id, doc_id, status, attempts, max_attempts, last_error
                )
                VALUES (%s, %s, %s, %s, %s, %s, 0, %s, NULL)
                RETURNING id, pack_id, session_id, user_id, doc_id, status, attempts, max_attempts, last_error, created_at, updated_at
                """,
                (job_id, pack_id, session_id, user_id, doc_id, status, max_attempts),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="create_render_job",
                request_id=request_id,
                render_job_id=job_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(row) if row else {}
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="create_render_job",
                request_id=request_id,
                render_job_id=job_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def get_render_job(job_id: str, request_id: str = "unknown") -> Optional[Dict[str, Any]]:
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="get_render_job",
        request_id=request_id,
        render_job_id=job_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                """
                SELECT id, pack_id, session_id, user_id, doc_id, status, attempts, max_attempts, last_error, created_at, updated_at
                FROM render_jobs
                WHERE id = %s
                """,
                (job_id,),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="get_render_job",
                request_id=request_id,
                render_job_id=job_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(row) if row else None
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="get_render_job",
                request_id=request_id,
                render_job_id=job_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def try_mark_render_job_rendering(
    job_id: str,
    request_id: str = "unknown",
) -> bool:
    """Atomically transition queued->rendering."""
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="try_mark_render_job_rendering",
        request_id=request_id,
        render_job_id=job_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE render_jobs
                SET status = 'rendering', updated_at = now()
                WHERE id = %s AND status = 'queued'
                """,
                (job_id,),
            )
            ok = cur.rowcount == 1
            _log_event(
                "db_query_ok",
                query_name="try_mark_render_job_rendering",
                request_id=request_id,
                render_job_id=job_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
                transitioned=ok,
            )
            return ok
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="try_mark_render_job_rendering",
                request_id=request_id,
                render_job_id=job_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def mark_render_job_ready(
    job_id: str,
    request_id: str = "unknown",
) -> None:
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="mark_render_job_ready",
        request_id=request_id,
        render_job_id=job_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE render_jobs
                SET status = 'ready', last_error = NULL, updated_at = now()
                WHERE id = %s
                """,
                (job_id,),
            )
            _log_event(
                "db_query_ok",
                query_name="mark_render_job_ready",
                request_id=request_id,
                render_job_id=job_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="mark_render_job_ready",
                request_id=request_id,
                render_job_id=job_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def mark_render_job_failed(
    job_id: str,
    last_error: str,
    request_id: str = "unknown",
) -> None:
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="mark_render_job_failed",
        request_id=request_id,
        render_job_id=job_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE render_jobs
                SET status = 'failed', last_error = %s, updated_at = now()
                WHERE id = %s
                """,
                (last_error, job_id),
            )
            _log_event(
                "db_query_ok",
                query_name="mark_render_job_failed",
                request_id=request_id,
                render_job_id=job_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="mark_render_job_failed",
                request_id=request_id,
                render_job_id=job_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise


def increment_render_job_attempt(
    job_id: str,
    last_error: str,
    request_id: str = "unknown",
) -> Dict[str, Any]:
    """attempts++ and set last_error; returns updated row."""
    start = time.perf_counter()
    _log_event(
        "db_query_start",
        query_name="increment_render_job_attempt",
        request_id=request_id,
        render_job_id=job_id,
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            sql = (
                "UPDATE render_jobs\n"
                "SET attempts = attempts + 1,\n"
                "    last_error = %s,\n"
                "    status = 'queued',\n"
                "    updated_at = now()\n"
                "WHERE id = %s\n"
                "RETURNING id, pack_id, session_id, user_id, doc_id, status, attempts, max_attempts, last_error, created_at, updated_at"
            )
            cur.execute(
                sql,
                (last_error, job_id),
            )
            row = cur.fetchone()
            _log_event(
                "db_query_ok",
                query_name="increment_render_job_attempt",
                request_id=request_id,
                render_job_id=job_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                rowcount=cur.rowcount,
            )
            return dict(row) if row else {}
        except Exception as e:
            _log_event(
                "db_query_error",
                level="error",
                query_name="increment_render_job_attempt",
                request_id=request_id,
                render_job_id=job_id,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )
            raise
