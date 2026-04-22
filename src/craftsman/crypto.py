import hashlib
import os
import secrets
import tempfile
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from craftsman.configure import get_config
from craftsman.logger import CraftsmanLogger


class Crypto:

    def __init__(self):
        config = get_config()
        self.logger = CraftsmanLogger().get_logger(__name__)
        self.secret_key = os.path.expanduser(
            os.path.join(config["workspace"]["secrets"], "secret.key")
        )
        self.size = config["crypto"]["size"]
        self.algorithm = config["crypto"]["algorithm"]
        self.duration_hr = config["crypto"]["duration_hr"]
        self.__secret: str | None = None

    def __prehash(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    def hash_password(self, password: str) -> str:
        return bcrypt.hashpw(
            self.__prehash(password).encode(), bcrypt.gensalt()
        ).decode()

    def verify_password(self, password: str, hashed: str) -> bool:
        return bcrypt.checkpw(
            self.__prehash(password).encode(), hashed.encode()
        )

    def get_secret(self) -> str:
        if self.__secret is not None:
            return self.__secret

        if not os.path.exists(self.secret_key):
            secret = secrets.token_hex(self.size)
            dir_ = os.path.dirname(self.secret_key)
            with tempfile.NamedTemporaryFile(
                mode="w", dir=dir_, delete=False, encoding="utf-8"
            ) as f:
                f.write(secret)
                tmp_path = f.name
            os.replace(tmp_path, self.secret_key)
        else:
            with open(self.secret_key, "r", encoding="utf-8") as f:
                secret = f.read().strip()
                self.logger.info(
                    f"Loaded existing secret key from {self.secret_key}"
                )
        self.__secret = secret
        return secret

    def create_token(self, user_id: str) -> str:
        payload = {
            "sub": user_id,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc)
            + timedelta(hours=self.duration_hr),
        }
        secret = self.get_secret()
        token = jwt.encode(payload, secret, algorithm=self.algorithm)
        return token

    def verify_token(self, token: str) -> str:
        # catch exceptions on the caller side
        # to handle invalid or expired tokens
        secret = self.get_secret()
        payload = jwt.decode(token, secret, algorithms=[self.algorithm])
        return payload["sub"]
