"""
LoRaWAN communication channel for low-power long-range data transmission.

Implements compact binary packet encoding with AES-128-GCM encryption,
fragmentation for payloads exceeding 51 bytes, and configurable radio
parameters (frequency, spreading factor, bandwidth, coding rate, TX power).

Packet format (before encryption):
    [Header:2B][DeviceID:4B][Timestamp:4B][Data:variable][CRC:2B]
"""

import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from ..core.crypto_utils import CryptoUtils
from ..core.logger import CorrosionLogger
from .data_packet import DataPacket, MessageType

_logger = CorrosionLogger().get_logger("LoRaWAN")


class LoRaWANChannel:
    """
    LoRaWAN communication channel with AES-128 encryption and fragmentation.

    Simulates a LoRa radio modem interface. In production, this would be
    replaced with actual SX1276/SX1262 driver calls.
    """

    _LORA_MAX_PAYLOAD = 51
    _DEFAULT_ENCRYPTION_KEY = b"\x00" * 16

    def __init__(self, config_manager: Any) -> None:
        self._config = config_manager
        self._data_packet = DataPacket()
        self._initialized = False
        self._running = False
        self._lock = threading.Lock()

        self._encryption_key = self._DEFAULT_ENCRYPTION_KEY
        self._frequency: float = 433.0
        self._spreading_factor: int = 7
        self._bandwidth: int = 125
        self._coding_rate: int = 5
        self._tx_power: int = 14
        self._device_id: int = 1

        self._send_callback: Optional[Callable[[bytes], bool]] = None
        self._receive_callback: Optional[Callable[[bytes], None]] = None

        self._packet_sent_count: int = 0
        self._packet_fail_count: int = 0
        self._last_tx_time: float = 0.0

    def initialize(self) -> bool:
        """Configure LoRa radio parameters from config."""
        try:
            self._frequency = float(
                self._get_config("comms.lora.frequency.value", 433.0)
            )
            self._spreading_factor = int(
                self._get_config("comms.lora.spreading_factor.value", 7)
            )
            self._bandwidth = int(
                self._get_config("comms.lora.bandwidth.value", 125)
            )
            self._coding_rate = int(
                self._get_config("comms.lora.coding_rate.value", 5)
            )
            self._tx_power = int(
                self._get_config("comms.lora.tx_power.value", 14)
            )

            key_str = self._get_config("comms.lora.encryption_key.value", None)
            if key_str:
                key_bytes = key_str.encode("utf-8")[:16]
                if len(key_bytes) < 16:
                    key_bytes = key_bytes.ljust(16, b"\x00")
                self._encryption_key = key_bytes

            self._initialized = True
            _logger.info(
                "LoRaWAN initialised: freq=%.1fMHz, SF=%d, BW=%dkHz, CR=%d, TX=%ddBm",
                self._frequency,
                self._spreading_factor,
                self._bandwidth,
                self._coding_rate,
                self._tx_power,
            )
            return True
        except Exception as exc:
            _logger.error("LoRaWAN initialisation failed: %s", exc)
            return False

    def start(self) -> None:
        """Start the LoRa radio (simulated)."""
        if not self._initialized:
            _logger.warning("LoRaWAN not initialised, cannot start")
            return
        self._running = True
        _logger.info("LoRaWAN channel started")

    def stop(self) -> None:
        """Stop the LoRa radio."""
        self._running = False
        _logger.info("LoRaWAN channel stopped")

    # ------------------------------------------------------------------
    # Data Transmission
    # ------------------------------------------------------------------

    def send_data(
        self,
        sensor_data: Dict[str, Any],
        corrosion_record: Dict[str, Any],
    ) -> bool:
        """
        Pack, encrypt, and send sensor data via LoRa.

        Args:
            sensor_data: Sensor readings (T, RH, Cl_deposition).
            corrosion_record: Corrosion processing results.

        Returns:
            True if packet was sent (queued), False on error.
        """
        if not self._running:
            _logger.warning("LoRaWAN not running, cannot send data")
            return False

        try:
            packet = self._data_packet.pack_sensor_data(sensor_data, corrosion_record)
            encrypted = self._encrypt(packet)

            fragments = self._data_packet.split_for_lora(encrypted)

            for i, fragment in enumerate(fragments):
                if len(fragment) > self._LORA_MAX_PAYLOAD:
                    _logger.error(
                        "Fragment %d exceeds LoRa max payload (%d > %d)",
                        i, len(fragment), self._LORA_MAX_PAYLOAD,
                    )
                    return False

            return self._transmit(fragments)

        except Exception as exc:
            _logger.error("LoRaWAN send_data failed: %s", exc)
            self._packet_fail_count += 1
            return False

    def send_alarm(self, alarm_record: Dict[str, Any]) -> bool:
        """
        Pack, encrypt, and send an alarm notification via LoRa.

        Args:
            alarm_record: Alarm data dictionary.

        Returns:
            True if sent successfully.
        """
        if not self._running:
            _logger.warning("LoRaWAN not running, cannot send alarm")
            return False

        try:
            packet = self._data_packet.pack_alarm(alarm_record)
            encrypted = self._encrypt(packet)

            fragments = self._data_packet.split_for_lora(encrypted)
            return self._transmit(fragments)

        except Exception as exc:
            _logger.error("LoRaWAN send_alarm failed: %s", exc)
            self._packet_fail_count += 1
            return False

    def send_raw(self, data: bytes) -> bool:
        """
        Send raw bytes via LoRa (caller handles packing/encryption).

        Args:
            data: Raw bytes to transmit.

        Returns:
            True if within payload limit and sent.
        """
        if not self._running:
            return False

        if len(data) > self._LORA_MAX_PAYLOAD:
            _logger.error("Raw data exceeds LoRa payload limit")
            return False

        encrypted = self._encrypt(data)
        return self._transmit([encrypted])

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def set_send_callback(self, callback: Callable[[bytes], bool]) -> None:
        """
        Set a callback that actually transmits bytes over the radio.

        Useful for testing or when a real radio HAL is available.
        """
        self._send_callback = callback

    def set_receive_callback(self, callback: Callable[[bytes], None]) -> None:
        """Set a callback for received packets (downlink handling)."""
        self._receive_callback = callback

    def receive_packet(self, data: bytes) -> Optional[Dict[str, Any]]:
        """
        Process a received LoRa packet (decrypt, verify CRC, unpack).

        Args:
            data: Raw received bytes.

        Returns:
            Decoded dictionary or None on failure.
        """
        try:
            decrypted = self._decrypt(data)

            if len(decrypted) < 30:
                body = decrypted[:-2]
                crc_received = struct.unpack("<H", decrypted[-2:])[0]
                crc_computed = CryptoUtils.crc16(body)

                if crc_received != crc_computed:
                    _logger.warning("LoRa packet CRC mismatch")
                    return None

            return self._data_packet.unpack_sensor_data(decrypted)

        except Exception as exc:
            _logger.error("LoRa packet receive processing failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Encryption
    # ------------------------------------------------------------------

    def set_encryption_key(self, key: bytes) -> None:
        """Set the AES-128 encryption key (must be 16 bytes)."""
        if len(key) != 16:
            raise ValueError("Encryption key must be exactly 16 bytes")
        self._encryption_key = key

    def _encrypt(self, data: bytes) -> bytes:
        return CryptoUtils.aes_encrypt(data, self._encryption_key)

    def _decrypt(self, data: bytes) -> bytes:
        return CryptoUtils.aes_decrypt(data, self._encryption_key)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _transmit(self, fragments: List[bytes]) -> bool:
        """Simulate radio transmission of one or more fragments."""
        with self._lock:
            for fragment in fragments:
                success = False

                if self._send_callback:
                    success = self._send_callback(fragment)

                if not self._send_callback or success:
                    success = True

                if success:
                    self._packet_sent_count += 1
                    self._last_tx_time = time.time()
                else:
                    self._packet_fail_count += 1
                    _logger.error("LoRa transmission failed for fragment")
                    return False

                if len(fragments) > 1:
                    time.sleep(0.05)

            return True

    def _get_config(self, path: str, default: Any) -> Any:
        try:
            value = self._config.get(path, default)
            return value if value is not None else default
        except Exception:
            return default

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def frequency(self) -> float:
        return self._frequency

    @property
    def statistics(self) -> dict:
        with self._lock:
            return {
                "packets_sent": self._packet_sent_count,
                "packets_failed": self._packet_fail_count,
                "last_tx_time": self._last_tx_time,
                "frequency": self._frequency,
                "spreading_factor": self._spreading_factor,
                "tx_power": self._tx_power,
            }

    def shutdown(self) -> None:
        """Gracefully shutdown the LoRa channel."""
        self.stop()
        _logger.info("LoRaWAN channel shut down")
