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
- `list_users() -> list`
- `delete_user(username) -> None`
- `create_session(project_id, user_id=None)` — update signature
- `list_sessions(project_id, limit, user_id=None)` — filter by `user_id`

### JWT utilities — `src/craftsman/crypto.py` (new)

* Implementation note: add secrets directory in worksapce and crypto configs

- `get_secret() -> str` — read `~/.craftsman/database/server_secret.key`; generate and write random 32-byte hex on first call
- `create_token(user_id: str) -> str` — sign JWT `{"sub": user_id, "exp": now + 8h}`
- `decode_token(token: str) -> str` — return `user_id`; raise `HTTPException(401)` on invalid or expired token

### User router — `src/craftsman/router/users.py` (new)

* Implementation note: only one endpoint -> no need for new router
* Add hash_password and verify_password in crypto.py

Class `UserRouter`, prefix `/users`, takes `Librarian` in constructor.

Only login goes through HTTP — register/list/delete are direct DB operations from the CLI:

| Endpoint | Body | Response |
|---|---|---|
| `POST /users/login` | `{username, password}` | `{token}` |

`login`: fetch user via `get_user_by_username()`, `bcrypt.verify()`, return `create_token(user_id)`.

### Server — `src/craftsman/server.py`

- Include `UserRouter`

### Router dependencies — `src/craftsman/router/deps.py` (new)

```python
from fastapi import Request
from craftsman.jwt_utils import decode_token

async def get_current_user(request: Request) -> str:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    return decode_token(token)
```

Imported by `sessions.py` and ~~`user.py`~~ `server.py` via `from craftsman.router.deps import get_current_user`.

* Implementation note: `verify_token` raises `jwt.PyJWTError` on failure — `deps.py` catches it and raises `HTTPException(401)`. Import is `from craftsman.crypto import Crypto`, not `jwt_utils`.

### Sessions router — `src/craftsman/router/sessions.py`

Add `user_id: str = Depends(get_current_user)` to:
- `create_session` — pass `user_id` to `structure_db.create_session()`
- `list_sessions` — pass `user_id` to `structure_db.list_sessions()`
- All other handlers — `Depends` for auth enforcement, value unused

### CLI — `src/craftsman/cli.py` + `src/craftsman/client.py`

* Implementation note: `USERNAME`, `PASSWORD` added to `auth.py` for client

**Auth keyring**: drop `USERNAME_LIST` whitelist from `auth.py` — validation is redundant since the DB owns the user registry. Use `Auth` directly for any keyring key.

**Server-side commands** (direct DB, no server running required) — in `cli.py` `user` group, use `StructureDB` + `passlib` directly:

```python
@user.command(name="register")
def user_register():
    username = click.prompt("Username")
    password = click.prompt("Password", hide_input=True)
    click.prompt("Confirm password", hide_input=True)
    db = StructureDB()
    if db.get_user_by_username(username):
        raise SystemExit("User already exists.")
    db.create_user(username, bcrypt.hash(password))
    click.echo("User registered.")

@user.command(name="list")
def user_list():
    for u in StructureDB().list_users():
        click.echo(f"{u['id'][:8]}  {u['username']}  {u['created_at']}")

@user.command(name="delete")
@click.argument("username")
def user_delete(username):
    StructureDB().delete_user(username)
    click.echo(f"User '{username}' deleted.")
```

**Client-side command** — `user login` stores credentials in keyring (no server needed):

```python
@user.command(name="login")
def user_login():
    username = click.prompt("Username")
    password = click.prompt("Password", hide_input=True)
    Auth.set_password("CRAFTSMAN_USER", username)
    Auth.set_password("CRAFTSMAN_PASSWORD", password)
    click.echo("Credentials saved.")
```

**`Client` token flow** — `self.token` held in memory, never persisted:

```python
def _fetch_token(self) -> str:
    username = Auth.get_password("CRAFTSMAN_USER")
    password = Auth.get_password("CRAFTSMAN_PASSWORD")
    if not username or not password:
        raise SystemExit("Run 'craftsman user login' first.")
    resp = requests.post(f"{self.entry_point}/user/login",
                         json={"username": username, "password": password})
    if resp.status_code != 200:
        raise SystemExit("Login failed. Check credentials with 'craftsman user login'.")
    return resp.json()["token"]
```

- `chat()` and `run()`: call `self.token = self._fetch_token()` after health check
- All requests use `headers={"Authorization": f"Bearer {self.token}"}`
- On any 401 response: call `self.token = self._fetch_token()` and retry once

---

## Files to change

| File | Change |
|---|---|
| `pyproject.toml` | Add `PyJWT`, `passlib[bcrypt]` |
| `src/craftsman/memory/structure.py` | `users` table, `user_id` on sessions, new methods |
| `src/craftsman/crypto.py` | New — JWT sign/verify + secret management |
| `src/craftsman/router/deps.py` | New — `get_current_user` FastAPI dependency |
| `src/craftsman/router/user.py` | New — login endpoint only |
| `src/craftsman/router/sessions.py` | Add `Depends(get_current_user)` to handlers |
| `src/craftsman/server.py` | Include `AuthRouter`, define `get_current_user` |
| `src/craftsman/auth.py` | Renamed `USERNAME_LIST` → `KEY_LIST`, `__validate_username` → `__validate_key` ✓ done |
| `src/craftsman/cli.py` | Updated to use `KEY_LIST`, `key` arg naming ✓ done |
| `src/craftsman/client.py` | `_fetch_token()`, in-memory `self.token`, auth headers + 401 retry in `chat()`/`run()` |
| `src/craftsman/cli.py` | Add `user` group: `register`, `list`, `delete` (direct DB); `login` (client HTTP) |
| `docs/schema.md` | Document `users` table and `user_id` on sessions |

---

## Verification

```bash
# Reset DB
rm ~/.craftsman/database/craftsman.db

# Start server
uv run craftsman server

# Register a user (no server needed)
uv run craftsman user register

# Save credentials to keyring (no server needed)
uv run craftsman user login

# Start client
uv run craftsman chat

# Verify session scoping: different user sees empty session list
```
