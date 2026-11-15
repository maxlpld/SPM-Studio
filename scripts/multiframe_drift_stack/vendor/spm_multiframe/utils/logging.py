from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(log_path: Path, verbose: bool = False) -> logging.Logger:
    """Configure a package logger that writes a timestamped run log and concise console text."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("spm_multiframe")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    )
    logger.addHandler(file_handler)
    return logger
