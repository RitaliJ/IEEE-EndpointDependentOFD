from __future__ import annotations

import logging
import sys


def configure_logging(
    level:      int  = logging.INFO,
    log_file:   str | None = None,
    log_format: str = "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
) -> None:
    """Configure root logger for the unified_sim package.

    Args:
        level:      logging level (e.g. logging.DEBUG)
        log_file:   if set, also write to this file path
        log_format: format string for all handlers
    """
    root = logging.getLogger("mvp_sim")
    root.setLevel(level)
    root.handlers.clear()

    fmt = logging.Formatter(log_format)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        root.addHandler(fh)