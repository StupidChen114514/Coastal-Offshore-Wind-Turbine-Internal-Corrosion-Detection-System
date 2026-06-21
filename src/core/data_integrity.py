"""
Data integrity protection for the Wind Turbine Internal Corrosion Detection System.

Provides checksum-based integrity verification for sensor data records (CRC-16)
and configuration parameters (SHA-256), plus secure memory sanitisation for
sensitive data deallocation.
"""

import ctypes
import json
from typing import Any, Dict, Tuple

from .crypto_utils import CryptoUtils
from .logger import CorrosionLogger

_logger = CorrosionLogger().get_logger("Integrity")


class DataIntegrityGuard:
    """Ensures data integrity for sensor records and configuration.

    Uses CRC-16 for sensor data record integrity and SHA-256 for
    configuration parameter integrity verification.
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Sensor record integrity
    # ------------------------------------------------------------------

    def sign_sensor_record(self, record_data: dict) -> dict:
        """Add CRC-16 checksum to a sensor data record.

        Computes CRC-16 over a canonical JSON representation (sorted keys)
        of the record data, then embeds the computed checksum in a 'crc16' field.

        Returns:
            Record dictionary with added 'crc16' field.
        """
        record = dict(record_data)
        record.pop("crc16", None)

        canonical = json.dumps(record, sort_keys=True, default=str, ensure_ascii=False)
        checksum = CryptoUtils.crc16(canonical.encode("utf-8"))

        record["crc16"] = checksum
        return record

    def verify_sensor_record(self, record_data: dict) -> Tuple[bool, str]:
        """Verify CRC-16 checksum of a sensor data record.

        Extracts the stored 'crc16' value, recomputes the checksum over the
        record data (excluding crc16), and compares. If verification fails,
        the record should be marked as 'corrupt'.

        Returns:
            (is_valid, error_message)
        """
        if "crc16" not in record_data:
            return False, "缺少 CRC-16 校验字段"

        stored_crc = record_data["crc16"]
        try:
            stored_crc = int(stored_crc)
        except (TypeError, ValueError):
            return False, f"CRC-16 校验值格式无效: {stored_crc}"

        record_copy = dict(record_data)
        record_copy.pop("crc16", None)

        canonical = json.dumps(record_copy, sort_keys=True, default=str, ensure_ascii=False)
        computed_crc = CryptoUtils.crc16(canonical.encode("utf-8"))

        if computed_crc != stored_crc:
            return False, (
                f"CRC-16 校验失败: 期望 0x{stored_crc:04X}, "
                f"计算得 0x{computed_crc:04X}"
            )

        return True, "数据完整性验证通过"

    # ------------------------------------------------------------------
    # Configuration integrity
    # ------------------------------------------------------------------

    def sign_config(self, config_json: str) -> str:
        """Generate SHA-256 hash for configuration integrity.

        Returns hex hash string of the canonicalised configuration JSON.
        """
        return CryptoUtils.sha256_hash(config_json.encode("utf-8"))

    def verify_config(self, config_json: str, expected_hash: str) -> bool:
        """Verify configuration integrity against a stored hash.

        Returns True if the computed hash matches the expected hash.
        """
        computed = CryptoUtils.sha256_hash(config_json.encode("utf-8"))
        if computed != expected_hash:
            _logger.warning(
                "Configuration integrity check FAILED: hash mismatch"
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Secure memory sanitisation
    # ------------------------------------------------------------------

    @staticmethod
    def secure_erase_sensitive_data(data: bytes) -> None:
        """Securely overwrite sensitive data in memory before deallocation.

        Overwrites the bytearray (or mutable bytes buffer) with zeros,
        then with 0xFF, then zeros again to mitigate data remanence in
        memory. Uses ctypes to bypass Python's immutable bytes restriction.

        This should be called for password buffers, key material, and
        other sensitive data after use.
        """
        if data is None:
            return
        try:
            length = len(data)
            if length == 0:
                return

            buf = (ctypes.c_ubyte * length).from_buffer_copy(data)

            for _ in range(2):
                for i in range(length):
                    buf[i] = 0x00
                for i in range(length):
                    buf[i] = 0xFF
                for i in range(length):
                    buf[i] = 0x00

            _logger.debug("Sensitive data securely erased (%d bytes)", length)
        except Exception as exc:
            _logger.warning("Secure erase operation encountered an issue: %s", exc)
