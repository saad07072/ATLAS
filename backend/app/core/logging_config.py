import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level_name: str) -> None:
    level = logging.getLevelNamesMapping().get(level_name.upper())
    if not isinstance(level, int):
        raise ValueError(f"Unsupported log level: {level_name}")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if not root_logger.handlers:
        root_logger.addHandler(logging.StreamHandler())

    formatter = logging.Formatter(LOG_FORMAT)
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)
