"""
Hardware/software watchdog timer with automatic recovery.

Monitors the main application loop health by tracking periodic "feed"
calls. When the watchdog is not fed within the configured timeout, it
triggers a recovery callback (typically a system reset).

Implements a background thread that periodically checks the last feed
timestamp against the configured timeout.
"""

import threading
import time
import traceback
from typing import Callable, Optional


class WatchdogTimer:
    """Hardware/software watchdog timer with automatic recovery.

    Must be fed regularly from the main application loop. If the timeout
    elapses without a feed, the optional `on_timeout` callback is invoked
    to trigger system recovery.

    Attributes:
        _timeout: Maximum allowed interval between feed calls (seconds).
        _last_feed: Timestamp of the most recent feed call.
        _running: Whether the monitoring thread is active.
        _thread: Background monitoring thread.
        _on_timeout: Optional callback invoked on timeout.
        _lock: Thread safety lock.
    """

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        on_timeout: Optional[Callable[[], None]] = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._last_feed = time.time()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._on_timeout = on_timeout
        self._lock = threading.Lock()

    def feed(self) -> None:
        """Feed the watchdog. Call regularly from the main application loop.

        Resets the internal last-feed timestamp to the current time,
        preventing the watchdog from timing out.
        """
        with self._lock:
            self._last_feed = time.time()

    def start(self) -> None:
        """Start watchdog monitoring in a background daemon thread.

        Creates and starts a daemon thread that periodically checks
        whether the watchdog has been fed within the timeout period.
        If already running, this call has no effect.
        """
        if self._running:
            return

        self._last_feed = time.time()
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="WatchdogTimer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop watchdog monitoring.

        Signals the monitoring thread to exit and waits for it to join.
        """
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def is_alive(self) -> bool:
        """Check if the watchdog has been fed within the timeout period.

        Returns:
            True if the watchdog is still healthy, False if it has timed out.
        """
        with self._lock:
            elapsed = time.time() - self._last_feed
        return elapsed <= self._timeout

    def reset(self) -> None:
        """Reset the watchdog feed timestamp and optionally restart.

        Equivalent to calling feed() if already running, or feed() +
        start() if not running.
        """
        self.feed()
        if not self._running:
            self.start()

    def _monitor_loop(self) -> None:
        """Background monitoring loop.

        Checks the last feed timestamp at regular intervals (every
        quarter of the timeout period). If the watchdog has not been
        fed within the timeout, invokes the on_timeout callback.
        """
        check_interval = max(0.5, self._timeout / 4.0)
        while self._running:
            time.sleep(check_interval)
            if not self._running:
                break
            if not self.is_alive():
                if self._on_timeout is not None:
                    try:
                        self._on_timeout()
                    except Exception:
                        traceback.print_exc()
                break

    @property
    def timeout(self) -> float:
        """Get the configured timeout in seconds."""
        return self._timeout

    @property
    def time_since_last_feed(self) -> float:
        """Get the elapsed time since the last feed in seconds."""
        with self._lock:
            return time.time() - self._last_feed

    @property
    def is_running(self) -> bool:
        """Check if the monitoring thread is active."""
        return self._running
