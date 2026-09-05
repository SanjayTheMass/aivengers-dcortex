"""Session + chat-history store (tables auto-created in appstate.db).

Kept separate from crewops.db so reverting the operational DB to its
pristine backup never touches chat history or the change log.
"""
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.db import rows

APPSTATE_PATH = Path(__file__).resolve().parents[1] / "appstate.db"

_DDL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'New chat',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL,
    spoken_summary TEXT,
    tool_trace TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_msgs_session ON chat_messages(session_id, id);
CREATE TABLE IF NOT EXISTS pending_actions (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    action TEXT NOT NULL,
    params TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT,
    action TEXT NOT NULL,
    summary TEXT NOT NULL,
    changes TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _con():
    con = sqlite3.connect(APPSTATE_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(_DDL)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def create_session(title="New chat"):
    sid, ts = uuid.uuid4().hex[:12], _now()
    with _con() as con:
        con.execute("INSERT INTO chat_sessions (id,title,created_at,updated_at) VALUES (?,?,?,?)",
                    (sid, title, ts, ts))
    return get_session(sid)


def list_sessions():
    with _con() as con:
        return rows(con, """SELECT s.*, COUNT(m.id) AS message_count
                            FROM chat_sessions s LEFT JOIN chat_messages m ON m.session_id = s.id
                            GROUP BY s.id ORDER BY s.updated_at DESC""")


def get_session(sid):
    with _con() as con:
        r = rows(con, "SELECT * FROM chat_sessions WHERE id=?", (sid,))
    return r[0] if r else None


def rename_session(sid, title):
    with _con() as con:
        con.execute("UPDATE chat_sessions SET title=?, updated_at=? WHERE id=?", (title, _now(), sid))
    return get_session(sid)


def delete_session(sid):
    with _con() as con:
        con.execute("DELETE FROM chat_messages WHERE session_id=?", (sid,))
        cur = con.execute("DELETE FROM chat_sessions WHERE id=?", (sid,))
    return cur.rowcount > 0


def get_messages(sid, limit=200):
    with _con() as con:
        out = rows(con, "SELECT * FROM chat_messages WHERE session_id=? ORDER BY id LIMIT ?", (sid, limit))
    for m in out:
        m["tool_trace"] = json.loads(m["tool_trace"]) if m["tool_trace"] else []
    return out


def clear_messages(sid):
    with _con() as con:
        con.execute("DELETE FROM chat_messages WHERE session_id=?", (sid,))
        con.execute("UPDATE chat_sessions SET updated_at=? WHERE id=?", (_now(), sid))


def add_message(sid, role, content, spoken=None, trace=None):
    ts = _now()
    with _con() as con:
        con.execute("""INSERT INTO chat_messages (session_id,role,content,spoken_summary,tool_trace,created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (sid, role, content, spoken, json.dumps(trace) if trace else None, ts))
        con.execute("UPDATE chat_sessions SET updated_at=? WHERE id=?", (ts, sid))


def history_as_llm_messages(sid):
    return [{"role": m["role"], "content": m["content"]} for m in get_messages(sid)]
