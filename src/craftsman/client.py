from craftsman.logger import CraftsmanLogger


class Client:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.logger = CraftsmanLogger().get_logger(__name__)

    def connect(self):
        # TODO: Implement connection logic to the server
        self.logger.info(f"Connecting to server at {self.host}:{self.port}...")
