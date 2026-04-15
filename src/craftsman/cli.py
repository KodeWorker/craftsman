import multiprocessing
import os

import click

from craftsman.auth import Auth
from craftsman.client import Client
from craftsman.server import Server

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS)
def main():
    """craftsman : an autonomous agent tool."""
    pass


@main.command()
def init():
    """Initializes the craftsman environment."""
    # Create necessary directories
    root_dir = os.path.expanduser("~/.craftsman")
    os.makedirs(root_dir, exist_ok=True)
    os.makedirs(os.path.join(root_dir, "workspace"), exist_ok=True)
    os.makedirs(os.path.join(root_dir, "database"), exist_ok=True)
    os.makedirs(os.path.join(root_dir, "logs"), exist_ok=True)
    click.echo("Craftsman environment initialized.")


@main.command()
@click.option("--port", default=6969, help="Port to listen on")
def server(port: int = 6969):
    """Starts an agent server."""
    server = Server(port=port)
    server.start()


@main.command()
@click.option("--host", default="localhost", help="Server host")
@click.option("--port", default=6969, help="Server port")
def client(host: str = "localhost", port: int = 6969):
    """Connects to an agent server."""
    client = Client(host=host, port=port)
    client.connect()


@main.command()
@click.option("--port", default=6969, help="Port to listen on")
def dev(port: int = 6969):
    """Starts both server and client for development."""
    server = Server(port=port)
    multiprocessing.Process(target=server.start).start()
    client = Client(host="localhost", port=port)
    client.connect()


@main.group(context_settings=CONTEXT_SETTINGS)
def auth():
    """Authentication management commands."""
    pass


@auth.command()
def list():
    """Lists all authenticated agents."""
    auth = Auth()
    for provider in auth.USERNAME_LIST:
        password = auth.get_password(provider)
        if password:
            click.echo(f"{provider}: {password}")
        else:
            click.echo(f"{provider}: Not set")


@auth.command()
@click.argument("provider")
def set(provider: str):
    """Sets authentication details for a specific provider."""
    auth = Auth()
    password = click.prompt(f"Enter password for {provider}", hide_input=True)
    auth.set_password(provider, password)
    click.echo(f"Password for {provider} set successfully.")


@auth.command()
@click.argument("provider")
def get(provider: str):
    """Gets authentication details for a specific provider."""
    auth = Auth()
    password = auth.get_password(provider)
    if password:
        click.echo(f"{provider}: {password}")
    else:
        click.echo(f"{provider}: Not set")


@auth.command()
@click.argument("provider", required=False)
def clear(provider: str = None):
    """
    Clears authentication details for a specific provider, or all providers
    if none is specified.
    """
    auth = Auth()
    if provider:
        auth.delete_password(provider)
        click.echo(f"Password for {provider} cleared.")
    else:
        for provider in auth.USERNAME_LIST:
            auth.delete_password(provider)
            click.echo(f"Password for {provider} cleared.")
