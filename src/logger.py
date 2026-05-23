"""
Structured logger for voice-cli.

Writes timestamped events to ~/.voice-cli/raycast.log, with a stage timer
that reports elapsed_ms per stage and total_ms since start. Trims the log
to the last LOG_MAX_LINES on init so the file does not grow unbounded.
"""

import logging
import os
import sys
import time
from pathlib import Path

LOG_PATH = Path.home() / ".voice-cli" / "raycast.log"
LOG_MAX_LINES = 2000

_logger: logging.Logger | None = None
_run_start: float | None = None
_stage_last: float | None = None


def _trim_log() -> None:
    try:
        if not LOG_PATH.exists():
            return
        with LOG_PATH.open("r") as f:
            lines = f.readlines()
        if len(lines) > LOG_MAX_LINES:
            with LOG_PATH.open("w") as f:
                f.writelines(lines[-LOG_MAX_LINES:])
    except OSError:
        pass


def get_logger(debug: bool = False) -> logging.Logger:
    global _logger, _run_start, _stage_last
    if _logger is not None:
        return _logger

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _trim_log()

    logger = logging.getLogger("voice-cli")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")

    file_handler = logging.FileHandler(LOG_PATH)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    if debug:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(fmt)
        logger.addHandler(stream_handler)

    _logger = logger
    now = time.monotonic()
    _run_start = now
    _stage_last = now
    return logger


def log_stage(name: str) -> None:
    """Emit a STAGE line with elapsed since prior stage and total since start."""
    global _stage_last
    logger = get_logger()
    now = time.monotonic()
    elapsed_ms = int((now - (_stage_last or now)) * 1000)
    total_ms = int((now - (_run_start or now)) * 1000)
    _stage_last = now
    logger.info(f"STAGE {name} elapsed_ms={elapsed_ms} total_ms={total_ms}")


def log_info(msg: str) -> None:
    get_logger().info(msg)


def log_error(msg: str) -> None:
    get_logger().error(msg)


def log_debug(msg: str) -> None:
    get_logger().debug(msg)
