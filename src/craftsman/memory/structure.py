import os
import sqlite3
import uuid
from pathlib import Path

from craftsman.configure import get_config

_DDL = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    title      TEXT,
    user_id    TEXT REFERENCES users(id) ON DELETE SET NULL,
    metadata   TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at   TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN (
                   'user', 'assistant', 'system',
                   'tool', 'summary', 'reasoning'
               )),
    content    TEXT NOT NULL,
    tokens     INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS global_facts (
    id                TEXT PRIMARY KEY,
    content           TEXT NOT NULL,
    source_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    source_project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    promoted_at       TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at        TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
    id         TEXT PRIMARY KEY,
    user_id    TEXT REFERENCES users(id) ON DELETE SET NULL,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    filepath   TEXT NOT NULL,
    filename   TEXT NOT NULL,
    mime_type  TEXT,
    size_bytes INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plans (
    id         TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    goal       TEXT NOT NULL,
    context    TEXT,
    status     TEXT NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active', 'done')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at   TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    plan_id     TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    criteria    TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN (
                        'pending', 'in_progress',
                        'verifying', 'done', 'failed'
                    )),
    output      TEXT,
    fail_reason TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tools (
    name        TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    category    TEXT NOT NULL,
    schema      TEXT NOT NULL,
    audited     INTEGER NOT NULL DEFAULT 0,
    call_count  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tool_invocations (
    id          TEXT PRIMARY KEY,
    session_id  TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    tool_name   TEXT NOT NULL,
    args        TEXT NOT NULL,
    result      TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    is_error    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id         TEXT PRIMARY KEY,
    user_id    TEXT REFERENCES users(id) ON DELETE SET NULL,
    tool_call  TEXT NOT NULL,
    run_at     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'running', 'done', 'failed')),
    result     TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cron_jobs (
    id          TEXT PRIMARY KEY,
    user_id     TEXT REFERENCES users(id) ON DELETE SET NULL,
    expression  TEXT NOT NULL,
    tool_call   TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    last_run    TEXT,
    last_result TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

"""


class StructureDB:
    def __init__(self, path: Path | None = None):
        self.config = get_config()
        if path is None:
            path = (
                Path(os.path.expanduser(self.config["workspace"]["database"]))
                / "craftsman.db"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(_DDL)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # --- projects ---

    def create_project(self, name: str, description: str = None) -> str:
        pid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO projects (id, name, description) VALUES (?, ?, ?)",
            (pid, name, description),
        )
        self.conn.commit()
        return pid

    def get_project(self, project_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()

    def list_projects(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC"
        ).fetchall()

    def update_project(self, project_id: str, **fields) -> None:
        allowed = {"name", "description"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = "datetime('now')"
        set_clause = ", ".join(
            f"{k} = datetime('now')" if k == "updated_at" else f"{k} = ?"
            for k in updates
        )
        values = [v for k, v in updates.items() if k != "updated_at"]
        values.append(project_id)
        self.conn.execute(
            f"UPDATE projects SET {set_clause} WHERE id = ?", values
        )
        self.conn.commit()

    def delete_project(self, project_id: str) -> None:
        self.conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self.conn.commit()

    # --- users ---
    def create_user(self, username: str, password_hash: str) -> dict:
        uid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO users (id, username, password_hash)"
            " VALUES (?, ?, ?)",
            (uid, username, password_hash),
        )
        self.conn.commit()
        return {"id": uid, "username": username}

    def get_user(self, username: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

    def list_users(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM users ORDER BY username"
        ).fetchall()

    def delete_user(self, username: str) -> None:
        self.conn.execute("DELETE FROM users WHERE username = ?", (username,))
        self.conn.commit()

    # --- sessions ---

    def create_session(
        self,
        project_id: str = None,
        title: str = None,
        user_id: str = None,
        metadata: str = None,
    ) -> str:
        sid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO sessions (id, project_id, title, user_id, metadata)"
            " VALUES (?, ?, ?, ?, ?)",
            (sid, project_id, title, user_id, metadata),
        )
        self.conn.commit()
        return sid

    def get_session(self, session_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

    def resolve_session(self, query: str) -> sqlite3.Row | None:
        """Match session by exact id, id prefix, or title."""
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (query,)
        ).fetchone()
        if row:
            return row
        rows = self.conn.execute(
            "SELECT * FROM sessions WHERE id LIKE ?", (query + "%",)
        ).fetchall()
        if len(rows) == 1:
            return rows[0]
        return self.conn.execute(
            "SELECT * FROM sessions WHERE title = ?", (query,)
        ).fetchone()

    def list_sessions(
        self, project_id: str = None, user_id: str = None, limit: int = None
    ) -> list[sqlite3.Row]:
        clauses = []
        params = []
        if project_id:
            clauses.append("s.project_id = ?")
            params.append(project_id)
        if user_id:
            clauses.append("s.user_id = ?")
            params.append(user_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        limit_clause = " LIMIT ?" if limit is not None else ""
        if limit is not None:
            params.append(limit)
        return self.conn.execute(
            f"""
            SELECT s.*, m.content AS last_input, m.created_at AS last_input_at
            FROM sessions s
            JOIN (
                SELECT session_id, content, created_at
                FROM messages
                WHERE role = 'user'
                GROUP BY session_id
                HAVING created_at = MAX(created_at)
            ) m ON m.session_id = s.id
            {where}
            ORDER BY s.created_at DESC{limit_clause}
            """,
            params,
        ).fetchall()

    def end_session(self, session_id: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET ended_at = datetime('now') WHERE id = ?",
            (session_id,),
        )
        self.conn.commit()

    def delete_session(self, session_id: str) -> None:
        self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self.conn.commit()

    # --- messages ---

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tokens: int = None,
    ) -> str:
        mid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO messages (id, session_id, role, content, tokens)"
            " VALUES (?, ?, ?, ?, ?)",
            (mid, session_id, role, content, tokens),
        )
        self.conn.commit()
        return mid

    def get_messages(self, session_id: str) -> list[sqlite3.Row]:
        # Find the most recent summary checkpoint; return it + everything after
        row = self.conn.execute(
            "SELECT rowid FROM messages"
            " WHERE session_id = ? AND role = 'summary'"
            " ORDER BY rowid DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row:
            return self.conn.execute(
                "SELECT * FROM messages WHERE session_id = ?"
                " AND rowid >= ? ORDER BY rowid ASC",
                (session_id, row["rowid"]),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM messages WHERE session_id = ?"
            " ORDER BY rowid ASC",
            (session_id,),
        ).fetchall()

    # --- global_facts ---

    def add_global_fact(
        self,
        content: str,
        source_session_id: str = None,
        source_project_id: str = None,
        expires_at: str = None,
    ) -> str:
        fid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO global_facts"
            " (id, content, source_session_id, source_project_id, expires_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (fid, content, source_session_id, source_project_id, expires_at),
        )
        self.conn.commit()
        return fid

    def get_global_facts(
        self, include_expired: bool = False
    ) -> list[sqlite3.Row]:
        if include_expired:
            return self.conn.execute(
                "SELECT * FROM global_facts ORDER BY promoted_at DESC"
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM global_facts"
            " WHERE expires_at IS NULL OR expires_at > datetime('now')"
            " ORDER BY promoted_at DESC"
        ).fetchall()

    def delete_global_fact(self, fact_id: str) -> None:
        self.conn.execute("DELETE FROM global_facts WHERE id = ?", (fact_id,))
        self.conn.commit()

    # --- artifacts ---

    def add_artifact(
        self,
        filepath: str,
        filename: str,
        user_id: str = None,
        session_id: str = None,
        project_id: str = None,
        mime_type: str = None,
        size_bytes: int = None,
    ) -> str:
        aid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO artifacts"
            " (id, user_id, session_id, project_id,"
            " filepath, filename, mime_type, size_bytes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                aid,
                user_id,
                session_id,
                project_id,
                filepath,
                filename,
                mime_type,
                size_bytes,
            ),
        )
        self.conn.commit()
        return aid

    def update_artifact(
        self, artifact_id: str, filepath: str, size_bytes: int
    ) -> None:
        self.conn.execute(
            "UPDATE artifacts SET filepath = ?, size_bytes = ? WHERE id = ?",
            (filepath, size_bytes, artifact_id),
        )
        self.conn.commit()

    def resolve_artifact_id(self, prefix: str) -> str | None:
        rows = self.conn.execute(
            "SELECT id FROM artifacts WHERE id LIKE ?",
            (f"{prefix}%",),
        ).fetchall()
        if len(rows) == 1:
            return rows[0]["id"]
        return None

    def get_artifact(self, artifact_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()

    def get_artifacts(
        self,
        user_id: str = None,
        session_id: str = None,
        project_id: str = None,
    ) -> list[sqlite3.Row]:
        if session_id:
            return self.conn.execute(
                "SELECT * FROM artifacts WHERE session_id = ?"
                " ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        if project_id:
            return self.conn.execute(
                "SELECT * FROM artifacts WHERE project_id = ?"
                " ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        if user_id:
            return self.conn.execute(
                "SELECT * FROM artifacts WHERE user_id = ?"
                " ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM artifacts ORDER BY created_at DESC"
        ).fetchall()

    def delete_artifact(self, artifact_id: str) -> None:
        self.conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
        self.conn.commit()

    # --- plans ---

    def create_plan(
        self, goal: str, session_id: str = None, context: str = None
    ) -> str:
        pid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO plans (id, session_id, goal, context)"
            " VALUES (?, ?, ?, ?)",
            (pid, session_id, goal, context),
        )
        self.conn.commit()
        return pid

    def get_plan(self, plan_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM plans WHERE id = ?", (plan_id,)
        ).fetchone()

    def complete_plan(self, plan_id: str) -> None:
        self.conn.execute(
            "UPDATE plans SET status = 'done', ended_at = datetime('now')"
            " WHERE id = ?",
            (plan_id,),
        )
        self.conn.commit()

    # --- tasks ---

    def create_task(
        self,
        plan_id: str,
        description: str,
        criteria: str = None,
    ) -> str:
        tid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO tasks (id, plan_id, description, criteria)"
            " VALUES (?, ?, ?, ?)",
            (tid, plan_id, description, criteria),
        )
        self.conn.commit()
        return tid

    def get_task(self, task_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()

    def list_tasks(self, plan_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE plan_id = ? ORDER BY created_at ASC",
            (plan_id,),
        ).fetchall()

    def update_task_status(
        self,
        task_id: str,
        status: str,
        output: str = None,
        fail_reason: str = None,
    ) -> None:
        self.conn.execute(
            "UPDATE tasks SET status = ?, output = ?, fail_reason = ?,"
            " updated_at = datetime('now') WHERE id = ?",
            (status, output, fail_reason, task_id),
        )
        self.conn.commit()

    # --- tools ---

    def register_tool(
        self,
        name: str,
        description: str,
        category: str,
        schema: str,
        audited: bool = False,
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO tools"
            " (name, description, category, schema, audited)"
            " VALUES (?, ?, ?, ?, ?)",
            (name, description, category, schema, int(audited)),
        )
        self.conn.commit()

    def log_tool_invocation(
        self,
        session_id: str | None,
        tool_name: str,
        args: str,
        result: str,
        duration_ms: int,
        is_error: bool = False,
    ) -> None:
        self.conn.execute(
            "INSERT INTO tool_invocations"
            " (id, session_id, tool_name, args, result, duration_ms, is_error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                session_id,
                tool_name,
                args,
                result,
                duration_ms,
                int(is_error),
            ),
        )
        self.conn.commit()

    def get_tool(self, name: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM tools WHERE name = ?", (name,)
        ).fetchone()

    def search_tools(self, keyword: str) -> list[sqlite3.Row]:
        escaped = (
            keyword.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        return self.conn.execute(
            "SELECT * FROM tools"
            " WHERE name LIKE ? OR description LIKE ?"
            " ESCAPE '\\' ORDER BY name",
            (pattern, pattern),
        ).fetchall()

    def list_tools(self, category: str = None) -> list[sqlite3.Row]:
        if category:
            return self.conn.execute(
                "SELECT * FROM tools WHERE category = ? ORDER BY name",
                (category,),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM tools ORDER BY name"
        ).fetchall()

    def increment_tool_call_count(self, name: str) -> None:
        self.conn.execute(
            "UPDATE tools SET call_count = call_count + 1 WHERE name = ?",
            (name,),
        )
        self.conn.commit()

    # --- scheduled_jobs ---

    def schedule_job(
        self, tool_call: str, run_at: str, user_id: str | None = None
    ) -> str:
        jid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO scheduled_jobs (id, user_id, tool_call, run_at)"
            " VALUES (?, ?, ?, ?)",
            (jid, user_id, tool_call, run_at),
        )
        self.conn.commit()
        return jid

    def get_due_jobs(self, user_id: str | None = None) -> list[sqlite3.Row]:
        if user_id:
            return self.conn.execute(
                "SELECT * FROM scheduled_jobs"
                " WHERE status = 'pending' AND run_at <= datetime('now')"
                " AND user_id = ?"
                " ORDER BY run_at ASC",
                (user_id,),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM scheduled_jobs"
            " WHERE status = 'pending' AND run_at <= datetime('now')"
            " ORDER BY run_at ASC"
        ).fetchall()

    def update_job_status(
        self, job_id: str, status: str, result: str = None
    ) -> None:
        self.conn.execute(
            "UPDATE scheduled_jobs SET status = ?, result = ? WHERE id = ?",
            (status, result, job_id),
        )
        self.conn.commit()

    # --- cron_jobs ---

    def create_cron_job(
        self,
        expression: str,
        tool_call: str,
        user_id: str | None = None,
    ) -> str:
        cid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO cron_jobs (id, user_id, expression, tool_call)"
            " VALUES (?, ?, ?, ?)",
            (cid, user_id, expression, tool_call),
        )
        self.conn.commit()
        return cid

    def list_cron_jobs(
        self, active_only: bool = True, user_id: str | None = None
    ) -> list[sqlite3.Row]:
        if active_only and user_id:
            return self.conn.execute(
                "SELECT * FROM cron_jobs WHERE active = 1 AND user_id = ?"
                " ORDER BY created_at",
                (user_id,),
            ).fetchall()
        if active_only:
            return self.conn.execute(
                "SELECT * FROM cron_jobs WHERE active = 1 ORDER BY created_at"
            ).fetchall()
        if user_id:
            return self.conn.execute(
                "SELECT * FROM cron_jobs"
                " WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM cron_jobs ORDER BY created_at"
        ).fetchall()

    def update_cron_last_run(
        self, cron_id: str, result: str | None = None
    ) -> None:
        self.conn.execute(
            "UPDATE cron_jobs"
            " SET last_run = datetime('now'), last_result = ?"
            " WHERE id = ?",
            (result, cron_id),
        )
        self.conn.commit()

    def set_cron_active(self, cron_id: str, active: bool) -> None:
        self.conn.execute(
            "UPDATE cron_jobs SET active = ? WHERE id = ?",
            (1 if active else 0, cron_id),
        )
        self.conn.commit()

    def delete_cron_job(self, cron_id: str) -> None:
        self.conn.execute("DELETE FROM cron_jobs WHERE id = ?", (cron_id,))
        self.conn.commit()

    def list_scheduled_jobs(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM scheduled_jobs"
            " WHERE status = 'pending' ORDER BY run_at ASC"
        ).fetchall()

    def cancel_scheduled_job(self, job_id: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM scheduled_jobs WHERE id = ? AND status = 'pending'",
            (job_id,),
        )
        self.conn.commit()
        return cur.rowcount > 0
