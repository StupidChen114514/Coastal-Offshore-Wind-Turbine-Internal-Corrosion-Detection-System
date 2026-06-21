"""
Communication modules for the Wind Turbine Internal Corrosion Detection System.

Channels:
    - LoRaWAN          – low-power long-range radio (primary field)
    - NB-IoT           – cellular narrowband IoT (alternate primary)
    - Modbus TCP       – local SCADA/PLC integration (port 502)
    - MQTT             – cloud IoT platform (Alibaba/Huawei/AWS)

Components:
    - CommunicationManager  – unified interface orchestrating all channels
    - DataPacket            – binary/JSON serialisation for telemetry
    - BacklogManager        – offline data buffer with smart replay
"""

from .backlog_manager import BacklogManager
from .comm_manager import CommunicationManager
from .data_packet import DataPacket, MessageType
from .lorawan_channel import LoRaWANChannel
from .modbus_server import ModbusServer
from .mqtt_client import CloudPlatform, MQTTClient
from .nbiot_channel import NBIoTChannel

__all__ = [
    "CommunicationManager",
    "DataPacket",
    "MessageType",
    "LoRaWANChannel",
    "NBIoTChannel",
    "ModbusServer",
    "MQTTClient",
    "CloudPlatform",
    "BacklogManager",
]
