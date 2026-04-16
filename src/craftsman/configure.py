from importlib.resources import files

import yaml


def get_config():
    config_path = files("craftsman").joinpath("craftsman.yaml")
    with config_path.open() as f:
        config = yaml.safe_load(f)
    return config
