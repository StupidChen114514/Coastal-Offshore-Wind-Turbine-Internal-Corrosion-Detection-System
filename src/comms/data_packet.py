"""
Data packet serialisation and deserialisation for telemetry data.

Supports two formats:
    - Compact binary (LoRa, 28 bytes): struct.pack with CRC-16
    - JSON (MQTT / HTTP): human-readable, extensible

Binary Packet Layout (28 bytes):
    Byte 0:     Version (0x01)
    Byte 1:     Message Type (0x01=data, 0x02=alarm, 0x03=status)
    Byte 2-5:   Device ID (uint32)
    Byte 6-9:   Timestamp (uint32, Unix epoch)
    Byte 10-11: Temperature (int16, ×100 °C)
    Byte 12-13: Humidity (uint16, ×10 %)
    Byte 14-15: Cl⁻ deposition (uint16, ×10 mg/(m²·day))
    Byte 16-17: Δd_ER (uint16, ×1000 μm)
    Byte 18-19: Δd_Inductive (uint16, ×1000 μm)
    Byte 20-21: CR_filtered (uint16, ×1000 μm/year)
    Byte 22-23: η (uint16, ×100)
    Byte 24:    ValidFlag + AlarmStatus (bit flags)
    Byte 25:    Alarm bitmask
    Byte 26-27: CRC-16 (CCITT)
"""

import json
import struct
import time
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Dict, Optional, Tuple

from ..core.crypto_utils import CryptoUtils


class MessageType(IntEnum):
    DATA = 0x01
    ALARM = 0x02
    STATUS = 0x03


class DataPacket:
    """Serialises / deserialises sensor and corrosion data for transmission."""

    _PROTOCOL_VERSION = 0x01

    _BINARY_BODY_FMT = "<B B I I h H H H H H H B B"
    _BINARY_SIZE = struct.calcsize(_BINARY_BODY_FMT) + 2

    _LORA_MAX_PAYLOAD = 51
    _LORA_OVERHEAD = 28
    _LORA_SPLIT_THRESHOLD = _LORA_MAX_PAYLOAD - 6

    def __init__(
        self,
        device_id: int = 1,
        message_type: MessageType = MessageType.DATA,
    ) -> None:
        self._version = self._PROTOCOL_VERSION
        self._device_id = device_id
        self._message_type = message_type
        self._sequence_number = 0

    @property
    def sequence_number(self) -> int:
        return self._sequence_number

    def _next_seq(self) -> int:
        self._sequence_number = (self._sequence_number + 1) % 65536
        return self._sequence_number

    # ------------------------------------------------------------------
    # Binary Packing (LoRa)
    # ------------------------------------------------------------------

    def pack_sensor_data(
        self,
        sensor_data: Dict[str, Any],
        corrosion_record: Dict[str, Any],
    ) -> bytes:
        """
        Pack sensor + corrosion data into compact binary format.

        Args:
            sensor_data: Dict with keys T, RH, Cl_deposition
            corrosion_record: Dict with keys delta_d_ER, delta_d_Inductive,
                              CR_out, eta, valid_flag

        Returns:
            28-byte packed binary packet.
        """
        timestamp = int(time.time())

        t_val = int(self._safe_float(sensor_data.get("T", 0)) * 100)
        rh_val = int(self._safe_float(sensor_data.get("RH", 0)) * 10)
        cl_val = int(self._safe_float(sensor_data.get("Cl_deposition", 0)) * 10)

        dd_er = int(self._safe_float(corrosion_record.get("delta_d_ER", 0)) * 1000)
        dd_ind = int(self._safe_float(corrosion_record.get("delta_d_Inductive", 0)) * 1000)
        cr_val = int(self._safe_float(corrosion_record.get("CR_out", 0)) * 1000)
        eta_val = int(self._safe_float(corrosion_record.get("eta", 0)) * 100)

        valid_flag = int(corrosion_record.get("valid_flag", True))
        alarm_status = int(corrosion_record.get("alarm_status", 0))
        flags = ((valid_flag & 0x01) << 0) | ((alarm_status & 0x7F) << 1)

        alarm_bitmask = int(corrosion_record.get("alarm_bitmask", 0x00)) & 0xFF

        packet_body = struct.pack(
            self._BINARY_BODY_FMT,
            self._version,
            self._message_type,
            self._device_id,
            timestamp,
            max(-32768, min(32767, t_val)),
            max(0, min(65535, rh_val)),
            max(0, min(65535, cl_val)),
            max(0, min(65535, dd_er)),
            max(0, min(65535, dd_ind)),
            max(0, min(65535, cr_val)),
            max(0, min(65535, eta_val)),
            flags,
            alarm_bitmask,
        )

        crc = CryptoUtils.crc16(packet_body)
        packet = packet_body + struct.pack("<H", crc)

        return packet

    def unpack_sensor_data(self, raw: bytes) -> Optional[Dict[str, Any]]:
        """
        Unpack a compact binary packet back into a dictionary.

        Args:
            raw: 28-byte binary packet.

        Returns:
            Dictionary with decoded values, or None on checksum failure.
        """
        if len(raw) < self._BINARY_SIZE:
            return None

        body = raw[:26]
        received_crc = struct.unpack("<H", raw[26:28])[0]
        computed_crc = CryptoUtils.crc16(body)

        if received_crc != computed_crc:
            return None

        (
            version,
            msg_type,
            device_id,
            timestamp,
            t_raw,
            rh_raw,
            cl_raw,
            dd_er_raw,
            dd_ind_raw,
            cr_raw,
            eta_raw,
            flags,
            alarm_bitmask,
        ) = struct.unpack(self._BINARY_BODY_FMT, body)

        valid_flag = bool(flags & 0x01)
        alarm_status = (flags >> 1) & 0x7F

        return {
            "version": version,
            "message_type": msg_type,
            "device_id": device_id,
            "timestamp": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
            "T": t_raw / 100.0,
            "RH": rh_raw / 10.0,
            "Cl_deposition": cl_raw / 10.0,
            "delta_d_ER": dd_er_raw / 1000.0,
            "delta_d_Inductive": dd_ind_raw / 1000.0,
            "CR_out": cr_raw / 1000.0,
            "eta": eta_raw / 100.0,
            "valid_flag": valid_flag,
            "alarm_status": alarm_status,
            "alarm_bitmask": alarm_bitmask,
        }

    def pack_alarm(self, alarm_record: Dict[str, Any]) -> bytes:
        """
        Pack an alarm record into compact binary.

        Args:
            alarm_record: Dict with alarm data (level, type, sensor_id, message).

        Returns:
            Packed binary bytes for LoRa transmission.
        """
        timestamp = int(time.time())

        alarm_level = int(alarm_record.get("level", 1)) & 0x07
        alarm_type_code = self._alarm_type_to_code(alarm_record.get("alarm_type", "CORROSION_RATE"))
        packed = bytearray()

        packed.extend(struct.pack("<B B I I", self._version, MessageType.ALARM, self._device_id, timestamp))

        packed.append(((alarm_level & 0x07) << 5) | (alarm_type_code & 0x1F))

        sensor_id = str(alarm_record.get("sensor_id", ""))[:8]
        sensor_id_bytes = sensor_id.encode("ascii", errors="replace").ljust(8, b"\x00")
        packed.extend(sensor_id_bytes)

        message = str(alarm_record.get("message", "") or alarm_record.get("details", {}).get("message", ""))
        message_bytes = message.encode("utf-8", errors="replace")[:30]
        packed.extend(message_bytes.ljust(30, b"\x00"))

        crc = CryptoUtils.crc16(bytes(packed))
        packed.extend(struct.pack("<H", crc))

        return bytes(packed)

    @staticmethod
    def _alarm_type_to_code(alarm_type: str) -> int:
        mapping = {
            "CORROSION_RATE": 0x01,
            "THICKNESS_LOSS": 0x02,
            "SENSOR_FAULT": 0x03,
            "COMMUNICATION_ERROR": 0x04,
            "SYSTEM_ERROR": 0x05,
            "PITTING_RISK": 0x06,
            "SEVERE_PITTING_PERFORATION": 0x07,
            "ENVIRONMENT_RAPID_CHANGE": 0x08,
            "TEMPERATURE_SHOCK": 0x09,
            "EMERGENCY_MODE": 0x0A,
        }
        return mapping.get(alarm_type, 0x00)

    def split_for_lora(self, data: bytes) -> list:
        """
        Split oversized data into multiple LoRa-compliant fragments.

        Each fragment includes a 6-byte header:
            Byte 0:     Fragment count (total)
            Byte 1:     Fragment index (0-based)
            Byte 2-5:   Message ID (uint32)
            Byte 6+:    Payload chunk

        Args:
            data: Complete binary payload.

        Returns:
            List of fragment bytes, each ≤ 51 bytes.
        """
        msg_id = self._next_seq()
        chunk_size = self._LORA_SPLIT_THRESHOLD
        total = (len(data) + chunk_size - 1) // chunk_size

        if total == 1:
            return [data]

        fragments = []
        for i in range(total):
            chunk = data[i * chunk_size : (i + 1) * chunk_size]
            header = struct.pack("<B B I", total, i, msg_id)
            fragments.append(header + chunk)

        return fragments

    @staticmethod
    def reassemble_fragments(fragments: list) -> Optional[bytes]:
        """
        Reassemble fragmented LoRa packets into the original data.

        Args:
            fragments: List of (total, index, msg_id, payload) tuples or raw bytes.

        Returns:
            Reassembled bytes, or None if incomplete.
        """
        if len(fragments) == 1:
            return fragments[0] if isinstance(fragments[0], bytes) else fragments[0][3]

        parsed = []
        for f in fragments:
            if isinstance(f, bytes):
                total, idx, msg_id = struct.unpack("<B B I", f[:6])
                payload = f[6:]
            else:
                total, idx, msg_id, payload = f
            parsed.append((total, idx, msg_id, payload))

        parsed.sort(key=lambda x: x[1])

        expected_total = parsed[0][0]
        if len(parsed) != expected_total:
            return None

        return b"".join(p[3] for p in parsed)

    # ------------------------------------------------------------------
    # JSON Packing (MQTT / HTTP)
    # ------------------------------------------------------------------

    def pack_sensor_json(
        self,
        sensor_data: Dict[str, Any],
        corrosion_record: Dict[str, Any],
        device_id: Optional[int] = None,
    ) -> str:
        """
        Pack sensor + corrosion data into JSON format for MQTT/HTTP.

        Args:
            sensor_data: Sensor readings dict.
            corrosion_record: Corrosion processing results dict.
            device_id: Override device ID.

        Returns:
            JSON string.
        """
        did = device_id if device_id is not None else self._device_id
        payload = {
            "version": self._version,
            "protocol": "json_v1",
            "device_id": did,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message_type": "data",
            "data": {
                "temperature": {
                    "value": round(self._safe_float(sensor_data.get("T", 0)), 2),
                    "unit": "°C",
                },
                "humidity": {
                    "value": round(self._safe_float(sensor_data.get("RH", 0)), 2),
                    "unit": "%",
                },
                "cl_deposition": {
                    "value": round(self._safe_float(sensor_data.get("Cl_deposition", 0)), 4),
                    "unit": "mg/(m²·day)",
                },
            },
            "corrosion": {
                "delta_d_ER": {
                    "value": round(self._safe_float(corrosion_record.get("delta_d_ER", 0)), 3),
                    "unit": "μm",
                },
                "delta_d_Inductive": {
                    "value": round(self._safe_float(corrosion_record.get("delta_d_Inductive", 0)), 3),
                    "unit": "μm",
                },
                "CR_out": {
                    "value": round(self._safe_float(corrosion_record.get("CR_out", 0)), 4),
                    "unit": "mm/year",
                },
                "eta": {
                    "value": round(self._safe_float(corrosion_record.get("eta", 0)), 2),
                    "unit": "dimensionless",
                },
            },
            "status": {
                "valid_flag": bool(corrosion_record.get("valid_flag", True)),
                "alarm_bitmask": corrosion_record.get("alarm_bitmask", 0),
            },
            "seq": self._next_seq(),
        }
        return json.dumps(payload, ensure_ascii=False)

    def pack_alarm_json(self, alarm_record: Dict[str, Any]) -> str:
        """
        Pack an alarm record into JSON format.

        Args:
            alarm_record: Alarm data dict.

        Returns:
            JSON string.
        """
        payload = {
            "version": self._version,
            "protocol": "json_v1",
            "device_id": self._device_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message_type": "alarm",
            "alarm": {
                "alarm_id": str(alarm_record.get("alarm_id", "")),
                "level": alarm_record.get("level", 1),
                "alarm_type": alarm_record.get("alarm_type", "UNKNOWN"),
                "sensor_id": alarm_record.get("sensor_id", ""),
                "message": alarm_record.get("message", ""),
                "status": alarm_record.get("status", "ACTIVE"),
            },
            "seq": self._next_seq(),
        }
        return json.dumps(payload, ensure_ascii=False)

    def pack_status_json(self, status_data: Dict[str, Any]) -> str:
        """
        Pack system status into JSON format.

        Args:
            status_data: Status information dict.

        Returns:
            JSON string.
        """
        payload = {
            "version": self._version,
            "protocol": "json_v1",
            "device_id": self._device_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message_type": "status",
            "status": status_data,
            "seq": self._next_seq(),
        }
        return json.dumps(payload, ensure_ascii=False)

    def unpack_json(self, json_str: str) -> Optional[Dict[str, Any]]:
        """
        Unpack a JSON packet into a dictionary.

        Args:
            json_str: JSON string.

        Returns:
            Parsed dictionary, or None on failure.
        """
        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @property
    def device_id(self) -> int:
        return self._device_id

    @device_id.setter
    def device_id(self, value: int) -> None:
        self._device_id = value

    @property
    def binary_size(self) -> int:
        return self._BINARY_SIZE
