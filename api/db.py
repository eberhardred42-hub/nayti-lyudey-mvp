"""
Database module for Nayti-Lyudey MVP.

Manages persistent storage for:
- sessions (profession query, chat state, vacancy KB, free report)
- messages (user/assistant conversation history)

Uses psycopg2 for PostgreSQL connection (no ORM).
"""

import os
import json
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from typing import Optional, Dict, Any, List

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
                vacancy_kb JSONB,
                free_report JSONB,
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


def health_check() -> bool:
    """Check if database is accessible."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            return True
    except Exception:
        return False


# ============================================================================
# Session operations
# ============================================================================

def create_session(
    session_id: str,
    profession_query: str,
    vacancy_kb: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Create a new session in database."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("""
            INSERT INTO sessions (session_id, profession_query, vacancy_kb)
            VALUES (%s, %s, %s)
            RETURNING session_id, profession_query, chat_state, vacancy_kb, free_report, created_at
        """, (session_id, profession_query, json.dumps(vacancy_kb) if vacancy_kb else None))
        
        session = cur.fetchone()
        return dict(session) if session else {}


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a session by ID."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("""
            SELECT session_id, profession_query, chat_state, vacancy_kb, free_report, created_at, updated_at
            FROM sessions
            WHERE session_id = %s
        """, (session_id,))
        
        session = cur.fetchone()
        if session:
            # Parse JSONB fields
            session = dict(session)
            if session.get("vacancy_kb"):
                session["vacancy_kb"] = json.loads(session["vacancy_kb"])
            if session.get("free_report"):
                session["free_report"] = json.loads(session["free_report"])
            return session
        return None


def update_session(
    session_id: str,
    chat_state: Optional[str] = None,
    vacancy_kb: Optional[Dict[str, Any]] = None,
    free_report: Optional[Dict[str, Any]] = None
) -> None:
    """Update session fields."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        updates = []
        params = []
        
        if chat_state is not None:
            updates.append("chat_state = %s")
            params.append(chat_state)
        
        if vacancy_kb is not None:
            updates.append("vacancy_kb = %s")
            params.append(json.dumps(vacancy_kb))
        
        if free_report is not None:
            updates.append("free_report = %s")
            params.append(json.dumps(free_report))
        
        if updates:
            updates.append("updated_at = now()")
            params.append(session_id)
            
            query = f"""
                UPDATE sessions
                SET {', '.join(updates)}
                WHERE session_id = %s
            """
            cur.execute(query, params)


# ============================================================================
# Message operations
# ============================================================================

def add_message(session_id: str, role: str, text: str) -> int:
    """Add a message to a session. Returns message ID."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO messages (session_id, role, text)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (session_id, role, text))
        
        msg_id = cur.fetchone()[0]
        return msg_id


def get_session_messages(session_id: str) -> List[Dict[str, Any]]:
    """Retrieve all messages for a session in order."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("""
            SELECT id, session_id, role, text, created_at
            FROM messages
            WHERE session_id = %s
            ORDER BY created_at ASC
        """, (session_id,))
        
        messages = cur.fetchall()
        return [dict(msg) for msg in messages]


def delete_session(session_id: str) -> None:
    """Delete a session and all its messages (cascade)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        cur.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
