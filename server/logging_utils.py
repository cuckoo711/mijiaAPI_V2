"""Lightweight logging helpers for the server process."""

from __future__ import annotations

import logging
import sys


def get_server_logger(name: str) -> logging.Logger:
    """Return a module logger configured for journal/stdout output."""

    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        logger.addHandler(handler)
        logger.propagate = False
        logger.setLevel(logging.INFO)
    return logger
