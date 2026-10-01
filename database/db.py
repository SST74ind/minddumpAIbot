import sqlite3

DB_NAME = "minddump.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Create main table if it doesn't exist yet
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            remind_at_iso TEXT,
            details TEXT,
            priority TEXT,
            status TEXT DEFAULT 'pending'
        )
    """)
    conn.commit()

    # Dynamic schema migration: add missing columns to legacy SQLite tables automatically
    cursor.execute("PRAGMA table_info(tasks)")
    existing_columns = [column[1] for column in cursor.fetchall()]

    if "remind_at_iso" not in existing_columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN remind_at_iso TEXT")
    if "details" not in existing_columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN details TEXT")
    if "priority" not in existing_columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN priority TEXT")
    if "status" not in existing_columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN status TEXT DEFAULT 'pending'")

    conn.commit()
    conn.close()

def save_tasks(user_id: int, tasks: list):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    for t in tasks:
        cursor.execute("""
            INSERT INTO tasks (user_id, title, remind_at_iso, details, priority, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (
            user_id,
            t.get("title"),
            t.get("remind_at_iso"),
            t.get("details"),
            t.get("priority", "Medium")
        ))
    conn.commit()
    conn.close()

def get_user_tasks(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE user_id = ? AND status = 'pending'", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_all_pending_tasks():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, title, remind_at_iso, details, priority, status FROM tasks WHERE status = 'pending'")
    rows = cursor.fetchall()
    conn.close()
    return rows

def mark_task_completed(task_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()