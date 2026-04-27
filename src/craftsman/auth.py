import keyring


class Auth:
    SERVICE_NAME = "craftsman"
    LLM_KEY_LIST = [
        "LLM_API_KEY",
        "LLM_SSL_CRT",
    ]  # Extend this list as needed
    USER_KEY_LIST = [
        "USERNAME",
        "PASSWORD",
    ]  # Extend this list as needed
    TELEGRAM_KEY_LIST = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ]  # Extend this list as needed

    @staticmethod
    def __validate_key(key: str):
        if (
            key
            not in Auth.LLM_KEY_LIST
            + Auth.USER_KEY_LIST
            + Auth.TELEGRAM_KEY_LIST
        ):
            all_keys = ", ".join(
                Auth.LLM_KEY_LIST + Auth.USER_KEY_LIST + Auth.TELEGRAM_KEY_LIST
            )
            raise ValueError(
                f"Key {key} is not recognized. Valid keys are: {all_keys}"
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
