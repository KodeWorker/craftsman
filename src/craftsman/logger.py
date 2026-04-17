import datetime
import logging
import os

from craftsman.configure import get_config

ROOT_DIR = os.path.expanduser(get_config()["workspace"]["root"])


class CraftsmanLogger:
    """Singleton logger factory.
    All calls to CraftsmanLogger() return the same instance."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        config = get_config()
        assert os.path.isdir(ROOT_DIR), (
            f"Root directory {ROOT_DIR} does not exist."
            " Please run `craftsman init` first."
        )
        log_file = os.path.join(ROOT_DIR, "logs", "craftsman-%Y-%m-%d.log")
        self.log_file = datetime.datetime.now().strftime(log_file)
        self.log_level = getattr(
            logging, config["logging"]["level"].upper(), logging.INFO
        )
        self.debug = config["logging"].get("debug", False)
        self._fmt = "%(asctime)s | %(name)s | %(levelname)s : %(message)s"
        self._initialized = True

    def get_logger(self, name: str) -> logging.Logger:
        logger = logging.getLogger(name)
        logger.setLevel(self.log_level)
        if not getattr(logger, "_custom_handlers_set", False):
            f_handler = logging.FileHandler(self.log_file)
            f_handler.setFormatter(logging.Formatter(self._fmt))
            logger.addHandler(f_handler)
            if self.debug:
                c_handler = logging.StreamHandler()
                c_handler.setFormatter(logging.Formatter(self._fmt))
                logger.addHandler(c_handler)
            logger._custom_handlers_set = True
        return logger
