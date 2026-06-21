"""
Unified communication manager for the Wind Turbine Corrosion Detection System.

Orchestrates all communication channels:
    - LoRaWAN   – low-power long-range radio (primary field channel)
    - NB-IoT    – cellular narrowband IoT (backup / alternate primary)
    - Modbus TCP – local SCADA / PLC integration
    - MQTT      – cloud IoT platform integration

Provides unified upload interface with automatic channel selection,
local queueing on failure, backlog management, and statistics reporting.

Features:
    - Primary channel selection (LoRa or NB-IoT) from configuration
    - Automatic failover to backup channel
    - Local queuing on upload failure with retry
    - Batch backlog processing on reconnect
    - Alarm priority upload (Level ≥ 2 alarms)
    - Upload statistics (pending, sent, failed counts)
    - Graceful shutdown of all channels
"""

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from ..core.data_models import AlarmRecord
from ..core.logger import CorrosionLogger
from .backlog_manager import BacklogManager
from .data_packet import DataPacket, MessageType
from .lorawan_channel import LoRaWANChannel
from .modbus_server import ModbusServer
from .mqtt_client import MQTTClient
from .nbiot_channel import NBIoTChannel

_logger = CorrosionLogger().get_logger("CommManager")

_RETRY_MAX = 3
_BATCH_SIZE = 100
_UPLOAD_RETRY_DELAY = 5.0
_BACKLOG_FLUSH_INTERVAL = 30.0


class CommunicationManager:
    """
    Manages all communication channels: LoRa, NB-IoT, Modbus TCP, MQTT.

    Provides a unified interface for data upload, alarm notification,
    offline buffering, and statistics reporting.
    """

    def __init__(self, config_manager: Any, storage_manager: Any) -> None:
        self._config = config_manager
        self._storage = storage_manager

        self._channels: Dict[str, Any] = {}
        self._primary_channel: str = "lora"

        self._upload_queue: List[Dict[str, Any]] = []
        self._queue_lock = threading.Lock()
        self._retry_max = _RETRY_MAX
        self._batch_size = _BATCH_SIZE

        self._data_packet = DataPacket()

        self._lora: Optional[LoRaWANChannel] = None
        self._nbiot: Optional[NBIoTChannel] = None
        self._modbus: Optional[ModbusServer] = None
        self._mqtt: Optional[MQTTClient] = None
        self._backlog: Optional[BacklogManager] = None

        self._initialized = False
        self._running = False

        self._upload_thread: Optional[threading.Thread] = None

        self._upload_sent: int = 0
        self._upload_failed: int = 0
        self._upload_pending: int = 0
        self._stats_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Initialise configured communication channels."""
        try:
            self._primary_channel = str(
                self._get_config("comms.primary_channel.value", "lora")
            ).lower()

            # LoRaWAN
            self._lora = LoRaWANChannel(self._config)
            if not self._lora.initialize():
                _logger.warning("LoRaWAN channel initialisation failed")

            # NB-IoT
            self._nbiot = NBIoTChannel(self._config)
            if not self._nbiot.initialize():
                _logger.warning("NB-IoT channel initialisation failed")

            # Modbus TCP
            modbus_port = int(self._get_config("comms.modbus.port.value", 502))
            self._modbus = ModbusServer(port=modbus_port)
            if not self._modbus.initialize():
                _logger.warning("Modbus server initialisation failed")

            # MQTT Cloud
            self._mqtt = MQTTClient(self._config)
            if not self._mqtt.initialize():
                _logger.warning("MQTT client initialisation failed")

            # Backlog
            self._backlog = BacklogManager(self._storage)
            self._backlog.initialize()

            self._channels = {
                "lora": self._lora,
                "nbiot": self._nbiot,
                "modbus": self._modbus,
                "mqtt": self._mqtt,
            }

            self._initialized = True
            _logger.info(
                "CommunicationManager initialised – primary=%s",
                self._primary_channel,
            )
            return True
        except Exception as exc:
            _logger.error("CommunicationManager initialisation failed: %s", exc)
            return False

    def start(self) -> None:
        """Start all communication services."""
        if not self._initialized:
            _logger.warning("CommunicationManager not initialised")
            return

        self._running = True

        if self._lora and self._lora._initialized:
            self._lora.start()

        if self._nbiot and self._nbiot._initialized:
            self._nbiot.start()

        if self._modbus and self._modbus._initialized:
            self._modbus.start()

        if self._mqtt and self._mqtt._initialized:
            self._mqtt.start()

        self._upload_thread = threading.Thread(
            target=self._upload_worker,
            daemon=True,
            name="comm-upload-worker",
        )
        self._upload_thread.start()

        _logger.info("CommunicationManager started – all channels active")

    def stop(self) -> None:
        """Stop all communication services gracefully."""
        self._running = False

        if self._lora:
            self._lora.stop()
        if self._nbiot:
            self._nbiot.stop()
        if self._modbus:
            self._modbus.stop()
        if self._mqtt:
            self._mqtt.stop()

        _logger.info("CommunicationManager stopped")

    # ------------------------------------------------------------------
    # Data Upload
    # ------------------------------------------------------------------

    def upload_data_packet(
        self,
        sensor_data: Dict[str, Any],
        corrosion_record: Dict[str, Any],
    ) -> bool:
        """
        Upload data via primary channel (LoRa or NB-IoT).

        Packet format: compact binary (<100 bytes) or compact JSON.
        On failure: queue locally for retry.

        Args:
            sensor_data: Sensor readings (T, RH, Cl_deposition).
            corrosion_record: Corrosion processing results.

        Returns:
            True if upload succeeded, False if queued.
        """
        success = False

        if self._primary_channel == "lora" and self._lora and self._lora.is_running:
            success = self._lora.send_data(sensor_data, corrosion_record)

        if not success and self._nbiot and self._nbiot.is_running:
            success = self._nbiot.publish_sensor_data(sensor_data, corrosion_record)

        if self._mqtt and self._mqtt.is_connected:
            self._mqtt.publish_data(sensor_data, corrosion_record)

        with self._stats_lock:
            if success:
                self._upload_sent += 1
            else:
                self._upload_failed += 1
                self._queue_locally("data", {
                    "sensor_data": sensor_data,
                    "corrosion_record": corrosion_record,
                })

        return success

    def upload_alarm(self, alarm_record: AlarmRecord) -> bool:
        """
        Send alarm notification with priority.

        Level ≥ 2 alarms get priority treatment:
        - Sent immediately via all available channels
        - Not buffered to backlog if at least one channel succeeds

        Args:
            alarm_record: AlarmRecord from alarm_manager.

        Returns:
            True if sent via at least one channel.
        """
        alarm_dict = alarm_record.to_dict()

        success_lora = False
        success_nbiot = False
        success_mqtt = False

        if self._lora and self._lora.is_running:
            success_lora = self._lora.send_alarm(alarm_dict)

        if self._nbiot and self._nbiot.is_running:
            success_nbiot = self._nbiot.publish_alarm(alarm_dict)

        if self._mqtt and self._mqtt.is_connected:
            success_mqtt = self._mqtt.publish_alarm(alarm_dict)

        any_success = success_lora or success_nbiot or success_mqtt

        with self._stats_lock:
            if any_success:
                self._upload_sent += 1
            else:
                self._upload_failed += 1
                self._queue_locally("alarm", {"alarm_record": alarm_dict})

        return any_success

    def upload_status(self, status_data: Dict[str, Any]) -> bool:
        """
        Upload system status via all available channels.

        Args:
            status_data: Status information dictionary.

        Returns:
            True if sent via at least one channel.
        """
        success = False

        if self._nbiot and self._nbiot.is_running:
            if self._nbiot.publish_status(status_data):
                success = True

        if self._mqtt and self._mqtt.is_connected:
            if self._mqtt.publish_status(status_data):
                success = True

        return success

    # ------------------------------------------------------------------
    # Queue Management
    # ------------------------------------------------------------------

    def process_upload_queue(self) -> Tuple[int, int]:
        """
        Process pending uploads from the local queue.

        Attempts to re-send queued items. Items that exceed retry_max
        are moved to the backlog manager for persistence.

        Returns:
            Tuple of (sent_count, failed_count).
        """
        sent = 0
        failed = 0

        with self._queue_lock:
            if not self._upload_queue:
                return (0, 0)

            to_remove = []
            to_backlog = []

            for item in self._upload_queue:
                item["retries"] = item.get("retries", 0) + 1

                if item["retries"] > self._retry_max:
                    to_backlog.append(item)
                    to_remove.append(item)
                    failed += 1
                    continue

                success = False
                msg_type = item["type"]
                payload = item["payload"]

                if msg_type == "data":
                    success = self._retry_upload_data(payload)
                elif msg_type == "alarm":
                    success = self._retry_upload_alarm(payload)

                if success:
                    sent += 1
                    to_remove.append(item)
                else:
                    failed += 1

            for item in to_remove:
                self._upload_queue.remove(item)

            if to_backlog:
                for item in to_backlog:
                    if item["type"] == "data":
                        sd = item["payload"].get("sensor_data", {})
                        cr = item["payload"].get("corrosion_record", {})
                        if self._backlog:
                            self._backlog.enqueue_sensor_data(sd, cr)
                    elif item["type"] == "alarm":
                        ar = item["payload"].get("alarm_record", {})
                        if self._backlog:
                            self._backlog.enqueue_alarm(ar)

        return (sent, failed)

    def _retry_upload_data(self, payload: Dict[str, Any]) -> bool:
        """Retry uploading data via primary channel."""
        sensor_data = payload.get("sensor_data", {})
        corrosion_record = payload.get("corrosion_record", {})

        if self._primary_channel == "lora" and self._lora and self._lora.is_running:
            return self._lora.send_data(sensor_data, corrosion_record)

        if self._nbiot and self._nbiot.is_running:
            return self._nbiot.publish_sensor_data(sensor_data, corrosion_record)

        return False

    def _retry_upload_alarm(self, payload: Dict[str, Any]) -> bool:
        """Retry uploading alarm data."""
        alarm_dict = payload.get("alarm_record", {})

        success = False
        if self._lora and self._lora.is_running:
            success = self._lora.send_alarm(alarm_dict)
        if not success and self._nbiot and self._nbiot.is_running:
            success = self._nbiot.publish_alarm(alarm_dict)
        return success

    def _queue_locally(self, msg_type: str, payload: Dict[str, Any]) -> None:
        """Add a failed upload to the local retry queue."""
        with self._queue_lock:
            self._upload_queue.append({
                "type": msg_type,
                "payload": payload,
                "retries": 0,
                "queued_at": time.time(),
            })
            self._upload_pending = len(self._upload_queue)

    # ------------------------------------------------------------------
    # Upload Worker
    # ------------------------------------------------------------------

    def _upload_worker(self) -> None:
        """Background thread that periodically processes the upload queue."""
        while self._running:
            time.sleep(_UPLOAD_RETRY_DELAY)

            if not self._running:
                break

            try:
                sent, failed = self.process_upload_queue()
                if sent > 0 or failed > 0:
                    _logger.debug(
                        "Upload worker processed: sent=%d, failed=%d, pending=%d",
                        sent, failed, len(self._upload_queue),
                    )

                # Flush backlog if any channel is connected
                if self._backlog and self._backlog.pending_count > 0:
                    if self._is_any_channel_connected():
                        self._backlog.flush(self._upload_via_backlog)
            except Exception as exc:
                _logger.error("Upload worker error: %s", exc)

    def _is_any_channel_connected(self) -> bool:
        """Check if any remote channel is connected."""
        if self._lora and self._lora.is_running:
            return True
        if self._nbiot and self._nbiot.is_connected:
            return True
        if self._mqtt and self._mqtt.is_connected:
            return True
        return False

    def _upload_via_backlog(self, data_type: str, data: dict) -> bool:
        """Upload a backlogged record via available channels."""
        if data_type == "alarm":
            if self._nbiot and self._nbiot.is_connected:
                return self._nbiot.publish_alarm(data.get("alarm", data))
            if self._mqtt and self._mqtt.is_connected:
                return self._mqtt.publish_alarm(data.get("alarm", data))
        elif data_type in ("sensor_data", "data"):
            sensor = data.get("sensor", {})
            corrosion = data.get("corrosion", {})
            if self._nbiot and self._nbiot.is_connected:
                return self._nbiot.publish_sensor_data(sensor, corrosion)
            if self._mqtt and self._mqtt.is_connected:
                return self._mqtt.publish_data(sensor, corrosion)
        return False

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_upload_status(self) -> dict:
        """
        Get upload statistics: pending, sent, failed counts.

        Returns:
            Dictionary with upload statistics per channel.
        """
        with self._stats_lock:
            base = {
                "sent": self._upload_sent,
                "failed": self._upload_failed,
                "pending_local": len(self._upload_queue),
            }

        if self._backlog:
            base["pending_backlog"] = self._backlog.pending_count

        channels = {}
        if self._lora:
            channels["lora"] = self._lora.statistics
        if self._nbiot:
            channels["nbiot"] = self._nbiot.statistics
        if self._modbus:
            channels["modbus"] = self._modbus.statistics
        if self._mqtt:
            channels["mqtt"] = self._mqtt.statistics

        base["channels"] = channels
        base["primary"] = self._primary_channel

        return base

    def get_channel(self, name: str) -> Optional[Any]:
        """
        Get a communication channel by name.

        Args:
            name: 'lora', 'nbiot', 'modbus', or 'mqtt'.

        Returns:
            The channel instance, or None if not available.
        """
        return self._channels.get(name)

    # ------------------------------------------------------------------
    # Modbus Integration
    # ------------------------------------------------------------------

    def update_modbus_registers(
        self,
        temperature: float,
        humidity: float,
        delta_d: float,
        cr_out: float,
        eta: float,
        status_word: int = 0,
    ) -> None:
        """
        Update Modbus holding registers with latest process data.

        Args:
            temperature: Temperature in °C.
            humidity: Relative humidity in %.
            delta_d: Thickness loss in μm.
            cr_out: Fused corrosion rate output in μm/year.
            eta: Corrosion efficiency factor.
            status_word: Status bit flags.
        """
        if self._modbus:
            self._modbus.update_process_data(
                temperature=temperature,
                humidity=humidity,
                delta_d=delta_d,
                cr_out=cr_out,
                eta=eta,
                status_word=status_word,
            )

    def update_modbus_alarms(self, alarm_bitmask: int) -> None:
        """Map alarm bitmask to Modbus coils 1-8."""
        if self._modbus:
            self._modbus.set_alarm_flags(alarm_bitmask)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_config(self, path: str, default: Any) -> Any:
        try:
            value = self._config.get(path, default)
            return value if value is not None else default
        except Exception:
            return default

    @property
    def primary_channel(self) -> str:
        return self._primary_channel

    @primary_channel.setter
    def primary_channel(self, channel: str) -> None:
        if channel in ("lora", "nbiot"):
            self._primary_channel = channel
            _logger.info("Primary channel switched to %s", channel)
        else:
            _logger.warning("Invalid primary channel: %s", channel)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Close all connections gracefully."""
        self._running = False

        if self._backlog:
            self._backlog.shutdown()
        if self._lora:
            self._lora.shutdown()
        if self._nbiot:
            self._nbiot.shutdown()
        if self._modbus:
            self._modbus.shutdown()
        if self._mqtt:
            self._mqtt.shutdown()

        _logger.info("CommunicationManager shut down – all channels closed")
