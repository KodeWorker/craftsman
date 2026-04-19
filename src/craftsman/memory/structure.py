import sqlite3
import uuid
from pathlib import Path

DB_PATH = Path.home() / ".craftsman" / "database" / "craftsman.db"

_DDL = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    title      TEXT,
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
    call_count  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tool_macros (
    name       TEXT PRIMARY KEY,
    steps      TEXT NOT NULL,
    scope      TEXT NOT NULL DEFAULT 'session'
                   CHECK (scope IN ('session', 'global')),
    session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id         TEXT PRIMARY KEY,
    tool_call  TEXT NOT NULL,
    run_at     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'running', 'done', 'failed')),
    result     TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cron_jobs (
    id         TEXT PRIMARY KEY,
    expression TEXT NOT NULL,
    tool_call  TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    last_run   TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class StructureDB:
    def __init__(self, path: Path = DB_PATH):
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

    # --- sessions ---

    def create_session(
        self,
        project_id: str = None,
        title: str = None,
        metadata: str = None,
    ) -> str:
        sid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO sessions (id, project_id, title, metadata)"
            " VALUES (?, ?, ?, ?)",
            (sid, project_id, title, metadata),
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
        self, project_id: str = None, limit: int = None
    ) -> list[sqlite3.Row]:
        limit_clause = " LIMIT ?" if limit is not None else ""
        has_messages = (
            "EXISTS (SELECT 1 FROM messages WHERE "
            "messages.session_id = sessions.id)"
        )
        if project_id:
            params = (
                (project_id, limit) if limit is not None else (project_id,)
            )
            return self.conn.execute(
                f"SELECT * FROM sessions WHERE "
                f"project_id = ? AND {has_messages}"
                f" ORDER BY created_at DESC{limit_clause}",
                params,
            ).fetchall()
        params = (limit,) if limit is not None else ()
        return self.conn.execute(
            f"SELECT * FROM sessions WHERE {has_messages}"
            f" ORDER BY created_at DESC{limit_clause}",
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
            "SELECT created_at FROM messages"
            " WHERE session_id = ? AND role = 'summary'"
            " ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row:
            return self.conn.execute(
                "SELECT * FROM messages WHERE session_id = ?"
                " AND created_at >= ? ORDER BY created_at ASC",
                (session_id, row["created_at"]),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM messages WHERE session_id = ?"
            " ORDER BY created_at ASC",
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
        session_id: str = None,
        project_id: str = None,
        mime_type: str = None,
        size_bytes: int = None,
    ) -> str:
        aid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO artifacts"
            " (id, session_id, project_id,"
            " filepath, filename, mime_type, size_bytes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                aid,
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

    def get_artifacts(
        self,
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
        return self.conn.execute(
            "SELECT * FROM artifacts ORDER BY created_at DESC"
        ).fetchall()

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
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO tools"
            " (name, description, category, schema)"
            " VALUES (?, ?, ?, ?)",
            (name, description, category, schema),
        )
        self.conn.commit()

    def get_tool(self, name: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM tools WHERE name = ?", (name,)
        ).fetchone()

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

    # --- tool_macros ---

    def create_macro(
        self,
        name: str,
        steps: str,
        scope: str = "session",
        session_id: str = None,
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO tool_macros"
            " (name, steps, scope, session_id) VALUES (?, ?, ?, ?)",
            (name, steps, scope, session_id),
        )
        self.conn.commit()

    def get_macro(self, name: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM tool_macros WHERE name = ?", (name,)
        ).fetchone()

    def list_macros(self, scope: str = None) -> list[sqlite3.Row]:
        if scope:
            return self.conn.execute(
                "SELECT * FROM tool_macros WHERE scope = ? ORDER BY name",
                (scope,),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM tool_macros ORDER BY name"
        ).fetchall()

    def delete_macro(self, name: str) -> None:
        self.conn.execute("DELETE FROM tool_macros WHERE name = ?", (name,))
        self.conn.commit()

    # --- scheduled_jobs ---

    def schedule_job(self, tool_call: str, run_at: str) -> str:
        jid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO scheduled_jobs (id, tool_call, run_at)"
            " VALUES (?, ?, ?)",
            (jid, tool_call, run_at),
        )
        self.conn.commit()
        return jid

    def get_due_jobs(self) -> list[sqlite3.Row]:
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

    def create_cron_job(self, expression: str, tool_call: str) -> str:
        cid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO cron_jobs (id, expression, tool_call)"
            " VALUES (?, ?, ?)",
            (cid, expression, tool_call),
        )
        self.conn.commit()
        return cid

    def list_cron_jobs(self, active_only: bool = True) -> list[sqlite3.Row]:
        if active_only:
            return self.conn.execute(
                "SELECT * FROM cron_jobs WHERE active = 1 ORDER BY created_at"
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM cron_jobs ORDER BY created_at"
        ).fetchall()

    def update_cron_last_run(self, cron_id: str) -> None:
        self.conn.execute(
            "UPDATE cron_jobs SET last_run = datetime('now') WHERE id = ?",
            (cron_id,),
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
