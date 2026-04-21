import keyring


class Auth:
    SERVICE_NAME = "craftsman"
    KEY_LIST = [
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_SSL_CRT",
        "USERNAME",
        "PASSWORD",
    ]  # Extend this list as needed

    @staticmethod
    def __validate_key(key: str):
        if key not in Auth.KEY_LIST:
            raise ValueError(
                f"Key {key} is not recognized."
                f" Valid keys are: {', '.join(Auth.KEY_LIST)}"
            )

    @staticmethod
    def set_password(key: str, password: str):
        """Stores the password securely using the keyring library."""
        Auth.__validate_key(key)
        keyring.set_password(Auth.SERVICE_NAME, key, password)

    @staticmethod
    def get_password(key: str) -> str | None:
        """Retrieves the stored password for the given service and key."""
        Auth.__validate_key(key)
        return keyring.get_password(Auth.SERVICE_NAME, key)

    @staticmethod
    def delete_password(key: str):
        """Deletes the stored password for the given service and key."""
        Auth.__validate_key(key)
        keyring.delete_password(Auth.SERVICE_NAME, key)
