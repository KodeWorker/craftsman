from unittest.mock import MagicMock

import jwt
import pytest

FAKE_CONFIG = {
    "crypto": {"size": 32, "algorithm": "HS256", "duration_hr": 1},
    "workspace": {"secrets": ""},  # overridden per-fixture via tmp_path
}


@pytest.fixture
def crypto(mocker, tmp_path):
    config = {
        "crypto": {"size": 32, "algorithm": "HS256", "duration_hr": 1},
        "workspace": {"secrets": str(tmp_path)},
    }
    mocker.patch("craftsman.crypto.get_config", return_value=config)
    mocker.patch(
        "craftsman.crypto.CraftsmanLogger"
    ).return_value.get_logger.return_value = MagicMock()
    from craftsman.crypto import Crypto

    return Crypto()


# --- password hashing ---


def test_hash_password_not_plaintext(crypto):
    h = crypto.hash_password("mypassword")
    assert h != "mypassword"
    assert h.startswith("$2b$")


def test_verify_password_correct(crypto):
    h = crypto.hash_password("secret")
    assert crypto.verify_password("secret", h) is True


def test_verify_password_wrong(crypto):
    h = crypto.hash_password("secret")
    assert crypto.verify_password("wrong", h) is False


# --- secret key ---


def test_get_secret_creates_file(crypto, tmp_path):
    secret = crypto.get_secret()
    key_file = tmp_path / "secret.key"
    assert key_file.exists()
    assert key_file.read_text().strip() == secret


def test_get_secret_cached(crypto, tmp_path):
    s1 = crypto.get_secret()
    s2 = crypto.get_secret()
    assert s1 == s2


def test_get_secret_loads_existing(crypto, tmp_path):
    (tmp_path / "secret.key").write_text("existingsecret")
    crypto._Crypto__secret = None  # clear cache
    assert crypto.get_secret() == "existingsecret"


# --- JWT tokens ---


def test_create_and_verify_token(crypto):
    token = crypto.create_token("user-123")
    assert crypto.verify_token(token) == "user-123"


def test_verify_token_invalid_raises(crypto):
    with pytest.raises(jwt.PyJWTError):
        crypto.verify_token("not.a.token")


def test_verify_token_wrong_secret(crypto, mocker, tmp_path):
    token = crypto.create_token("user-1")
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    config = {
        "crypto": {"size": 32, "algorithm": "HS256", "duration_hr": 1},
        "workspace": {"secrets": str(other_dir)},
    }
    mocker.patch("craftsman.crypto.get_config", return_value=config)
    from craftsman.crypto import Crypto

    other = Crypto()
    with pytest.raises(jwt.PyJWTError):
        other.verify_token(token)
