import jwt
from fastapi import HTTPException, Request

from craftsman.crypto import Crypto

_crypto = Crypto()


async def get_current_user(request: Request) -> str:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    try:
        return _crypto.verify_token(token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401, detail="Invalid or expired token."
        )
