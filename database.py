import json
import os
import sqlite3
import time
from pathlib import Path
from config import DATABASE_PATH, DEFAULT_ADMIN_LEVEL
from levels import level_from_xp

def _connect():
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    with _connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL DEFAULT 'گروه',
            admin_level INTEGER NOT NULL DEFAULT 70,
            rankup_announcements INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS members (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL DEFAULT '',
            full_name TEXT NOT NULL DEFAULT '',
            xp INTEGER NOT NULL DEFAULT 0,
            bonus_points INTEGER NOT NULL DEFAULT 0,
            custom_title TEXT NOT NULL DEFAULT '',
            custom_badges TEXT NOT NULL DEFAULT '[]',
            last_xp_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (chat_id, user_id),
            FOREIGN KEY(chat_id) REFERENCES groups(chat_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_members_rank ON members(chat_id, xp DESC);
        CREATE TABLE IF NOT EXISTS point_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            actor_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS admin_requests (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at INTEGER NOT NULL,
            reviewed_at INTEGER,
            PRIMARY KEY (chat_id, user_id)
        );
        """)
        conn.execute("UPDATE groups SET admin_level=? WHERE admin_level IS NULL", (DEFAULT_ADMIN_LEVEL,))

def register_group(chat_id: int, title: str):
    now = int(time.time())
    with _connect() as conn:
        conn.execute(
            """INSERT INTO groups(chat_id,title,admin_level,created_at) VALUES(?,?,?,?)
               ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title""",
            (chat_id, title or "گروه", DEFAULT_ADMIN_LEVEL, now),
        )

def get_groups():
    with _connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM groups ORDER BY title COLLATE NOCASE")]

def get_group(chat_id: int):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM groups WHERE chat_id=?", (chat_id,)).fetchone()
        return dict(row) if row else None

def set_admin_level(chat_id: int, level: int):
    level = max(1, min(100, int(level)))
    with _connect() as conn:
        conn.execute("UPDATE groups SET admin_level=? WHERE chat_id=?", (level, chat_id))

def set_announcements(chat_id: int, enabled: bool):
    with _connect() as conn:
        conn.execute("UPDATE groups SET rankup_announcements=? WHERE chat_id=?", (int(enabled), chat_id))

def upsert_member(chat_id: int, user, xp_delta=0, award_xp=False, cooldown_seconds=60):
    now = int(time.time())
    username = (user.username or "")
    full_name = (user.full_name or user.first_name or "عضو")
    with _connect() as conn:
        conn.execute(
            """INSERT INTO members(chat_id,user_id,username,full_name,updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(chat_id,user_id) DO UPDATE SET
               username=excluded.username, full_name=excluded.full_name, updated_at=excluded.updated_at""",
            (chat_id, user.id, username, full_name, now),
        )
        row = conn.execute("SELECT xp,last_xp_at FROM members WHERE chat_id=? AND user_id=?", (chat_id, user.id)).fetchone()
        old_xp = int(row["xp"])
        old_level = level_from_xp(old_xp)
        got_xp = False
        new_xp = old_xp
        if award_xp and now - int(row["last_xp_at"]) >= cooldown_seconds:
            new_xp = old_xp + max(0, int(xp_delta))
            conn.execute("UPDATE members SET xp=?,last_xp_at=?,updated_at=? WHERE chat_id=? AND user_id=?",
                         (new_xp, now, now, chat_id, user.id))
            got_xp = True
        return {"old_xp": old_xp, "xp": new_xp, "old_level": old_level,
                "level": level_from_xp(new_xp), "got_xp": got_xp}

def get_member(chat_id: int, user_id: int):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM members WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        return dict(row) if row else None

def get_members(chat_id: int, limit=30, offset=0):
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM members WHERE chat_id=?
               ORDER BY xp DESC, bonus_points DESC, full_name COLLATE NOCASE
               LIMIT ? OFFSET ?""", (chat_id, limit, offset)
        ).fetchall()
        return [dict(r) for r in rows]

def member_count(chat_id: int):
    with _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM members WHERE chat_id=?", (chat_id,)).fetchone()[0])

def change_bonus_points(chat_id: int, user_id: int, amount: int, actor_id: int, reason: str):
    now = int(time.time())
    with _connect() as conn:
        row = conn.execute("SELECT bonus_points FROM members WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        if not row:
            return None
        new_value = max(0, int(row["bonus_points"]) + int(amount))
        actual_change = new_value - int(row["bonus_points"])
        conn.execute("UPDATE members SET bonus_points=?,updated_at=? WHERE chat_id=? AND user_id=?",
                     (new_value, now, chat_id, user_id))
        conn.execute("INSERT INTO point_history(chat_id,user_id,actor_id,amount,reason,created_at) VALUES(?,?,?,?,?,?)",
                     (chat_id, user_id, actor_id, actual_change, reason, now))
        return new_value

def set_custom_title(chat_id: int, user_id: int, title: str):
    with _connect() as conn:
        conn.execute("UPDATE members SET custom_title=?,updated_at=? WHERE chat_id=? AND user_id=?",
                     (title[:60], int(time.time()), chat_id, user_id))

def set_custom_badges(chat_id: int, user_id: int, badges):
    with _connect() as conn:
        conn.execute("UPDATE members SET custom_badges=?,updated_at=? WHERE chat_id=? AND user_id=?",
                     (json.dumps(badges, ensure_ascii=False), int(time.time()), chat_id, user_id))

def add_admin_request(chat_id: int, user_id: int):
    now = int(time.time())
    with _connect() as conn:
        conn.execute("""INSERT INTO admin_requests(chat_id,user_id,status,created_at,reviewed_at)
                        VALUES(?,?,'pending',?,NULL)
                        ON CONFLICT(chat_id,user_id) DO UPDATE SET status='pending',created_at=excluded.created_at,reviewed_at=NULL""",
                     (chat_id, user_id, now))

def get_admin_requests(chat_id: int, status="pending"):
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM admin_requests WHERE chat_id=? AND status=? ORDER BY created_at",
            (chat_id, status)
        )]

def set_admin_request_status(chat_id: int, user_id: int, status: str):
    with _connect() as conn:
        conn.execute("UPDATE admin_requests SET status=?,reviewed_at=? WHERE chat_id=? AND user_id=?",
                     (status, int(time.time()), chat_id, user_id))

def history_for_member(chat_id: int, user_id: int, limit=8):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM point_history WHERE chat_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]
