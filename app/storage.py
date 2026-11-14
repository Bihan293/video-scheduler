"""SQLite storage for accounts, OAuth states, posts and pending bot uploads."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    platform           TEXT NOT NULL DEFAULT 'tiktok',
    open_id            TEXT NOT NULL,
    union_id           TEXT,
    display_name       TEXT,
    username           TEXT,
    avatar_url         TEXT,
    access_token       TEXT NOT NULL,
    refresh_token      TEXT,
    expires_at         REAL,
    refresh_expires_at REAL,
    scope              TEXT,
    telegram_user_id   INTEGER,
    created_at         REAL NOT NULL,
    updated_at         REAL NOT NULL,
    UNIQUE (platform, open_id)
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state            TEXT PRIMARY KEY,
    telegram_user_id INTEGER,
    created_at       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    mode           TEXT NOT NULL,
    title          TEXT NOT NULL DEFAULT '',
    privacy_level  TEXT NOT NULL DEFAULT 'SELF_ONLY',
    publish_id     TEXT,
    status         TEXT NOT NULL DEFAULT 'CREATED',
    fail_reason    TEXT,
    video_size     INTEGER NOT NULL DEFAULT 0,
    video_path     TEXT,
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_uploads (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    file_id          TEXT NOT NULL,
    title            TEXT NOT NULL DEFAULT '',
    created_at       REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_account ON posts(account_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_accounts_tg ON accounts(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_pending_tg ON pending_uploads(telegram_user_id);
"""


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


# ---------------------------------------------------------------- OAuth states


def create_oauth_state(state: str, telegram_user_id: int | None) -> None:
    now = time.time()
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO oauth_states(state, telegram_user_id, created_at) VALUES (?, ?, ?)",
            (state, telegram_user_id, now),
        )
        # States older than 15 minutes are useless.
        conn.execute("DELETE FROM oauth_states WHERE created_at < ?", (now - 900,))


def pop_oauth_state(state: str) -> dict[str, Any] | None:
    now = time.time()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM oauth_states WHERE state = ?", (state,)
        ).fetchone()
        conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
    if not row or now - row["created_at"] > 900:
        return None
    return dict(row)


# -------------------------------------------------------------------- accounts


def upsert_account(
    *,
    open_id: str,
    access_token: str,
    refresh_token: str | None,
    expires_at: float,
    refresh_expires_at: float | None,
    scope: str,
    union_id: str | None = None,
    display_name: str | None = None,
    username: str | None = None,
    avatar_url: str | None = None,
    telegram_user_id: int | None = None,
) -> dict[str, Any]:
    now = time.time()
    with db() as conn:
        existing = conn.execute(
            "SELECT id FROM accounts WHERE platform='tiktok' AND open_id=?",
            (open_id,),
        ).fetchone()
        if existing:
            account_id = existing["id"]
            conn.execute(
                """
                UPDATE accounts SET access_token=?, refresh_token=?, expires_at=?,
                    refresh_expires_at=?, scope=?, union_id=COALESCE(?, union_id),
                    display_name=COALESCE(?, display_name),
                    username=COALESCE(?, username),
                    avatar_url=COALESCE(?, avatar_url),
                    telegram_user_id=COALESCE(?, telegram_user_id),
                    updated_at=?
                WHERE id=?
                """,
                (
                    access_token,
                    refresh_token,
                    expires_at,
                    refresh_expires_at,
                    scope,
                    union_id,
                    display_name,
                    username,
                    avatar_url,
                    telegram_user_id,
                    now,
                    account_id,
                ),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO accounts(platform, open_id, union_id, display_name,
                    username, avatar_url, access_token, refresh_token, expires_at,
                    refresh_expires_at, scope, telegram_user_id, created_at, updated_at)
                VALUES('tiktok', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    open_id,
                    union_id,
                    display_name,
                    username,
                    avatar_url,
                    access_token,
                    refresh_token,
                    expires_at,
                    refresh_expires_at,
                    scope,
                    telegram_user_id,
                    now,
                    now,
                ),
            )
            account_id = cur.lastrowid
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    return dict(row)


def update_account_tokens(
    account_id: int,
    *,
    access_token: str,
    refresh_token: str | None,
    expires_at: float,
    refresh_expires_at: float | None,
) -> None:
    with db() as conn:
        conn.execute(
            """UPDATE accounts SET access_token=?, refresh_token=?, expires_at=?,
               refresh_expires_at=?, updated_at=? WHERE id=?""",
            (
                access_token,
                refresh_token,
                expires_at,
                refresh_expires_at,
                time.time(),
                account_id,
            ),
        )


def get_account(account_id: int) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    return _row(row)


def get_latest_account_for_telegram(telegram_user_id: int) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE telegram_user_id=? ORDER BY updated_at DESC LIMIT 1",
            (telegram_user_id,),
        ).fetchone()
    return _row(row)


def link_account_to_telegram(account_id: int, telegram_user_id: int) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE accounts SET telegram_user_id=?, updated_at=? WHERE id=?",
            (telegram_user_id, time.time(), account_id),
        )


def delete_account(account_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))


# ----------------------------------------------------------------------- posts


def create_post(
    *,
    account_id: int,
    mode: str,
    title: str,
    privacy_level: str,
    video_size: int,
    video_path: str | None,
    status: str = "CREATED",
    publish_id: str | None = None,
) -> dict[str, Any]:
    now = time.time()
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO posts(account_id, mode, title, privacy_level, publish_id,
                status, video_size, video_path, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                mode,
                title,
                privacy_level,
                publish_id,
                status,
                video_size,
                video_path,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM posts WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


def update_post(post_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    assignments = ", ".join(f"{key}=?" for key in fields)
    with db() as conn:
        conn.execute(
            f"UPDATE posts SET {assignments} WHERE id=?",
            (*fields.values(), post_id),
        )


def get_post(post_id: int) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    return _row(row)


def list_posts(account_id: int, limit: int = 10) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE account_id=? ORDER BY id DESC LIMIT ?",
            (account_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def post_owner_telegram(post_id: int) -> int | None:
    with db() as conn:
        row = conn.execute(
            "SELECT a.telegram_user_id FROM posts p JOIN accounts a ON a.id=p.account_id WHERE p.id=?",
            (post_id,),
        ).fetchone()
    return row["telegram_user_id"] if row else None


# ------------------------------------------------------------ pending uploads


def create_pending(telegram_user_id: int, file_id: str, title: str) -> int:
    now = time.time()
    with db() as conn:
        conn.execute(
            "DELETE FROM pending_uploads WHERE created_at < ?", (now - 3600,)
        )
        cur = conn.execute(
            "INSERT INTO pending_uploads(telegram_user_id, file_id, title, created_at) VALUES(?, ?, ?, ?)",
            (telegram_user_id, file_id, title, now),
        )
    return int(cur.lastrowid)


def get_pending(pending_id: int) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM pending_uploads WHERE id=?", (pending_id,)
        ).fetchone()
    return _row(row)


def delete_pending(pending_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM pending_uploads WHERE id=?", (pending_id,))
