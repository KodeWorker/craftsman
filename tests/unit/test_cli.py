import pytest
from click.testing import CliRunner

from craftsman.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_config(mocker):
    return mocker.patch(
        "craftsman.cli.get_config",
        return_value={
            "workspace": {
                "root": "/tmp/craftsman-test",
                "database": "/tmp/craftsman-test/database",
                "logs": "/tmp/craftsman-test/logs",
            }
        },
    )


@pytest.fixture
def mock_makedirs(mocker):
    return mocker.patch("craftsman.cli.os.makedirs")


@pytest.fixture
def mock_auth(mocker):
    mock_cls = mocker.patch("craftsman.cli.Auth")
    mock_cls.USERNAME_LIST = ["LLM_BASE_URL", "LLM_API_KEY", "LLM_SSL_CRT"]
    mock_cls.get_password.return_value = None
    return mock_cls


@pytest.fixture
def mock_client(mocker):
    mock_cls = mocker.patch("craftsman.cli.Client")
    instance = mock_cls.return_value
    instance.list_sessions.return_value = []
    return instance


# --- init ---


@pytest.fixture
def mock_init_fs(mocker, mock_makedirs):
    mocker.patch("craftsman.cli.os.path.exists", return_value=False)
    mocker.patch("craftsman.cli.shutil.copy")
    mocker.patch("craftsman.cli.files").return_value.joinpath.return_value = (
        "/fake/craftsman.yaml"
    )
    return mock_makedirs


def test_init_creates_three_directories(runner, mock_config, mock_init_fs):
    result = runner.invoke(main, ["init"])
    assert result.exit_code == 0
    assert mock_init_fs.call_count == 3


def test_init_outputs_root_path(runner, mock_config, mock_init_fs):
    result = runner.invoke(main, ["init"])
    assert "/tmp/craftsman-test" in result.output


def test_init_exits_zero(runner, mock_config, mock_init_fs):
    assert runner.invoke(main, ["init"]).exit_code == 0


def test_init_copies_config_if_not_exists(
    runner, mock_config, mocker, mock_makedirs
):
    mocker.patch("craftsman.cli.os.path.exists", return_value=False)
    mock_copy = mocker.patch("craftsman.cli.shutil.copy")
    mocker.patch("craftsman.cli.files").return_value.joinpath.return_value = (
        "/fake/craftsman.yaml"
    )
    runner.invoke(main, ["init"])
    mock_copy.assert_called_once()


def test_init_skips_copy_if_config_exists(
    runner, mock_config, mocker, mock_makedirs
):
    mocker.patch("craftsman.cli.os.path.exists", return_value=True)
    mock_copy = mocker.patch("craftsman.cli.shutil.copy")
    mocker.patch("craftsman.cli.files")
    runner.invoke(main, ["init"])
    mock_copy.assert_not_called()


# --- auth list ---


def test_auth_list_shows_masked_value(runner, mock_auth):
    mock_auth.get_password.side_effect = lambda k: (
        "myval" if k == "LLM_API_KEY" else None
    )
    result = runner.invoke(main, ["auth", "list"])
    assert "*****" in result.output


def test_auth_list_shows_not_set(runner, mock_auth):
    mock_auth.get_password.return_value = None
    result = runner.invoke(main, ["auth", "list"])
    assert "Not set" in result.output


# --- auth set ---


def test_auth_set_calls_set_password(runner, mock_auth):
    result = runner.invoke(
        main, ["auth", "set", "LLM_API_KEY"], input="secret\n"
    )
    assert result.exit_code == 0
    mock_auth.set_password.assert_called_once_with("LLM_API_KEY", "secret")


# --- auth get ---


def test_auth_get_shows_masked_value(runner, mock_auth):
    mock_auth.get_password.return_value = "mykey"
    result = runner.invoke(main, ["auth", "get", "LLM_API_KEY"])
    assert "*****" in result.output


def test_auth_get_shows_not_set(runner, mock_auth):
    mock_auth.get_password.return_value = None
    result = runner.invoke(main, ["auth", "get", "LLM_API_KEY"])
    assert "Not set" in result.output


# --- auth clear ---


def test_auth_clear_specific_provider(runner, mock_auth):
    mock_auth.get_password.return_value = "val"
    runner.invoke(main, ["auth", "clear", "LLM_API_KEY"])
    mock_auth.delete_password.assert_called_once_with("LLM_API_KEY")


def test_auth_clear_specific_provider_not_set(runner, mock_auth):
    mock_auth.get_password.return_value = None
    runner.invoke(main, ["auth", "clear", "LLM_API_KEY"])
    mock_auth.delete_password.assert_not_called()


def test_auth_clear_all_providers(runner, mock_auth):
    mock_auth.get_password.return_value = "val"
    runner.invoke(main, ["auth", "clear"])
    assert mock_auth.delete_password.call_count == 3


# --- sess list / delete ---


def test_sess_list_prints_sessions(runner, mock_client):
    mock_client.list_sessions.return_value = [
        "session-info-1",
        "session-info-2",
    ]
    result = runner.invoke(main, ["sess", "list"])
    assert "session-info-1" in result.output
    assert "session-info-2" in result.output


def test_sess_delete_calls_client(runner, mock_client):
    runner.invoke(main, ["sess", "delete", "abc123"])
    mock_client.delete_session.assert_called_once_with("abc123")


# --- help ---


def test_main_help_exits_zero(runner):
    assert runner.invoke(main, ["--help"]).exit_code == 0


def test_auth_group_in_help(runner):
    assert "auth" in runner.invoke(main, ["--help"]).output


def test_sess_group_in_help(runner):
    assert "sess" in runner.invoke(main, ["--help"]).output
