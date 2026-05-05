import os
from importlib.resources import files

import yaml

_USER_CONFIG = os.path.expanduser("~/.craftsman/craftsman.yaml")


def get_config() -> dict:
    try:
        if os.path.exists(_USER_CONFIG):
            with open(_USER_CONFIG, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        config_path = files("craftsman").joinpath("craftsman.yaml")
        with config_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        raise RuntimeError(f"Error loading config: {e}") from e
