"""
Thread-safe multi-level logging module with console and file output.

Provides a singleton logger instance with automatic log file rotation.
Supports DEBUG, INFO, WARNING, ERROR, and CRITICAL levels with
timestamp and module name prefixing.
"""

import logging
import logging.handlers
import os
import sys
import threading
from datetime import datetime
from typing import Optional


class CorrosionLogger:
    """
    Thread-safe singleton logger for the corrosion detection system.

    Features:
        - Dual output: console (stdout) + rotating file
        - Timestamp + module name prefix
        - Log file rotation: max 10 MB per file, keep 5 backups
        - Thread-safe via internal lock
    """

    _instance: Optional["CorrosionLogger"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls, *args, **kwargs) -> "CorrosionLogger":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        log_dir: str = "logs",
        log_level: str = "INFO",
        max_file_size: int = 10 * 1024 * 1024,
        backup_count: int = 5,
    ) -> None:
        if hasattr(self, "_initialized") and self._initialized:
            return

        self._initialized = True
        self._log_dir = log_dir
        self._log_level = log_level
        self._max_file_size = max_file_size
        self._backup_count = backup_count
        self._lock = threading.Lock()

        os.makedirs(self._log_dir, exist_ok=True)

        self._root_logger = logging.getLogger("corrosion_detector")
        self._root_logger.setLevel(self._str_to_level(log_level))
        self._root_logger.propagate = False

        if not self._root_logger.handlers:
            self._setup_handlers()

    def _str_to_level(self, level: str) -> int:
        mapping = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        return mapping.get(level.upper(), logging.INFO)

    def _setup_handlers(self) -> None:
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self._str_to_level(self._log_level))
        console_handler.setFormatter(fmt)
        self._root_logger.addHandler(console_handler)

        log_file = os.path.join(self._log_dir, "corrosion_detector.log")
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=self._max_file_size,
            backupCount=self._backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        self._root_logger.addHandler(file_handler)

    def get_logger(self, module_name: str) -> logging.Logger:
        """
        Get a logger instance for the specified module.

        Args:
            module_name: Name of the module requesting the logger.

        Returns:
            Configured logger instance with module name prefix.
        """
        with self._lock:
            return logging.getLogger(f"corrosion_detector.{module_name}")

    def set_level(self, level: str) -> None:
        """
        Dynamically change the logging level.

        Args:
            level: One of DEBUG, INFO, WARNING, ERROR, CRITICAL.
        """
        with self._lock:
            self._log_level = level
            self._root_logger.setLevel(self._str_to_level(level))
            for handler in self._root_logger.handlers:
                if isinstance(handler, logging.StreamHandler) and not isinstance(
                    handler, logging.handlers.RotatingFileHandler
                ):
                    handler.setLevel(self._str_to_level(level))

    def shutdown(self) -> None:
        with self._lock:
            logging.shutdown()

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            cls._instance = None
