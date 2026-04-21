import os
from importlib.resources import files

import yaml

_USER_CONFIG = os.path.expanduser("~/.craftsman/craftsman.yaml")


def get_config():
    if os.path.exists(_USER_CONFIG):
        with open(_USER_CONFIG) as f:
            return yaml.safe_load(f)
    config_path = files("craftsman").joinpath("craftsman.yaml")
    with config_path.open() as f:
        return yaml.safe_load(f)
