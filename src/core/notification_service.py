"""
Multi-channel notification service for the Wind Turbine Internal
Corrosion Detection System.

Handles sending alarm notifications through configured channels
(LoRa, MQTT, Modbus, etc.) with priority-based dispatch:

    - Level 4 (Emergency): immediate send, bypass queue, highest priority
    - Level 2-3: standard send through configured channels
    - Level 1 (Info): logged only, no external notification

Each notification is sent asynchronously with up to 3 retries per channel.
"""

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .data_models import AlarmLevel, AlarmRecord
from .logger import CorrosionLogger

_logger = CorrosionLogger().get_logger("NotificationService")

_MAX_RETRIES = 3
_RETRY_DELAY_SECONDS = 2.0


class NotificationService:
    """
    Handles sending alarm notifications through configured communication channels.

    Channels are registered as named callables that accept an AlarmRecord
    and return True on success or False on failure.

    Usage:
        svc = NotificationService(config_manager)
        svc.register_channel("lora", lora_send_fn)
        svc.register_channel("mqtt", mqtt_send_fn)
        svc.send_notification(alarm_record)
    """

    def __init__(self, config_manager: Any = None) -> None:
        """
        Args:
            config_manager: Optional ConfigManager for reading notification settings.
        """
        self._channels: Dict[str, Callable[[AlarmRecord], bool]] = {}
        self._config = config_manager
        self._lock = threading.Lock()
        _logger.info("NotificationService initialised")

    def register_channel(self, name: str, sender: Callable[[AlarmRecord], bool]) -> None:
        """
        Register a notification channel.

        Args:
            name: Channel name (e.g., 'lora', 'mqtt', 'modbus').
            sender: Callable that accepts AlarmRecord and returns bool (success/failure).
        """
        with self._lock:
            self._channels[name] = sender
            _logger.info("Notification channel registered: %s", name)

    def unregister_channel(self, name: str) -> None:
        """Unregister a notification channel."""
        with self._lock:
            if name in self._channels:
                del self._channels[name]
                _logger.info("Notification channel unregistered: %s", name)

    def get_channels(self) -> List[str]:
        """Get names of all registered channels."""
        with self._lock:
            return list(self._channels.keys())

    def send_notification(
        self,
        alarm: AlarmRecord,
        channels: Optional[List[str]] = None,
    ) -> Dict[str, bool]:
        """
        Send alarm notification through specified channels.

        Each channel is invoked in its own thread. Up to 3 retries
        per channel with a 2-second delay between attempts.

        Level 4 (Emergency) alarms bypass all queueing and are sent
        immediately with highest priority.

        Args:
            alarm: The AlarmRecord to send.
            channels: List of channel names. If None, uses all configured channels.

        Returns:
            Dictionary mapping channel name → success status.
        """
        with self._lock:
            target_channels = channels if channels is not None else list(self._channels.keys())
            channel_map = {
                name: self._channels[name]
                for name in target_channels
                if name in self._channels
            }

        if not channel_map:
            _logger.debug("No notification channels available for alarm %s", alarm.alarm_id)
            return {}

        is_emergency = alarm.level == AlarmLevel.LEVEL_4

        if is_emergency:
            _logger.critical(
                "EMERGENCY notification: alarm %s, channels=%s",
                alarm.alarm_id, list(channel_map.keys()),
            )
            return self.send_priority_message(alarm, channel_map)

        _logger.info(
            "Sending notification for alarm %s (level=%d) via %d channel(s)",
            alarm.alarm_id, alarm.level.value, len(channel_map),
        )

        results: Dict[str, bool] = {}
        threads: List[threading.Thread] = []
        result_lock = threading.Lock()

        def _send_with_result(name: str, sender: Callable[[AlarmRecord], bool]) -> None:
            success = self._send_with_retry(name, sender, alarm)
            with result_lock:
                results[name] = success

        for ch_name, ch_sender in channel_map.items():
            t = threading.Thread(
                target=_send_with_result,
                args=(ch_name, ch_sender),
                daemon=True,
            )
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        return results

    def send_priority_message(
        self,
        alarm: AlarmRecord,
        channel_map: Optional[Dict[str, Callable[[AlarmRecord], bool]]] = None,
    ) -> Dict[str, bool]:
        """
        Emergency priority: send Level 4 alarms immediately with synchronous dispatch.

        All channels are attempted synchronously in sequence. Each channel
        gets up to 3 retries.

        Args:
            alarm: The emergency AlarmRecord.
            channel_map: Channels to use. If None, uses all registered channels.

        Returns:
            Dictionary mapping channel name → success status.
        """
        if channel_map is None:
            with self._lock:
                channel_map = dict(self._channels)

        results: Dict[str, bool] = {}
        for ch_name, ch_sender in channel_map.items():
            _logger.critical(
                "EMERGENCY dispatch to channel '%s' for alarm %s", ch_name, alarm.alarm_id
            )
            results[ch_name] = self._send_with_retry(ch_name, ch_sender, alarm)

        return results

    def _send_with_retry(
        self,
        channel_name: str,
        sender: Callable[[AlarmRecord], bool],
        alarm: AlarmRecord,
        max_retries: int = _MAX_RETRIES,
    ) -> bool:
        for attempt in range(1, max_retries + 1):
            try:
                success = sender(alarm)
                if success:
                    _logger.info(
                        "Notification sent via '%s' (attempt %d/%d)",
                        channel_name, attempt, max_retries,
                    )
                    return True
                _logger.warning(
                    "Notification via '%s' returned failure (attempt %d/%d)",
                    channel_name, attempt, max_retries,
                )
            except Exception:
                _logger.exception(
                    "Notification via '%s' raised exception (attempt %d/%d)",
                    channel_name, attempt, max_retries,
                )

            if attempt < max_retries:
                time.sleep(_RETRY_DELAY_SECONDS)

        _logger.error(
            "Notification via '%s' failed after %d attempts for alarm %s",
            channel_name, max_retries, alarm.alarm_id,
        )
        return False
