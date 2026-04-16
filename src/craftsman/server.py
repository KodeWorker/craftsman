from craftsman.logger import CraftsmanLogger


class Server:
    def __init__(self, port: int):
        self.port = port
        self.logger = CraftsmanLogger().get_logger(__name__)

    def start(self):
        # TODO: Implement server startup logic
        self.logger.info(f"Starting server on port {self.port}...")
