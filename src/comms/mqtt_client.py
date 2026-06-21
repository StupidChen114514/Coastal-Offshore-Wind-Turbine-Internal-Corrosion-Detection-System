"""
MQTT client for cloud IoT platform integration.

Supports major cloud IoT platforms:
    - Alibaba Cloud IoT  (aliyun)
    - Huawei Cloud IoT   (huawei)
    - AWS IoT Core       (aws)

Features:
    - QoS=1 (at least once delivery) for data integrity
    - Auto-reconnect with exponential backoff (1s → 2s → 4s → ... → 60s max)
    - Last Will and Testament (LWT) for offline detection
    - Standardised cloud topic structure
    - Configurable TLS 1.2 support

MQTT Topics per platform:

    Alibaba Cloud IoT:
        /{product_key}/{device_id}/thing/event/property/post
        /{product_key}/{device_id}/thing/event/alarm/post
        /{product_key}/{device_id}/thing/service/property/set

    Huawei Cloud IoT:
        /v1/devices/{device_id}/data
        /v1/devices/{device_id}/alarm
        /v1/devices/{device_id}/command

    AWS IoT Core:
        $aws/things/{device_id}/shadow/update
        $aws/things/{device_id}/shadow/update/delta
        $aws/things/{device_id}/events
"""

import json
import ssl
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from ..core.logger import CorrosionLogger
from .data_packet import DataPacket

_logger = CorrosionLogger().get_logger("MQTTClient")


class CloudPlatform(Enum):
    ALIBABA = "aliyun"
    HUAWEI = "huawei"
    AWS = "aws"
    GENERIC = "generic"


class MQTTClient:
    """
    Cloud MQTT client supporting Alibaba/Huawei/AWS IoT platforms.

    Manages connection lifecycle, topic publishing/subscription,
    auto-reconnection with exponential backoff, and QoS=1 delivery.
    """

    _QOS = 1
    _KEEPALIVE = 60
    _MAX_BACKOFF_INTERVAL = 60
    _INITIAL_BACKOFF = 1
    _BACKOFF_MULTIPLIER = 2
    _MAX_RETRIES = 10

    def __init__(self, config_manager: Any) -> None:
        self._config = config_manager
        self._data_packet = DataPacket()

        self._platform = CloudPlatform.GENERIC
        self._broker: str = "mqtt.cloud.example.com"
        self._port: int = 8883
        self._client_id: str = "WTICDS-001"
        self._device_id: str = "WTICDS-001"
        self._product_key: str = "a1xTgH2kPqR"
        self._username: str = ""
        self._password: str = ""
        self._use_tls: bool = True
        self._ca_cert_path: Optional[str] = None
        self._cert_path: Optional[str] = None
        self._key_path: Optional[str] = None

        self._running = False
        self._connected = False
        self._initialized = False
        self._lock = threading.Lock()
        self._reconnect_attempt = 0
        self._reconnect_thread: Optional[threading.Thread] = None

        self._client = None

        self._on_config_received: Optional[Callable[[Dict[str, Any]], None]] = None
        self._publish_callback: Optional[Callable[[str, str, int], bool]] = None

        self._sent_count: int = 0
        self._fail_count: int = 0

        self._lwt_topic: str = ""
        self._lwt_payload: str = '{"status":"offline"}'

    def initialize(self) -> bool:
        """Configure MQTT parameters from config."""
        try:
            platform_str = str(
                self._get_config("comms.cloud.platform.value", "generic")
            ).lower()

            platform_map = {
                "aliyun": CloudPlatform.ALIBABA,
                "alibaba": CloudPlatform.ALIBABA,
                "huawei": CloudPlatform.HUAWEI,
                "aws": CloudPlatform.AWS,
                "generic": CloudPlatform.GENERIC,
            }
            self._platform = platform_map.get(platform_str, CloudPlatform.GENERIC)

            self._broker = str(
                self._get_config("comms.cloud.server_address.value", "mqtt.cloud.example.com")
            )
            self._port = int(self._get_config("comms.cloud.server_port.value", 8883))
            self._device_id = str(self._get_config("comms.cloud.device_id.value", "WTICDS-001"))
            self._product_key = str(
                self._get_config("comms.cloud.product_key.value", "a1xTgH2kPqR")
            )
            self._username = str(self._get_config("comms.cloud.username.value", ""))
            self._password = str(self._get_config("comms.cloud.password.value", ""))
            self._use_tls = bool(self._get_config("comms.cloud.use_tls.value", True))

            self._client_id = f"{self._device_id}_{int(time.time())}"

            self._setup_lwt()

            self._init_client()

            self._initialized = True
            _logger.info(
                "MQTT client initialised: platform=%s, broker=%s:%d, device=%s",
                self._platform.value, self._broker, self._port, self._device_id,
            )
            return True
        except Exception as exc:
            _logger.error("MQTT client initialisation failed: %s", exc)
            return False

    def start(self) -> None:
        """Connect to MQTT broker and start services."""
        if not self._initialized:
            _logger.warning("MQTT client not initialised")
            return

        self._running = True

        if self._connect():
            self._subscribe_topics()
            _logger.info("MQTT client connected and subscribed")
        else:
            _logger.warning("MQTT initial connection failed, will retry")
            self._start_reconnect()

    def stop(self) -> None:
        """Disconnect MQTT gracefully."""
        self._running = False
        self._disconnect()
        _logger.info("MQTT client stopped")

    # ------------------------------------------------------------------
    # Connection Management
    # ------------------------------------------------------------------

    def _connect(self) -> bool:
        """Establish connection to MQTT broker."""
        with self._lock:
            try:
                if self._client is None:
                    self._init_client()

                if self._publish_callback is None:
                    self._connected = True
                    self._reconnect_attempt = 0
                    _logger.info("MQTT connected (simulated)")
                    return True

                result = self._publish_callback("__connect_test__", "", self._QOS)
                if result:
                    self._connected = True
                    self._reconnect_attempt = 0
                    _logger.info("MQTT connected to %s:%d", self._broker, self._port)
                    return True

                return False

            except Exception as exc:
                _logger.error("MQTT connection failed: %s", exc)
                return False

    def _disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        with self._lock:
            self._connected = False
            self._client = None
        _logger.info("MQTT disconnected")

    def _init_client(self) -> None:
        """Initialise MQTT client with platform-specific configuration."""
        client_id = f"{self._device_id}_{int(time.time())}"

        try:
            import paho.mqtt.client as mqtt

            self._client = mqtt.Client(
                client_id=client_id,
                clean_session=True,
                protocol=mqtt.MQTTv311,
            )

            self._client.username_pw_set(self._username, self._password)

            if self._use_tls:
                tls_context = self._build_tls_context()
                if tls_context:
                    self._client.tls_set_context(tls_context)

            self._client.will_set(
                self._lwt_topic,
                payload=self._lwt_payload,
                qos=self._QOS,
                retain=True,
            )

            self._client.on_connect = self._on_mqtt_connect
            self._client.on_disconnect = self._on_mqtt_disconnect
            self._client.on_message = self._on_mqtt_message

            self._client.connect_async(self._broker, self._port, self._KEEPALIVE)
            self._client.loop_start()

        except ImportError:
            _logger.info("paho-mqtt not available, using simulated MQTT mode")
            self._client = None

    def _build_tls_context(self) -> Optional[ssl.SSLContext]:
        """Build TLS 1.2 context for secure MQTT connection."""
        try:
            tls_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            tls_context.minimum_version = ssl.TLSVersion.TLSv1_2

            if self._ca_cert_path:
                tls_context.load_verify_locations(cafile=self._ca_cert_path)
            if self._cert_path and self._key_path:
                tls_context.load_cert_chain(
                    certfile=self._cert_path,
                    keyfile=self._key_path,
                )

            return tls_context
        except Exception as exc:
            _logger.error("TLS context creation failed: %s", exc)
            return None

    def _start_reconnect(self) -> None:
        """Start background reconnection with exponential backoff."""
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            return

        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop,
            daemon=True,
            name="mqtt-reconnect",
        )
        self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        """Exponential backoff reconnection loop."""
        while self._running and not self._connected:
            if self._reconnect_attempt >= self._MAX_RETRIES:
                _logger.error("MQTT max reconnection attempts reached")
                break

            delay = min(
                self._INITIAL_BACKOFF * (self._BACKOFF_MULTIPLIER ** self._reconnect_attempt),
                self._MAX_BACKOFF_INTERVAL,
            )

            self._reconnect_attempt += 1
            _logger.info(
                "MQTT reconnect attempt %d in %.1fs",
                self._reconnect_attempt, delay,
            )

            time.sleep(delay)

            if not self._running:
                break

            if self._connect():
                self._subscribe_topics()
                break

    # ------------------------------------------------------------------
    # MQTT Callbacks
    # ------------------------------------------------------------------

    def _on_mqtt_connect(self, client, userdata, flags, rc) -> None:
        """Callback when MQTT broker connection is established."""
        if rc == 0:
            self._connected = True
            self._reconnect_attempt = 0
            _logger.info("MQTT broker connected (rc=%d)", rc)
        else:
            self._connected = False
            _logger.error("MQTT broker connection refused (rc=%d)", rc)

    def _on_mqtt_disconnect(self, client, userdata, rc) -> None:
        """Callback when MQTT broker connection is lost."""
        self._connected = False
        _logger.warning("MQTT broker disconnected (rc=%d)", rc)
        if self._running:
            self._start_reconnect()

    def _on_mqtt_message(self, client, userdata, msg) -> None:
        """Callback when a downlink MQTT message is received."""
        try:
            topic = msg.topic
            payload = msg.payload.decode("utf-8")

            _logger.debug("MQTT downlink: topic=%s", topic)

            if self._is_config_topic(topic):
                command = self._data_packet.unpack_json(payload)
                if command and self._on_config_received:
                    self._on_config_received(command)

        except Exception as exc:
            _logger.error("MQTT message handling error: %s", exc)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish_data(
        self,
        sensor_data: Dict[str, Any],
        corrosion_record: Dict[str, Any],
    ) -> bool:
        """
        Publish sensor + corrosion data to the cloud MQTT topic.

        Args:
            sensor_data: Sensor readings dict.
            corrosion_record: Corrosion processing results dict.

        Returns:
            True if published successfully.
        """
        if not self._running:
            return False

        topic = self._get_data_topic()
        payload = self._data_packet.pack_sensor_json(sensor_data, corrosion_record)
        return self._publish(topic, payload)

    def publish_alarm(self, alarm_record: Dict[str, Any]) -> bool:
        """
        Publish alarm notification to the cloud MQTT topic.

        Args:
            alarm_record: Alarm data dict.

        Returns:
            True if published successfully.
        """
        if not self._running:
            return False

        topic = self._get_alarm_topic()
        payload = self._data_packet.pack_alarm_json(alarm_record)
        return self._publish(topic, payload)

    def publish_status(self, status_data: Dict[str, Any]) -> bool:
        """
        Publish device status update to the cloud.

        Args:
            status_data: Status information dict.

        Returns:
            True if published successfully.
        """
        if not self._running:
            return False

        topic = self._get_status_topic()
        payload = self._data_packet.pack_status_json(status_data)
        return self._publish(topic, payload)

    def _publish(self, topic: str, payload: str) -> bool:
        """Internal publish with error handling."""
        with self._lock:
            try:
                if self._client is not None:
                    try:
                        import paho.mqtt.client as mqtt

                        result = self._client.publish(topic, payload, qos=self._QOS)
                        if result.rc == mqtt.MQTT_ERR_SUCCESS:
                            self._sent_count += 1
                            return True
                    except Exception:
                        self._fail_count += 1
                        return False

                if self._publish_callback:
                    result = self._publish_callback(topic, payload, self._QOS)
                    if result:
                        self._sent_count += 1
                        return True

                self._fail_count += 1
                _logger.error("MQTT publish failed for topic %s", topic)
                return False

            except Exception as exc:
                _logger.error("MQTT publish exception: %s", exc)
                self._fail_count += 1
                return False

    # ------------------------------------------------------------------
    # Topics per Platform
    # ------------------------------------------------------------------

    def _get_data_topic(self) -> str:
        if self._platform == CloudPlatform.ALIBABA:
            return f"/{self._product_key}/{self._device_id}/thing/event/property/post"
        elif self._platform == CloudPlatform.HUAWEI:
            return f"/v1/devices/{self._device_id}/data"
        elif self._platform == CloudPlatform.AWS:
            return f"$aws/things/{self._device_id}/events"
        else:
            return f"data/{self._device_id}/sensor"

    def _get_alarm_topic(self) -> str:
        if self._platform == CloudPlatform.ALIBABA:
            return f"/{self._product_key}/{self._device_id}/thing/event/alarm/post"
        elif self._platform == CloudPlatform.HUAWEI:
            return f"/v1/devices/{self._device_id}/alarm"
        elif self._platform == CloudPlatform.AWS:
            return f"$aws/things/{self._device_id}/events/alarm"
        else:
            return f"data/{self._device_id}/alarm"

    def _get_status_topic(self) -> str:
        if self._platform == CloudPlatform.ALIBABA:
            return f"/{self._product_key}/{self._device_id}/thing/event/property/post"
        elif self._platform == CloudPlatform.HUAWEI:
            return f"/v1/devices/{self._device_id}/status"
        elif self._platform == CloudPlatform.AWS:
            return f"$aws/things/{self._device_id}/shadow/update"
        else:
            return f"data/{self._device_id}/status"

    def _get_config_topic(self) -> str:
        if self._platform == CloudPlatform.ALIBABA:
            return f"/{self._product_key}/{self._device_id}/thing/service/property/set"
        elif self._platform == CloudPlatform.HUAWEI:
            return f"/v1/devices/{self._device_id}/command"
        elif self._platform == CloudPlatform.AWS:
            return f"$aws/things/{self._device_id}/shadow/update/delta"
        else:
            return f"cmd/{self._device_id}/config"

    def _is_config_topic(self, topic: str) -> bool:
        config_topic = self._get_config_topic()
        return topic == config_topic or topic.startswith(config_topic.rsplit("/", 1)[0])

    def _subscribe_topics(self) -> None:
        """Subscribe to downlink configuration topic."""
        if self._client is not None:
            try:
                topic = self._get_config_topic()
                self._client.subscribe(topic, qos=self._QOS)
                _logger.info("Subscribed to config topic: %s", topic)
            except Exception as exc:
                _logger.error("MQTT subscribe failed: %s", exc)

    # ------------------------------------------------------------------
    # Last Will & Testament
    # ------------------------------------------------------------------

    def _setup_lwt(self) -> None:
        """Configure Last Will and Testament for offline detection."""
        if self._platform == CloudPlatform.ALIBABA:
            self._lwt_topic = (
                f"/{self._product_key}/{self._device_id}/thing/event/property/post"
            )
        elif self._platform == CloudPlatform.HUAWEI:
            self._lwt_topic = f"/v1/devices/{self._device_id}/status"
        else:
            self._lwt_topic = f"data/{self._device_id}/status"

        self._lwt_payload = json.dumps({
            "device_id": self._device_id,
            "status": "offline",
            "timestamp": int(time.time()),
        })

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def set_on_config(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Set callback for downlink configuration commands."""
        self._on_config_received = callback

    def set_publish_callback(self, callback: Callable[[str, str, int], bool]) -> None:
        """
        Set custom publish callback (topic, payload, qos) -> bool.

        Useful for testing or when a custom transport layer is needed.
        """
        self._publish_callback = callback

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def platform(self) -> CloudPlatform:
        return self._platform

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    def statistics(self) -> dict:
        with self._lock:
            return {
                "connected": self._connected,
                "messages_sent": self._sent_count,
                "messages_failed": self._fail_count,
                "broker": self._broker,
                "port": self._port,
                "platform": self._platform.value,
                "reconnect_attempt": self._reconnect_attempt,
            }

    def shutdown(self) -> None:
        """Gracefully shutdown the MQTT client."""
        self.stop()
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
        _logger.info("MQTT client shut down")
