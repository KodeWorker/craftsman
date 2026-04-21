# Phase 2: User Registry + Auth

## Goals

Add a user registry to the server and JWT-based login to the client. Sessions are
scoped to the authenticated user.

Dev mode: drop old DB (`rm ~/.craftsman/database/craftsman.db`), no migration.

---

## New dependencies

```toml
PyJWT>=2.8
passlib[bcrypt]>=1.7
```

---

## Design

### DB changes — `src/craftsman/memory/structure.py`

New `users` table in DDL:

```sql
CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
```

`sessions` table gets a new column:

```sql
user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
```

New `StructureDB` methods:
- `create_user(username, password_hash) -> dict`
- `get_user_by_username(username) -> dict | None`
- `create_session(project_id, user_id=None)` — update signature
- `list_sessions(project_id, limit, user_id=None)` — filter by `user_id`

### JWT utilities — `src/craftsman/jwt_utils.py` (new)

- `get_secret() -> str` — read `~/.craftsman/database/server_secret.key`; generate and write random 32-byte hex on first call
- `create_token(user_id: str) -> str` — sign JWT `{"sub": user_id, "exp": now + 8h}`
- `decode_token(token: str) -> str` — return `user_id`; raise `HTTPException(401)` on invalid or expired token

### Auth router — `src/craftsman/router/auth.py` (new)

Class `AuthRouter`, prefix `/auth`, takes `Librarian` in constructor:

| Endpoint | Body | Response |
|---|---|---|
| `POST /auth/register` | `{username, password}` | `{user_id}` |
| `POST /auth/login` | `{username, password}` | `{token}` |

`register`: hash with `passlib.hash.bcrypt`, call `structure_db.create_user()`.
`login`: fetch user, `bcrypt.verify()`, return `create_token(user_id)`.

### Server — `src/craftsman/server.py`

- Include `AuthRouter`
- Add `get_current_user` FastAPI dependency:
  ```python
  async def get_current_user(request: Request) -> str:
      token = request.headers.get("Authorization", "").removeprefix("Bearer ")
      return decode_token(token)  # raises 401 if invalid
  ```
- Import and use in `SessionsRouter` handlers via `Depends`

### Sessions router — `src/craftsman/router/sessions.py`

Add `user_id: str = Depends(get_current_user)` to:
- `create_session` — pass `user_id` to `structure_db.create_session()`
- `list_sessions` — pass `user_id` to `structure_db.list_sessions()`
- All other handlers — `Depends` for auth enforcement, value unused

### Client — `src/craftsman/client.py` + `src/craftsman/cli.py`

**Auth keyring**: add `CRAFTSMAN_TOKEN` to `Auth.USERNAME_LIST` in `auth.py`.

**`Client.login()` method** — prompts credentials, POSTs to `/auth/login`, stores token:

```python
def login(self):
    username = click.prompt("Username")
    password = click.prompt("Password", hide_input=True)
    resp = requests.post(f"{self.entry_point}/auth/login",
                         json={"username": username, "password": password})
    if resp.status_code != 200:
        raise SystemExit("Login failed.")
    Auth.set_password("CRAFTSMAN_TOKEN", resp.json()["token"])
    click.echo("Logged in.")
```

**New `craftsman auth login` CLI command** in `cli.py` (under existing `auth` group):

```python
@auth.command(name="login")
@click.option("--host", default="localhost")
@click.option("--port", default=6969)
def auth_login(host, port):
    Client(host=host, port=port).login()
```

**`chat()` and `run()`**: read `CRAFTSMAN_TOKEN` from keyring at start. If missing, exit with `"Run 'craftsman auth login' first."`. If server returns 401, clear token from keyring and exit with same message. Add `headers={"Authorization": f"Bearer {self.token}"}` to all requests.

---

## Files to change

| File | Change |
|---|---|
| `pyproject.toml` | Add `PyJWT`, `passlib[bcrypt]` |
| `src/craftsman/memory/structure.py` | `users` table, `user_id` on sessions, new methods |
| `src/craftsman/jwt_utils.py` | New — JWT sign/verify + secret management |
| `src/craftsman/router/auth.py` | New — register + login endpoints |
| `src/craftsman/router/sessions.py` | Add `Depends(get_current_user)` to handlers |
| `src/craftsman/server.py` | Include `AuthRouter`, define `get_current_user` |
| `src/craftsman/auth.py` | Add `CRAFTSMAN_TOKEN` to `USERNAME_LIST` |
| `src/craftsman/client.py` | `login()` method, read token + auth headers in `chat()`/`run()` |
| `src/craftsman/cli.py` | Add `craftsman auth login` command under `auth` group |
| `docs/schema.md` | Document `users` table and `user_id` on sessions |

---

## Verification

```bash
# Reset DB
rm ~/.craftsman/database/craftsman.db

# Start server
uv run craftsman server

# Register
curl -X POST http://localhost:6969/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret"}'

# Start client — prompts for login, stores token, then enters chat
uv run craftsman chat

# Verify session scoping: different user sees empty session list
```
