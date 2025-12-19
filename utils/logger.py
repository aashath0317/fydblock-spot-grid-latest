import logging
from logging.handlers import RotatingFileHandler
import sys
from pathlib import Path


def setup_logger(name: str, log_level=logging.INFO):
    """
    Sets up a structured logger with both File and Console handlers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Prevent duplicate logs if logger already exists
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
