import click

from craftsman.client import Client
from craftsman.server import Server

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS)
def main():
    """craftsman : an autonomous agent tool."""
    pass


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
