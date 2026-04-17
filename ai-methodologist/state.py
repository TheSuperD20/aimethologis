import sqlite3
import uuid
from datetime import datetime
from typing import Optional


class StateManager:
    def __init__(self, db_path: str = "bot.db"):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'INIT',
                    topic TEXT,
                    expert_mm_id TEXT,
                    expert_channel_id TEXT,
                    methodologist_mm_id TEXT,
                    methodologist_channel_id TEXT,
                    interview_answers TEXT,
                    proposed_structure TEXT,
                    source_text TEXT,
                    longread TEXT,
                    longread_version INTEGER DEFAULT 0,
                    longread_edit_count INTEGER DEFAULT 0,
                    test TEXT,
                    test_type TEXT,
                    test_version INTEGER DEFAULT 0,
                    test_edit_count INTEGER DEFAULT 0,
                    needs_test INTEGER,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            for col in ["interview_answers", "proposed_structure"]:
                try:
                    conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} TEXT")
                except Exception:
                    pass

    def create_task(
        self,
        expert_mm_id: str,
        expert_channel_id: str,
        topic: str,
        methodologist_mm_id: str,
        methodologist_channel_id: str,
    ) -> str:
        task_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO tasks
                   (id, status, topic, expert_mm_id, expert_channel_id,
                    methodologist_mm_id, methodologist_channel_id,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (task_id, "INIT", topic, expert_mm_id, expert_channel_id,
                 methodologist_mm_id, methodologist_channel_id, now, now),
            )
        return task_id

    def get_task(self, task_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_task_by_channel(self, channel_id: str) -> Optional[dict]:
        """Returns active task for a channel (expert or methodologist side)."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM tasks
                   WHERE (expert_channel_id = ? OR methodologist_channel_id = ?)
                     AND status NOT IN ('DONE', 'CANCELLED', 'ERROR')
                   ORDER BY created_at DESC LIMIT 1""",
                (channel_id, channel_id),
            ).fetchone()
        return dict(row) if row else None

    def update_task(self, task_id: str, **kwargs) -> None:
        if not kwargs:
            return
        kwargs["updated_at"] = datetime.utcnow().isoformat()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?", values)
