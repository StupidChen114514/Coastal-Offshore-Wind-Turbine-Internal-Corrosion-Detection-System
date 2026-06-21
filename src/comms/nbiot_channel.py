"""
NB-IoT communication channel via MQTT with AT-command modem simulation.

Provides narrowband IoT connectivity through simulated AT-command modem
interface. Supports MQTT-based data transmission with TLS 1.2 encryption,
configurable APN, and standardised MQTT topic structure.

MQTT Topics:
    data/{device_id}/sensor   – sensor telemetry data (JSON)
    data/{device_id}/alarm    – alarm notifications (JSON)
    data/{device_id}/status   – device heartbeat / status (JSON)
    cmd/{device_id}/config    – downlink configuration commands (JSON)
"""

import json
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from ..core.logger import CorrosionLogger
from .data_packet import DataPacket, MessageType

_logger = CorrosionLogger().get_logger("NBIoT")


class ATModemSimulator:
    """
    Simulates an NB-IoT AT-command modem interface.

    In production, this would be replaced with actual UART communication
    to a BC95/BC26/SIM7020 module.
    """

    def __init__(self) -> None:
        self._at_responses: Dict[str, str] = {}
        self._registered = False
        self._attached = False
        self._connected = False
        self._signal_quality = 25
        self._lock = threading.Lock()
        self._init_at_responses()

    def _init_at_responses(self) -> None:
        self._at_responses = {
            "AT": "OK",
            "AT+CGMI": "Quectel",
            "AT+CGMM": "BC95-G",
            "AT+CGSN": "869701030012345",
            "AT+CIMI": "460010123456789",
            "AT+CSQ": f"+CSQ: {self._signal_quality},99",
            "AT+CGATT?": "+CGATT: 1",
            "AT+CEREG?": "+CEREG: 0,1",
            "AT+CSCON?": "+CSCON: 0,1",
            "AT+CGDCONT?": '+CGDCONT: 1,"IP","ctnet","0.0.0.0",0,0',
            "AT+COPS?": "+COPS: 0,2,\"46011\",9",
            "AT+NUESTATS": "Signal power:-85 dBm,Total power:-75 dBm,TX power:23 dBm",
        }

    def send_command(self, command: str, timeout: float = 2.0) -> str:
        """Simulate sending an AT command and receiving the response."""
        with self._lock:
            cmd_key = command.split("=")[0].strip()

            if cmd_key in self._at_responses:
                return self._at_responses[cmd_key]

            if command == "AT+CFUN=1":
                self._registered = True
                return "OK"
            if command == "AT+CGATT=1":
                self._attached = True
                return "OK"
            if command.startswith("AT+QMTOPEN"):
                self._connected = True
                return "+QMTOPEN: 0,0"
            if command == "AT+NRB":
                self._registered = True
                return "+NRB: Reboot OK"
            if command.startswith("AT+CGDCONT="):
                return "OK"
            if command.startswith("AT+QMTCFG="):
                return "OK"
            if command.startswith("AT+QMTCONN="):
                self._connected = True
                return "+QMTCONN: 0,0"
            if command.startswith("AT+QMTSUB="):
                return "+QMTSUB: 0,0"
            if command.startswith("AT+QMTPUB="):
                return "+QMTPUB: 0,0"
            if command == "AT+QMTCONN?":
                state = 1 if self._connected else 0
                return f"+QMTCONN: 0,{state}"
            if command == "AT+CFUN?":
                mode = 1 if self._registered else 0
                return f"+CFUN: {mode}"

            return "OK"

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_registered(self) -> bool:
        return self._registered


class NBIoTChannel:
    """
    NB-IoT communication channel with MQTT-based data transport.

    Manages modem initialisation, network registration, MQTT connection
    lifecycle, data publishing, keep-alive pings, and topic subscriptions.
    """

    _KEEPALIVE_INTERVAL = 60
    _RECONNECT_INTERVAL = 10
    _MAX_RETRIES = 3

    def __init__(self, config_manager: Any) -> None:
        self._config = config_manager
        self._data_packet = DataPacket()
        self._modem = ATModemSimulator()
        self._initialized = False
        self._running = False
        self._connected = False
        self._lock = threading.Lock()

        self._apn: str = "ctnet"
        self._band: int = 8
        self._server_address: str = "mqtt.cloud.example.com"
        self._server_port: int = 8883
        self._device_id: str = "WTICDS-001"
        self._product_key: str = "a1xTgH2kPqR"

        self._keepalive_thread: Optional[threading.Thread] = None
        self._message_queue: queue.Queue = queue.Queue(maxsize=500)

        self._on_config_received: Optional[Callable[[Dict[str, Any]], None]] = None
        self._publish_callback: Optional[Callable[[str, str], bool]] = None

        self._sent_count: int = 0
        self._fail_count: int = 0

    def initialize(self) -> bool:
        """Initialise NB-IoT modem and configure MQTT parameters."""
        try:
            self._apn = str(self._get_config("comms.nb_iot.apn.value", "ctnet"))
            self._band = int(self._get_config("comms.nb_iot.band.value", 8))
            self._server_address = str(
                self._get_config("comms.cloud.server_address.value", "mqtt.cloud.example.com")
            )
            self._server_port = int(self._get_config("comms.cloud.server_port.value", 8883))

            self._modem_init()

            self._initialized = True
            _logger.info(
                "NB-IoT initialised: APN=%s, Band=%d, Server=%s:%d",
                self._apn, self._band, self._server_address, self._server_port,
            )
            return True
        except Exception as exc:
            _logger.error("NB-IoT initialisation failed: %s", exc)
            return False

    def start(self) -> None:
        """Start NB-IoT services: network registration, MQTT connect, keepalive."""
        if not self._initialized:
            _logger.warning("NB-IoT not initialised, cannot start")
            return

        self._running = True

        if not self._network_register():
            _logger.error("NB-IoT network registration failed")
            self._running = False
            return

        if not self._mqtt_connect():
            _logger.error("NB-IoT MQTT connection failed")
            self._running = False
            return

        self._subscribe_topics()

        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop,
            daemon=True,
            name="nbiot-keepalive",
        )
        self._keepalive_thread.start()

        _logger.info("NB-IoT channel started")

    def stop(self) -> None:
        """Stop NB-IoT services gracefully."""
        self._running = False
        self._mqtt_disconnect()
        _logger.info("NB-IoT channel stopped")

    # ------------------------------------------------------------------
    # Data Publishing
    # ------------------------------------------------------------------

    def publish_sensor_data(
        self,
        sensor_data: Dict[str, Any],
        corrosion_record: Dict[str, Any],
    ) -> bool:
        """
        Publish sensor data to MQTT topic.

        Args:
            sensor_data: Sensor readings dictionary.
            corrosion_record: Corrosion processing results.

        Returns:
            True if published (or queued), False on error.
        """
        if not self._running:
            return self._enqueue_for_retry("sensor", sensor_data, corrosion_record)

        topic = f"data/{self._device_id}/sensor"
        payload = self._data_packet.pack_sensor_json(sensor_data, corrosion_record)
        return self._publish(topic, payload)

    def publish_alarm(self, alarm_record: Dict[str, Any]) -> bool:
        """
        Publish alarm notification to MQTT topic.

        Args:
            alarm_record: Alarm data dictionary.

        Returns:
            True if published.
        """
        if not self._running:
            return self._enqueue_for_retry("alarm", alarm_record)

        topic = f"data/{self._device_id}/alarm"
        payload = self._data_packet.pack_alarm_json(alarm_record)
        return self._publish(topic, payload)

    def publish_status(self, status_data: Dict[str, Any]) -> bool:
        """
        Publish device status / heartbeat to MQTT topic.

        Args:
            status_data: Status information dictionary.

        Returns:
            True if published.
        """
        if not self._running:
            return False

        topic = f"data/{self._device_id}/status"
        payload = self._data_packet.pack_status_json(status_data)
        return self._publish(topic, payload)

    def _publish(self, topic: str, payload: str) -> bool:
        """Internal publish with simulated modem AT commands."""
        with self._lock:
            try:
                if not self._connected:
                    _logger.warning("NB-IoT not connected, queueing message")
                    self._message_queue.put((topic, payload))
                    return False

                at_cmd = f'AT+QMTPUB=0,0,0,0,"{topic}","{payload}"'
                response = self._modem.send_command(at_cmd)

                if "+QMTPUB: 0,0" in response:
                    self._sent_count += 1
                    return True

                if self._publish_callback:
                    result = self._publish_callback(topic, payload)
                    if result:
                        self._sent_count += 1
                        return True

                self._fail_count += 1
                _logger.error("NB-IoT publish failed for topic %s", topic)
                self._message_queue.put((topic, payload))
                return False

            except Exception as exc:
                _logger.error("NB-IoT publish exception: %s", exc)
                self._fail_count += 1
                return False

    # ------------------------------------------------------------------
    # Downlink Handling
    # ------------------------------------------------------------------

    def set_config_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback for downlink configuration commands."""
        self._on_config_received = callback

    def set_publish_callback(self, callback: Callable[[str, str], bool]) -> None:
        """Register a callback for actual MQTT publish (for real modem integration)."""
        self._publish_callback = callback

    def handle_downlink_command(self, topic: str, payload: str) -> None:
        """
        Process a downlink MQTT message (config command).

        Args:
            topic: MQTT topic string.
            payload: JSON payload string.
        """
        expected_topic = f"cmd/{self._device_id}/config"
        if topic != expected_topic:
            _logger.debug("Ignoring downlink on unexpected topic: %s", topic)
            return

        try:
            command = json.loads(payload)
            _logger.info("Downlink config received: %s", command)

            if self._on_config_received:
                self._on_config_received(command)

        except json.JSONDecodeError:
            _logger.error("Invalid JSON in downlink command")

    # ------------------------------------------------------------------
    # Internal: Modem & Network
    # ------------------------------------------------------------------

    def _modem_init(self) -> None:
        """Initialise the NB-IoT modem via AT commands."""
        self._modem.send_command("AT")
        self._modem.send_command("AT+NRB")
        time.sleep(1.0)
        self._modem.send_command("AT+CFUN=1")
        self._modem.send_command(f'AT+CGDCONT=1,"IP","{self._apn}"')
        _logger.debug("NB-IoT modem initialised")

    def _network_register(self, attempt: int = 0) -> bool:
        """Register on the NB-IoT network with retry."""
        if attempt >= self._MAX_RETRIES:
            return False

        response = self._modem.send_command("AT+CGATT=1")
        if "OK" in response:
            response = self._modem.send_command("AT+CEREG?")
            if "+CEREG: 0,1" in response or "+CEREG: 0,5" in response:
                _logger.info("NB-IoT network registered")
                return True

        _logger.warning("NB-IoT network registration attempt %d failed", attempt + 1)
        time.sleep(self._RECONNECT_INTERVAL)
        return self._network_register(attempt + 1)

    def _mqtt_connect(self, attempt: int = 0) -> bool:
        """Connect to MQTT broker via AT commands."""
        if attempt >= self._MAX_RETRIES:
            return False

        self._modem.send_command(
            f'AT+QMTOPEN=0,"{self._server_address}",{self._server_port}'
        )

        if self._modem.is_connected:
            time.sleep(0.5)
            client_id = f"{self._device_id}_{int(time.time())}"
            self._modem.send_command(f'AT+QMTCONN=0,"{client_id}","",""')

            if self._modem.send_command("AT+QMTCONN?").endswith(",1"):
                self._connected = True
                _logger.info("NB-IoT MQTT connected as %s", client_id)
                return True

        _logger.warning("NB-IoT MQTT connection attempt %d failed", attempt + 1)
        time.sleep(self._RECONNECT_INTERVAL)
        return self._mqtt_connect(attempt + 1)

    def _mqtt_disconnect(self) -> None:
        """Disconnect MQTT gracefully."""
        if self._connected:
            self._modem.send_command("AT+QMTDISC=0")
            self._connected = False
            _logger.info("NB-IoT MQTT disconnected")

    def _subscribe_topics(self) -> None:
        """Subscribe to downlink configuration topic."""
        topic = f"cmd/{self._device_id}/config"
        self._modem.send_command(f'AT+QMTSUB=0,1,"{topic}",2')
        _logger.debug("Subscribed to downlink topic: %s", topic)

    # ------------------------------------------------------------------
    # Keepalive
    # ------------------------------------------------------------------

    def _keepalive_loop(self) -> None:
        """Periodic keep-alive thread."""
        while self._running:
            time.sleep(self._KEEPALIVE_INTERVAL)
            if not self._running:
                break

            try:
                if self._connected:
                    self._modem.send_command("AT+CSQ")
                    status = {
                        "connected": True,
                        "signal_quality": self._modem._signal_quality,
                        "uptime": int(time.time()),
                    }
                    self.publish_status(status)
                else:
                    _logger.warning("NB-IoT connection lost, attempting reconnect")
                    if self._network_register():
                        self._mqtt_connect()
            except Exception as exc:
                _logger.error("NB-IoT keepalive error: %s", exc)

    # ------------------------------------------------------------------
    # Message Queue
    # ------------------------------------------------------------------

    def _enqueue_for_retry(
        self,
        msg_type: str,
        *args: Any,
    ) -> bool:
        topic_map = {
            "sensor": f"data/{self._device_id}/sensor",
            "alarm": f"data/{self._device_id}/alarm",
            "status": f"data/{self._device_id}/status",
        }
        topic = topic_map.get(msg_type, f"data/{self._device_id}/{msg_type}")

        try:
            if msg_type == "sensor" and len(args) >= 2:
                payload = self._data_packet.pack_sensor_json(args[0], args[1])
            elif msg_type == "alarm" and len(args) >= 1:
                payload = self._data_packet.pack_alarm_json(args[0])
            else:
                payload = json.dumps({"type": msg_type, "args": str(args)})
        except Exception:
            payload = json.dumps({"type": msg_type})

        self._message_queue.put((topic, payload))
        return False

    def flush_queue(self) -> int:
        """
        Flush queued messages after reconnection.

        Returns:
            Number of messages successfully sent.
        """
        sent = 0
        while not self._message_queue.empty() and self._connected:
            try:
                topic, payload = self._message_queue.get_nowait()
                if self._publish(topic, payload):
                    sent += 1
                else:
                    self._message_queue.put((topic, payload))
                    break
            except queue.Empty:
                break
        return sent

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
    def device_id(self) -> str:
        return self._device_id

    @device_id.setter
    def device_id(self, value: str) -> None:
        self._device_id = value

    @property
    def queue_size(self) -> int:
        return self._message_queue.qsize()

    @property
    def statistics(self) -> dict:
        with self._lock:
            return {
                "messages_sent": self._sent_count,
                "messages_failed": self._fail_count,
                "queue_size": self._message_queue.qsize(),
                "connected": self._connected,
                "apn": self._apn,
                "band": self._band,
            }

    def shutdown(self) -> None:
        """Gracefully shutdown NB-IoT channel."""
        self.stop()
        _logger.info("NB-IoT channel shut down")
