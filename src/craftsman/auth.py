import keyring


class Auth:
    SERVICE_NAME = "craftsman"
    USERNAME_LIST = ["LLM_BASE_URL", "LLM_API_KEY", "LLM_SSL_CRT"]

    @staticmethod
    def __validate_username(username: str):
        if username not in Auth.USERNAME_LIST:
            raise ValueError(
                f"Username {username} is not recognized."
                f" Valid usernames are: {', '.join(Auth.USERNAME_LIST)}"
            )

    @staticmethod
    def set_password(username: str, password: str):
        """Stores the password securely using the keyring library."""
        Auth.__validate_username(username)
        keyring.set_password(Auth.SERVICE_NAME, username, password)

    @staticmethod
    def get_password(username: str) -> str | None:
        """Retrieves the stored password for the given service and username."""
        Auth.__validate_username(username)
        return keyring.get_password(Auth.SERVICE_NAME, username)

    @staticmethod
    def delete_password(username: str):
        """Deletes the stored password for the given service and username."""
        Auth.__validate_username(username)
        keyring.delete_password(Auth.SERVICE_NAME, username)
