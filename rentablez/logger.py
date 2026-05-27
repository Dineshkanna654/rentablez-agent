import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOGGER_NAME = "rentablez"
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5


def setup_logger(log_file: str, level: int = logging.INFO) -> logging.Logger:
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.handlers.clear()

    handler = RotatingFileHandler(
        log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
