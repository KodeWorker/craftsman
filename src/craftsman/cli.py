import multiprocessing
import os
import shutil
from importlib.resources import files

import click

from craftsman.auth import Auth
from craftsman.client import Client
from craftsman.configure import get_config
from craftsman.crypto import Crypto
from craftsman.memory.structure import StructureDB

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS)
def main():
    """craftsman : an autonomous agent tool."""
    pass


@main.command()
def init():
    """Initializes the craftsman environment."""
    config = get_config()
    root_dir = os.path.expanduser(config["workspace"]["root"])
    os.makedirs(root_dir, exist_ok=True)
    os.makedirs(
        os.path.expanduser(config["workspace"]["database"]), exist_ok=True
    )
    os.makedirs(os.path.expanduser(config["workspace"]["logs"]), exist_ok=True)
    os.makedirs(
        os.path.expanduser(config["workspace"]["secrets"]), exist_ok=True
    )
    user_config = os.path.join(root_dir, "craftsman.yaml")
    if not os.path.exists(user_config):
        shutil.copy(
            str(files("craftsman").joinpath("craftsman.yaml")), user_config
        )
    click.echo(f"Craftsman environment initialized at {root_dir}")


@main.command()
@click.option("--port", default=6969, help="Port to listen on")
def server(port: int = 6969):
    """Starts an agent server."""
    from craftsman.server import Server

    _server = Server(port=port)
    _server.start()


@main.command()
@click.option("--host", default="localhost", help="Server host")
@click.option("--port", default=6969, help="Server port")
@click.option(
    "--resume",
    "session",
    default=None,
    is_flag=False,
    flag_value="",
    help="Resume a session. Omit value to pick from list.",
)
def chat(host: str = "localhost", port: int = 6969, session: str = None):
    """Connects to an agent server."""
    client = Client(host=host, port=port)
    if session is None:
        client.chat()
    elif session == "":
        session_id = client.pick_session()
        client.chat(session_id=session_id)
    else:
        session_id = client.find_session_id(session)
        client.chat(session_id=session_id)


@main.command()
@click.argument("prompt")
@click.option("--host", default="localhost", help="Server host")
@click.option("--port", default=6969, help="Server port")
def run(prompt, host: str = "localhost", port: int = 6969):
    """Runs an independent agent task."""
    client = Client(host=host, port=port)
    client.run(prompt)


@main.command()
@click.option("--port", default=6969, help="Port to listen on")
def dev(port: int = 6969):
    """Starts both server and client for development."""
    from craftsman.server import Server

    _server = Server(port=port)
    multiprocessing.Process(target=_server.start).start()
    client = Client(host="localhost", port=port)
    client.chat()


# --- Authentication Commands ---


@main.group(context_settings=CONTEXT_SETTINGS)
def auth():
    """Authentication management commands."""
    pass


@auth.command(name="list")
def auth_list():
    """Lists all authenticated agents."""
    for key in Auth.LLM_KEY_LIST:
        password = Auth.get_password(key)
        if password is not None:
            click.echo(f"{key}: {len(password) * '*'}")
        else:
            click.echo(f"{key}: Not set")


@auth.command(name="set")
@click.argument("key")
def auth_set(key: str):
    """Sets authentication details for a specific key."""
    password = click.prompt(f"Enter password for {key}", hide_input=True)
    Auth.set_password(key, password)
    click.echo(f"Password for {key} set successfully.")


@auth.command(name="get")
@click.argument("key")
def auth_get(key: str):
    """Gets authentication details for a specific key."""
    password = Auth.get_password(key)
    if password is not None:
        click.echo(f"{key}: {len(password) * '*'}")
    else:
        click.echo(f"{key}: Not set")


@auth.command(name="delete")
@click.argument("key", required=False)
def auth_delete(key: str = None):
    """
    Deletes authentication details for a specific key, or all keys
    if none is specified.
    """
    if key:
        if Auth.get_password(key) is not None:
            Auth.delete_password(key)
            click.echo(f"Password for {key} deleted.")
        else:
            click.echo(f"Password for {key} is not set.")
    else:
        for cred in Auth.LLM_KEY_LIST:
            if Auth.get_password(cred) is not None:
                Auth.delete_password(cred)
                click.echo(f"Password for {cred} deleted.")
            else:
                click.echo(f"Password for {cred} is not set.")


# --- User Management Commands ---


@main.group(context_settings=CONTEXT_SETTINGS)
def user():
    """User management commands."""
    pass


# --- Server User Commands ---


@user.command(name="list")
def user_list():
    for u in StructureDB().list_users():
        click.echo(f"{u['id'][:8]}  {u['username']}  {u['created_at']}")


@user.command(name="register")
def user_register():
    username = click.prompt("Username")
    password = click.prompt("Password", hide_input=True)
    click.prompt("Confirm password", hide_input=True)
    db = StructureDB()
    if db.get_user(username):
        click.echo(f"User '{username}' already exists.")
        return
    db.create_user(username, Crypto().hash_password(password))
    click.echo(f"User '{username}' registered successfully.")


@user.command(name="delete")
@click.argument("username")
def user_delete(username: str):
    db = StructureDB()
    if not db.get_user(username):
        click.echo(f"User '{username}' does not exist.")
        return
    db.delete_user(username)
    click.echo(f"User '{username}' deleted.")


# --- Client User Commands ---


@user.command(name="login")
def user_login():
    username = click.prompt("Username")
    password = click.prompt("Password", hide_input=True)
    Auth.set_password("USERNAME", username)
    Auth.set_password("PASSWORD", password)
    click.echo("User credentials saved.")


# --- Session Management Commands ---


@main.group(context_settings=CONTEXT_SETTINGS)
def sess():
    """Session management commands."""
    pass


@sess.command(name="list")
@click.option("--host", default="localhost", help="Server host")
@click.option("--port", default=6969, help="Server port")
@click.option(
    "--project-id", default=None, help="Project ID to filter sessions"
)
@click.option("--limit", default=5, help="Limit number of sessions listed")
def sess_list(
    host: str = "localhost",
    port: int = 6969,
    project_id: str = None,
    limit: int = 5,
):
    """Lists all sessions."""
    client = Client(host=host, port=port)
    session_infos = client.list_sessions(project_id=project_id, limit=limit)
    for session_info in session_infos:
        click.echo(session_info)


@sess.command(name="delete")
@click.argument("session")
@click.option("--host", default="localhost", help="Server host")
@click.option("--port", default=6969, help="Server port")
def sess_delete(
    session: str = None, host: str = "localhost", port: int = 6969
):
    """Deletes session by ID, prefix, or title."""
    client = Client(host=host, port=port)
    client.delete_session(session)
    click.echo(f"Session '{session}' deleted successfully.")
