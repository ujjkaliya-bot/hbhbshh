"""
database.py — SQLite persistence layer for the Bot Hosting Platform.

Tables
------
users        : (user_id, username, plan, max_bots, expiry, banned, created_at)
hosted_bots  : (bot_id, owner_id, server_id, name, language, status,
                remote_path, restart_count, created_at, last_check)
servers      : (server_id, ip, port, ssh_user, ram_total_mb, region,
                credit_expiry, status, added_at)

The module is dependency-free (stdlib sqlite3 only) and safe to call from
multiple threads: every operation opens a short-lived connection and the
database runs in WAL mode.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterable, Optional


def _default_db_path() -> str:
    """
    Pick a writable SQLite location.

    Env ``KILO_HOST_AGENT_DB`` wins. Otherwise use the app directory when it
    is writable (Selfhost/systemd), else fall back to /tmp (Render, where the
    checkout may be read-only and the disk is ephemeral).
    """
    env = os.environ.get("KILO_HOST_AGENT_DB")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    if os.access(here, os.W_OK):
        return os.path.join(here, "platform.db")
    return "/tmp/platform.db"


DB_PATH = _default_db_path()

_write_lock = threading.Lock()


@contextmanager
def _connect():
    """Yield a configured SQLite connection (row-dict access)."""
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they do not exist. Idempotent."""
    with _write_lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                plan        TEXT    NOT NULL DEFAULT 'free',
                max_bots    INTEGER NOT NULL DEFAULT 1,
                expiry      TEXT,
                banned      INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS servers (
                server_id     TEXT PRIMARY KEY,
                ip            TEXT NOT NULL,
                port          INTEGER NOT NULL DEFAULT 22,
                ssh_user      TEXT NOT NULL DEFAULT 'root',
                ram_total_mb  INTEGER NOT NULL DEFAULT 2048,
                region        TEXT,
                credit_expiry TEXT,
                status        TEXT NOT NULL DEFAULT 'active',
                added_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS hosted_bots (
                bot_id        TEXT PRIMARY KEY,
                owner_id      INTEGER NOT NULL,
                server_id     TEXT,
                name          TEXT,
                language      TEXT,
                status        TEXT NOT NULL DEFAULT 'deploying',
                remote_path   TEXT,
                restart_count INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                last_check    TEXT,
                FOREIGN KEY (owner_id) REFERENCES users(user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_bots_owner  ON hosted_bots(owner_id);
            CREATE INDEX IF NOT EXISTS idx_bots_server ON hosted_bots(server_id);

            CREATE TABLE IF NOT EXISTS chat_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                role       TEXT    NOT NULL,
                content    TEXT    NOT NULL,
                created_at TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_history(user_id, id);
            """
        )


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def get_user(user_id: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def upsert_user(user_id: int, username: str = "", plan: str = "free",
                max_bots: int = 1, expiry: Optional[str] = None) -> dict:
    """Insert the user if missing, otherwise refresh the username."""
    with _write_lock, _connect() as conn:
        conn.execute(
            "INSERT INTO users (user_id, username, plan, max_bots, expiry) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
            (user_id, username, plan, max_bots, expiry),
        )
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row)


def ensure_user(user_id: int, username: str = "") -> dict:
    user = get_user(user_id)
    if user:
        if username and user.get("username") != username:
            with _write_lock, _connect() as conn:
                conn.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
            user["username"] = username
        return user
    return upsert_user(user_id, username)


def set_ban(user_id: int, banned: bool) -> None:
    with _write_lock, _connect() as conn:
        conn.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, user_id))


def is_banned(user_id: int) -> bool:
    user = get_user(user_id)
    return bool(user and user.get("banned"))


def set_max_bots(user_id: int, max_bots: int) -> None:
    with _write_lock, _connect() as conn:
        conn.execute("UPDATE users SET max_bots=? WHERE user_id=?", (max_bots, user_id))


def set_plan(user_id: int, plan: str, max_bots: int, expiry: Optional[str]) -> None:
    with _write_lock, _connect() as conn:
        conn.execute(
            "UPDATE users SET plan=?, max_bots=?, expiry=? WHERE user_id=?",
            (plan, max_bots, expiry, user_id),
        )


def count_user_bots(user_id: int) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM hosted_bots WHERE owner_id=?", (user_id,)
        ).fetchone()
        return int(row["c"])


def list_users(limit: int = 100, offset: int = 0) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Bots
# --------------------------------------------------------------------------- #
def add_bot(bot_id: str, owner_id: int, server_id: str, name: str,
            language: str, remote_path: str, status: str = "deploying") -> dict:
    with _write_lock, _connect() as conn:
        conn.execute(
            "INSERT INTO hosted_bots "
            "(bot_id, owner_id, server_id, name, language, status, remote_path) "
            "VALUES (?,?,?,?,?,?,?)",
            (bot_id, owner_id, server_id, name, language, remote_path, status),
        )
    return get_bot(bot_id)


def get_bot(bot_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM hosted_bots WHERE bot_id=?", (bot_id,)).fetchone()
        return dict(row) if row else None


def list_bots_by_owner(owner_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM hosted_bots WHERE owner_id=? ORDER BY created_at DESC",
            (owner_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_bots_by_server(server_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM hosted_bots WHERE server_id=?", (server_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def list_all_bots() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM hosted_bots ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def update_bot_status(bot_id: str, status: str,
                      restart_count: Optional[int] = None) -> None:
    with _write_lock, _connect() as conn:
        conn.execute(
            "UPDATE hosted_bots SET status=?, last_check=datetime('now') WHERE bot_id=?",
            (status, bot_id),
        )
        if restart_count is not None:
            conn.execute(
                "UPDATE hosted_bots SET restart_count=? WHERE bot_id=?",
                (restart_count, bot_id),
            )


def move_bot_to_server(bot_id: str, server_id: str, remote_path: str,
                       status: str = "running") -> None:
    with _write_lock, _connect() as conn:
        conn.execute(
            "UPDATE hosted_bots SET server_id=?, remote_path=?, status=?, "
            "restart_count=0, last_check=datetime('now') WHERE bot_id=?",
            (server_id, remote_path, status, bot_id),
        )


def delete_bot(bot_id: str) -> None:
    with _write_lock, _connect() as conn:
        conn.execute("DELETE FROM hosted_bots WHERE bot_id=?", (bot_id,))


def count_bots_on_server(server_id: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM hosted_bots WHERE server_id=?", (server_id,)
        ).fetchone()
        return int(row["c"])


# --------------------------------------------------------------------------- #
# Servers
# --------------------------------------------------------------------------- #
def add_server(server_id: str, ip: str, port: int = 22, ssh_user: str = "root",
               ram_total_mb: int = 2048, region: Optional[str] = None,
               credit_expiry: Optional[str] = None) -> dict:
    with _write_lock, _connect() as conn:
        conn.execute(
            "INSERT INTO servers "
            "(server_id, ip, port, ssh_user, ram_total_mb, region, credit_expiry) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(server_id) DO UPDATE SET ip=excluded.ip, port=excluded.port, "
            "ssh_user=excluded.ssh_user, ram_total_mb=excluded.ram_total_mb, "
            "region=excluded.region, credit_expiry=excluded.credit_expiry, status='active'",
            (server_id, ip, port, ssh_user, ram_total_mb, region, credit_expiry),
        )
    return get_server(server_id)


def get_server(server_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM servers WHERE server_id=?", (server_id,)).fetchone()
        return dict(row) if row else None


def list_servers(active_only: bool = False) -> list[dict]:
    q = "SELECT * FROM servers"
    if active_only:
        q += " WHERE status='active'"
    q += " ORDER BY server_id"
    with _connect() as conn:
        rows = conn.execute(q).fetchall()
        return [dict(r) for r in rows]


def set_server_status(server_id: str, status: str) -> None:
    with _write_lock, _connect() as conn:
        conn.execute("UPDATE servers SET status=? WHERE server_id=?", (status, server_id))


def remove_server(server_id: str) -> None:
    with _write_lock, _connect() as conn:
        conn.execute("DELETE FROM servers WHERE server_id=?", (server_id,))


# --------------------------------------------------------------------------- #
# AI chat history
# --------------------------------------------------------------------------- #
def add_chat(user_id: int, role: str, content: str) -> None:
    """Append one message to a user's AI chat history."""
    with _write_lock, _connect() as conn:
        conn.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
            (int(user_id), role, content[:8000]),
        )


def get_chat_history(user_id: int, limit: int = 10) -> list[dict]:
    """Return the most recent ``limit`` messages, oldest-first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM chat_history WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (int(user_id), int(limit)),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_chat_history(user_id: int) -> None:
    with _write_lock, _connect() as conn:
        conn.execute("DELETE FROM chat_history WHERE user_id = ?", (int(user_id),))


# --------------------------------------------------------------------------- #
# Bootstrap helpers
# --------------------------------------------------------------------------- #
def seed_servers_from_json(path: str) -> int:
    """Load servers.json (if present) into the servers table. Returns count."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return 0

    items: Iterable[dict] = data.get("servers", []) if isinstance(data, dict) else data
    count = 0
    for item in items:
        if not item.get("server_id") or not item.get("ip"):
            continue
        ip = str(item["ip"]).strip()
        # Skip template placeholders so they never reach the load balancer.
        if ip.upper().startswith("CHANGE_ME"):
            continue
        add_server(
            server_id=item["server_id"],
            ip=ip,
            port=int(item.get("port", 22)),
            ssh_user=item.get("user", item.get("ssh_user", "root")),
            ram_total_mb=int(item.get("ram_total_mb", 2048)),
            region=item.get("region"),
            credit_expiry=item.get("credit_expiry"),
        )
        count += 1
    return count


if __name__ == "__main__":
    init_db()
    print(f"[database] initialised at {DB_PATH}")
