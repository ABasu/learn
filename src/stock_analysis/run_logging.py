from __future__ import annotations

import logging
import sys
from pathlib import Path


def configure_run_logger(log_file: Path, *, verbose: bool = False, quiet: bool = False) -> logging.Logger:
    """Create an isolated console + file logger for one report run."""
    logger = logging.getLogger(f"stock_analysis.run.{log_file.parent.name}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.handlers.clear()

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.WARNING if quiet else logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%H:%M:%S"))

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"))

    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger
