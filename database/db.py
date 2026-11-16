import os
import sqlite3
from contextlib import closing
from datetime import datetime
import zoneinfo

from config import DATABASE_PATH

IST_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")

# Column order used everywhere: (id, user_id, title, remind_at_iso, details, priority, status)
_COLS = "id, user_id, title, remind_at_iso, details, priority, status"


def _connect():
    folder = os.path.dirname(DATABASE_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    return sqlite3.connect(DATABASE_PATH, timeout=10)


def init_db():
    with closing(_connect()) as conn, conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                remind_at_iso TEXT,
                details TEXT,
                priority TEXT,
                status TEXT DEFAULT 'pending',
                reminded INTEGER DEFAULT 0
            )
        """)
        existing = [c[1] for c in conn.execute("PRAGMA table_info(tasks)").fetchall()]

        # Migrations for databases created by older versions
        for col, ddl in [
            ("remind_at_iso", "TEXT"),
            ("details", "TEXT"),
            ("priority", "TEXT"),
            ("status", "TEXT DEFAULT 'pending'"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {ddl}")

        if "reminded" not in existing:
            conn.execute("ALTER TABLE tasks ADD COLUMN reminded INTEGER DEFAULT 0")
            # Old overdue tasks were already alerted in the past - don't re-fire them all at startup.
            now_iso = datetime.now(IST_TZ).strftime("%Y-%m-%dT%H:%M:%S")
            conn.execute(
                "UPDATE tasks SET reminded = 1 WHERE remind_at_iso IS NOT NULL AND remind_at_iso < ?",
                (now_iso,),
            )


def save_tasks(user_id: int, tasks: list) -> list:
    """Insert tasks and return their new row ids (same order as `tasks`)."""
    ids = []
    with closing(_connect()) as conn, conn:
        for t in tasks:
            cur = conn.execute(
                """
                INSERT INTO tasks (user_id, title, remind_at_iso, details, priority, status, reminded)
                VALUES (?, ?, ?, ?, ?, 'pending', 0)
                """,
                (
                    user_id,
                    t.get("title"),
                    t.get("remind_at_iso"),
                    t.get("details"),
                    t.get("priority") or "Medium",
                ),
            )
            ids.append(cur.lastrowid)
    return ids


def get_user_tasks(user_id: int, limit: int = 20):
    with closing(_connect()) as conn:
        return conn.execute(
            f"""SELECT {_COLS} FROM tasks
                WHERE user_id = ? AND status = 'pending'
                ORDER BY remind_at_iso IS NULL, remind_at_iso, id
                LIMIT ?""",
            (user_id, limit),
        ).fetchall()


def get_task(task_id: int):
    with closing(_connect()) as conn:
        return conn.execute(f"SELECT {_COLS} FROM tasks WHERE id = ?", (task_id,)).fetchone()


def get_all_pending_tasks():
    """Pending tasks that still need a reminder to be sent."""
    with closing(_connect()) as conn:
        return conn.execute(
            f"""SELECT {_COLS} FROM tasks
                WHERE status = 'pending' AND COALESCE(reminded, 0) = 0
                  AND remind_at_iso IS NOT NULL
                ORDER BY remind_at_iso"""
        ).fetchall()


def mark_task_completed(task_id: int):
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,))


def mark_reminded(task_id: int):
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE tasks SET reminded = 1 WHERE id = ?", (task_id,))


def update_remind_time(task_id: int, remind_at_iso: str):
    """Used by snooze: store the new time and allow the reminder to fire again."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE tasks SET remind_at_iso = ?, reminded = 0 WHERE id = ?",
            (remind_at_iso, task_id),
        )
