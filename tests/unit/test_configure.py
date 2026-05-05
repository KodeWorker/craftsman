from craftsman.configure import get_config


def test_get_config_returns_dict():
    assert isinstance(get_config(), dict)


def test_get_config_has_required_keys():
    config = get_config()
    for key in ("logging", "workspace", "provider", "commands"):
        assert key in config


def test_provider_section_has_model():
    model = get_config()["provider"]["model"]
    assert isinstance(model, str) and model


def test_workspace_section_has_paths():
    workspace = get_config()["workspace"]
    for key in ("root", "database", "logs"):
        assert key in workspace


def test_commands_is_list_of_dicts_with_name():
    commands = get_config()["commands"]
    assert isinstance(commands, list)
    assert all(isinstance(c, dict) and "name" in c for c in commands)


def test_get_config_returns_empty_dict_for_empty_yaml(mocker):
    mocker.patch("craftsman.configure.os.path.exists", return_value=False)
    mocker.patch("craftsman.configure.yaml.safe_load", return_value=None)
    assert get_config() == {}


def test_get_config_raises_on_load_error(mocker):
    import pytest

    mocker.patch("craftsman.configure.os.path.exists", return_value=False)
    mocker.patch(
        "craftsman.configure.files",
        side_effect=Exception("bundled config missing"),
    )
    with pytest.raises(RuntimeError, match="Error loading config"):
        get_config()
