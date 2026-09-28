"""Console + file logging with a compact, readable format.

The UI tails the per-run log file, so the format is kept stable.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_FMT = "%(asctime)s  %(levelname)-7s  %(name)-22s  %(message)s"
_DATEFMT = "%H:%M:%S"

_CONSOLE_COLOURS = {
    "DEBUG": "\033[38;5;245m",
    "INFO": "\033[38;5;39m",
    "WARNING": "\033[38;5;214m",
    "ERROR": "\033[38;5;203m",
    "CRITICAL": "\033[48;5;203m\033[38;5;231m",
}
_RESET = "\033[0m"


class _ColourFormatter(logging.Formatter):
    def __init__(self, colour: bool) -> None:
        super().__init__(_FMT, _DATEFMT)
        self.colour = colour

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if not self.colour:
            return text
        prefix = _CONSOLE_COLOURS.get(record.levelname, "")
        return f"{prefix}{text}{_RESET}" if prefix else text


_configured = False


def setup(level: str = "INFO", logfile: Path | None = None) -> None:
    """Configure root logging once. Safe to call repeatedly."""
    global _configured
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not _configured:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(_ColourFormatter(colour=sys.stderr.isatty()))
        root.addHandler(console)
        # Third-party chatter we never want at INFO.
        for noisy in ("httpx", "httpcore", "urllib3", "chromadb", "onnxruntime", "fastembed"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        _configured = True

    if logfile is not None:
        logfile.parent.mkdir(parents=True, exist_ok=True)
        # Avoid attaching the same file twice across repeated runs in one process.
        existing = {
            getattr(h, "baseFilename", None) for h in root.handlers if isinstance(h, logging.FileHandler)
        }
        if str(logfile.resolve()) not in existing:
            fh = logging.FileHandler(logfile, encoding="utf-8")
            fh.setFormatter(logging.Formatter(_FMT, _DATEFMT))
            root.addHandler(fh)


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
