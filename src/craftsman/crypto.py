import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from passlib.hash import bcrypt

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

    def hash_password(self, password: str) -> str:
        return bcrypt.hash(password)

    def verify_password(self, password: str, hashed: str) -> bool:
        return bcrypt.verify(password, hashed)

    def get_secret(self) -> str:
        if not os.path.exists(self.secret_key):
            with open(self.secret_key, "w", encoding="utf-8") as f:
                secret = secrets.token_hex(self.size)
                f.write(secret)
                self.logger.info(
                    f"Generated new secret key at {self.secret_key}"
                )
        else:
            with open(self.secret_key, "r", encoding="utf-8") as f:
                secret = f.read().strip()
                self.logger.info(
                    f"Loaded existing secret key from {self.secret_key}"
                )
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
