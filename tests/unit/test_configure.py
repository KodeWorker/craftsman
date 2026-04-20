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
