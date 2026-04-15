class Client:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def connect(self):
        # TODO: Implement connection logic to the server
        print(f"Connecting to server at {self.host}:{self.port}...")
