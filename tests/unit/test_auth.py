import pytest

from craftsman.auth import Auth


@pytest.fixture(autouse=True)
def mock_keyring(mocker):
    return mocker.patch("craftsman.auth.keyring")


def test_set_password_calls_keyring(mock_keyring):
    Auth.set_password("LLM_API_KEY", "secret")
    mock_keyring.set_password.assert_called_once_with(
        "craftsman", "LLM_API_KEY", "secret"
    )


def test_set_password_rejects_unknown_username():
    with pytest.raises(ValueError, match="not recognized"):
        Auth.set_password("UNKNOWN", "secret")


@pytest.mark.parametrize(
    "username",
    ["LLM_BASE_URL", "LLM_API_KEY", "LLM_SSL_CRT", "USERNAME", "PASSWORD"],
)
def test_set_password_all_valid_keys_accepted(username, mock_keyring):
    Auth.set_password(username, "val")
    mock_keyring.set_password.assert_called_once()


def test_set_password_user_keys_accepted(mock_keyring):
    Auth.set_password("USERNAME", "alice")
    Auth.set_password("PASSWORD", "secret")
    assert mock_keyring.set_password.call_count == 2


def test_get_password_returns_value(mock_keyring):
    mock_keyring.get_password.return_value = "abc"
    assert Auth.get_password("LLM_API_KEY") == "abc"


def test_get_password_returns_none_when_not_set(mock_keyring):
    mock_keyring.get_password.return_value = None
    assert Auth.get_password("LLM_API_KEY") is None


def test_get_password_rejects_unknown_username():
    with pytest.raises(ValueError, match="not recognized"):
        Auth.get_password("BAD")


def test_delete_password_delegates_to_keyring(mock_keyring):
    Auth.delete_password("LLM_SSL_CRT")
    mock_keyring.delete_password.assert_called_once_with(
        "craftsman", "LLM_SSL_CRT"
    )


def test_delete_password_rejects_unknown_username():
    with pytest.raises(ValueError, match="not recognized"):
        Auth.delete_password("NOPE")
