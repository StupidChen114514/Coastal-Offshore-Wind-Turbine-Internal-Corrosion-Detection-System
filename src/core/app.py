"""
Main Application class for the Wind Turbine Internal Corrosion Detection System.

Provides initialization, lifecycle management, and inter-module communication
via a signal/slot mechanism. Implements the thread-safe singleton pattern.
"""

import threading
import time
import traceback
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional

from .config_manager import ConfigManager
from .logger import CorrosionLogger


class AppState(Enum):
    """Application lifecycle states."""

    UNINITIALIZED = auto()
    INITIALIZED = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()
    ERROR = auto()


class Signal:
    """Simple signal/slot mechanism for decoupled inter-module communication.

    A signal can be connected to multiple slots (callbacks). When emitted,
    all connected slots are called with the provided arguments.
    """

    def __init__(self) -> None:
        self._slots: List[Callable[..., Any]] = []
        self._lock = threading.Lock()

    def connect(self, slot: Callable[..., Any]) -> None:
        """Connect a callable slot to this signal."""
        with self._lock:
            if slot not in self._slots:
                self._slots.append(slot)

    def disconnect(self, slot: Callable[..., Any]) -> None:
        """Disconnect a callable slot from this signal."""
        with self._lock:
            if slot in self._slots:
                self._slots.remove(slot)

    def emit(self, *args: Any, **kwargs: Any) -> None:
        """Emit the signal, calling all connected slots with provided arguments."""
        with self._lock:
            slots_copy = list(self._slots)
        for slot in slots_copy:
            try:
                slot(*args, **kwargs)
            except Exception:
                traceback.print_exc()

    def clear(self) -> None:
        """Remove all connected slots."""
        with self._lock:
            self._slots.clear()


class App:
    """
    Thread-safe singleton Application class.

    Manages the full lifecycle of the corrosion detection system:
        - Initialization of all subsystems (config, logging, etc.)
        - Start/Stop/Restart operations
        - Inter-module communication via signals

    Usage:
        app = App()
        app.initialize()
        app.start()
        ...
        app.stop()
    """

    _instance: Optional["App"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls, *args, **kwargs) -> "App":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_dir: str = "config") -> None:
        if hasattr(self, "_initialized"):
            return

        self._initialized = False
        self._state = AppState.UNINITIALIZED
        self._state_lock = threading.Lock()
        self._config_dir = config_dir

        self._logger: Optional[CorrosionLogger] = None
        self._config_manager: Optional[ConfigManager] = None

        self._signals: Dict[str, Signal] = {
            "sensor_data_received": Signal(),
            "corrosion_record_computed": Signal(),
            "alarm_raised": Signal(),
            "alarm_resolved": Signal(),
            "config_changed": Signal(),
            "system_error": Signal(),
            "state_changed": Signal(),
        }

        self._modules: Dict[str, Any] = {}
        self._started = False
        self._diagnostics = None

    # ------------------------------------------------------------------
    # Lifecycle Management
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """
        Initialize all subsystems.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        with self._state_lock:
            if self._state not in (AppState.UNINITIALIZED, AppState.STOPPED):
                return False
            self._state = AppState.INITIALIZED

        try:
            self._config_manager = ConfigManager(self._config_dir)
            self._config_manager.load()

            log_config = self._config_manager.get("logging", {})
            self._logger = CorrosionLogger(
                log_dir=log_config.get("log_dir", {}).get("value", "logs"),
                log_level=log_config.get("level", {}).get("value", "INFO"),
                max_file_size=log_config.get("max_file_size", {}).get("value", 10485760),
                backup_count=log_config.get("backup_count", {}).get("value", 5),
            )

            log = self._logger.get_logger("App")
            log.info("=" * 60)
            log.info("Wind Turbine Internal Corrosion Detection System")
            log.info(f"Version: {self._config_manager.get_version()}")
            log.info("=" * 60)
            log.info("System initialization started")

            self._init_modules()
            self._initialized = True
            log.info("System initialization completed successfully")
            return True

        except Exception as e:
            self._state = AppState.ERROR
            if self._logger:
                self._logger.get_logger("App").error(
                    f"Initialization failed: {e}\n{traceback.format_exc()}"
                )
            else:
                traceback.print_exc()
            return False

    def _init_modules(self) -> None:
        """Initialize all subsystem modules."""
        log = self._logger.get_logger("App") if self._logger else None
        if log:
            log.debug("Registering subsystem modules")
        self._modules = {}

        self._init_diagnostics()

    def _init_diagnostics(self) -> None:
        """Initialize the diagnostics manager and run POST."""
        from .diagnostics import DiagnosticsManager

        log = self._logger.get_logger("App") if self._logger else None

        self._diagnostics = DiagnosticsManager(self)
        self._modules["diagnostics"] = self._diagnostics

        post_passed = self._diagnostics.run_post()
        if post_passed:
            if log:
                log.info("POST completed successfully")
        else:
            if log:
                log.critical("POST failed – system may be in degraded or faulty state")

    def start(self) -> bool:
        """
        Start the application and all subsystems.

        Returns:
            True if start succeeded, False otherwise.
        """
        with self._state_lock:
            if self._state != AppState.INITIALIZED:
                return False
            self._state = AppState.RUNNING

        log = self._logger.get_logger("App") if self._logger else None

        try:
            if log:
                log.info("Starting application subsystems")

            if self._diagnostics is not None:
                self._diagnostics.start_watchdog()
                self._diagnostics.start_periodic_checks()
                if log:
                    log.info("Watchdog and periodic diagnostics started")

            self._signals["state_changed"].emit(AppState.RUNNING)
            self._started = True

            if log:
                log.info("Application started successfully")
            return True

        except Exception as e:
            self._state = AppState.ERROR
            if log:
                log.error(f"Start failed: {e}\n{traceback.format_exc()}")
            return False

    def stop(self) -> bool:
        """
        Stop the application and shutdown all subsystems gracefully.

        Returns:
            True if stop succeeded, False otherwise.
        """
        with self._state_lock:
            if self._state not in (AppState.RUNNING, AppState.INITIALIZED):
                return False
            self._state = AppState.STOPPING

        log = self._logger.get_logger("App") if self._logger else None

        try:
            if log:
                log.info("Shutting down application subsystems")

            self._signals["state_changed"].emit(AppState.STOPPING)

            if self._diagnostics is not None:
                self._diagnostics.watchdog.stop()
                if log:
                    log.info("Watchdog stopped")

            for signal in self._signals.values():
                signal.clear()

            self._modules.clear()

            if self._logger:
                if log:
                    log.info("Application shutdown complete")
                self._logger.shutdown()

            self._state = AppState.STOPPED
            self._started = False
            return True

        except Exception as e:
            self._state = AppState.ERROR
            if log:
                log.error(f"Shutdown error: {e}\n{traceback.format_exc()}")
            return False

    def restart(self) -> bool:
        """
        Restart the application.

        Returns:
            True if restart succeeded, False otherwise.
        """
        log = self._logger.get_logger("App") if self._logger else None
        if log:
            log.info("Restarting application")

        self.stop()
        time.sleep(0.5)
        if not self.initialize():
            return False
        return self.start()

    def run(self) -> None:
        """
        Run the main application event loop with watchdog feeding.

        Blocks until the application is stopped. Feeds the watchdog
        on every iteration. Designed for headless/embedded deployments.

        Usage:
            app = App()
            app.initialize()
            app.start()
            app.run()
        """
        log = self._logger.get_logger("App") if self._logger else None
        if log:
            log.info("Application main loop started")

        while self.is_running:
            try:
                self.feed_watchdog()
                time.sleep(0.5)
            except KeyboardInterrupt:
                break
            except Exception as e:
                if log:
                    log.error(f"Main loop error: {e}")

        if log:
            log.info("Application main loop exited")
        self.stop()

    def feed_watchdog(self) -> None:
        """Feed the diagnostics watchdog timer from the main loop."""
        if self._diagnostics is not None:
            self._diagnostics.feed_watchdog()

    @property
    def diagnostics(self):
        """Get the diagnostics manager instance."""
        return self._diagnostics

    # ------------------------------------------------------------------
    # Signal Management
    # ------------------------------------------------------------------

    def get_signal(self, name: str) -> Optional[Signal]:
        """Get a signal by name. Returns None if not found."""
        return self._signals.get(name)

    def connect(self, signal_name: str, slot: Callable[..., Any]) -> bool:
        """
        Connect a slot to a named signal.

        Args:
            signal_name: Name of the signal.
            slot: Callable to connect.

        Returns:
            True if connected successfully, False if signal not found.
        """
        signal = self._signals.get(signal_name)
        if signal:
            signal.connect(slot)
            return True
        return False

    def disconnect(self, signal_name: str, slot: Callable[..., Any]) -> bool:
        """
        Disconnect a slot from a named signal.

        Args:
            signal_name: Name of the signal.
            slot: Callable to disconnect.

        Returns:
            True if disconnected successfully, False if signal not found.
        """
        signal = self._signals.get(signal_name)
        if signal:
            signal.disconnect(slot)
            return True
        return False

    def emit(self, signal_name: str, *args: Any, **kwargs: Any) -> bool:
        """
        Emit a named signal with arguments.

        Args:
            signal_name: Name of the signal to emit.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            True if emitted, False if signal not found.
        """
        signal = self._signals.get(signal_name)
        if signal:
            signal.emit(*args, **kwargs)
            return True
        return False

    # ------------------------------------------------------------------
    # Property Accessors
    # ------------------------------------------------------------------

    @property
    def state(self) -> AppState:
        """Get the current application state."""
        return self._state

    @property
    def is_running(self) -> bool:
        """Check if the application is currently running."""
        return self._state == AppState.RUNNING

    @property
    def config_manager(self) -> Optional[ConfigManager]:
        """Get the configuration manager instance."""
        return self._config_manager

    @property
    def logger(self) -> Optional[CorrosionLogger]:
        """Get the logger instance."""
        return self._logger

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        with cls._lock:
            cls._instance = None
