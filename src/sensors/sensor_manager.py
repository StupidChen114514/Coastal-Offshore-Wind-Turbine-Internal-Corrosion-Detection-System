"""
Sensor Manager - Main sensor data acquisition module.

Manages communication with the MSP430FR series MCU via UART/RS-485 serial
bus. The MCU handles low-level I2C/SPI sensor communication and ADC reading,
then sends structured binary data packets to this module over serial.

Supports both real hardware (serial) and simulated (offline) operation modes.

Binary Protocol (from MCU to host):
    Packet structure:
        [0xAA][0x55][PKT_TYPE:1][PKT_LEN:2][PAYLOAD:N][CRC16:2][0x55][0xAA]

    PKT_TYPE = 0x01: Full sensor data packet
        PAYLOAD layout:
            [T_int16:2][RH_uint16:2][V_mid_uint16:2][V_diff_int16:2]
            [L_raw_uint32:4][delta_f_int32:4][flags_uint8:1]

    PKT_TYPE = 0x02: Status/heartbeat packet
        PAYLOAD layout:
            [MCU_temp:2][V_supply:2][uptime:4][error_flags:1]

    PKT_TYPE = 0x03: Acknowledge packet

All multi-byte fields are big-endian (MSB first).
CRC-16 uses polynomial 0x8005 (CRC-16-IBM).
"""

import struct
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from ..core.data_models import SensorData
from ..core.logger import CorrosionLogger

from .pt1000_driver import Pt1000Driver
from .sht35_driver import SHT35Driver
from .qcm_driver import QCMDriver
from .er_probe_driver import ERProbeDriver
from .inductive_driver import InductiveDriver

logger = CorrosionLogger().get_logger(__name__)


class SensorManager:
    """Sensor data acquisition manager for the corrosion detection system.

    Manages serial communication with the MSP430FR MCU, parses binary data
    packets, and produces unified SensorData objects. Supports a simulated
    mode for testing without hardware.

    Attributes:
        serial_config: Serial port configuration dictionary.
        _serial: pyserial Serial instance (hardware mode only).
        _simulated: Whether running in simulation mode.
        _lock: Thread safety lock.
        _initialized: Initialization status.
        _data_callback: Optional callback for incoming data.
        _stats: Runtime statistics dictionary.
        _V_ref_history: Sliding window of V_ref for current source stability.
    """

    PACKET_HEADER: bytes = b'\xAA\x55'
    PACKET_FOOTER: bytes = b'\x55\xAA'

    PKT_TYPE_SENSOR_DATA: int = 0x01
    PKT_TYPE_HEARTBEAT: int = 0x02
    PKT_TYPE_ACK: int = 0x03

    FULL_SENSOR_PAYLOAD_FORMAT: str = '>hHHhiihB'
    FULL_SENSOR_PAYLOAD_SIZE: int = struct.calcsize(FULL_SENSOR_PAYLOAD_FORMAT)

    DEFAULT_SERIAL_CONFIG: Dict = {
        "port": "COM3",
        "baudrate": 115200,
        "timeout": 1.0,
    }

    DEFAULT_CONFIG: Dict = {
        "d0_m": 100.0e-6,
        "electrode_area_m2": 1.0e-4,
        "f0_Hz": 10.0e6,
        "RH_crit": 76.0,
        "epsilon_noise_um": 0.2,
        "calibration_factor_um_per_H": 1.0e6,
    }

    _CRC16_TABLE: Optional[List[int]] = None

    def __init__(
        self,
        serial_config: Optional[Dict] = None,
        simulated: bool = False,
    ) -> None:
        """Initialize the SensorManager.

        Args:
            serial_config: Serial port configuration. Uses defaults if None.
            simulated: If True, operate in simulation mode (no hardware).
        """
        self.serial_config = {**self.DEFAULT_SERIAL_CONFIG}
        if serial_config:
            self.serial_config.update(serial_config)

        self._simulated = simulated
        self._serial = None
        self._lock = threading.Lock()
        self._initialized = False
        self._running = False
        self._data_callback: Optional[Callable[[SensorData], None]] = None
        self._read_thread: Optional[threading.Thread] = None
        self._rx_buffer = bytearray()

        self._config = dict(self.DEFAULT_CONFIG)

        self._stats: Dict[str, int] = {
            "packets_received": 0,
            "packets_parse_errors": 0,
            "packets_crc_errors": 0,
            "read_errors": 0,
        }

        self._V_ref_history: List[float] = []
        self._last_sensor_data: Optional[SensorData] = None

        self._pt1000 = Pt1000Driver()
        self._sht35 = SHT35Driver()
        self._qcm = QCMDriver()
        self._er_probe = ERProbeDriver()
        self._inductive = InductiveDriver()

    def initialize(self, config: Optional[Dict] = None) -> bool:
        """Initialize the sensor subsystem.

        Opens the serial port (hardware mode) and prepares data structures.

        Args:
            config: Optional configuration overrides.

        Returns:
            True if initialization succeeded.
        """
        if self._initialized:
            logger.warning("SensorManager already initialized")
            return True

        if config:
            self._config.update(config)

        try:
            if not self._simulated:
                self._open_serial()
            self._initialized = True
            logger.info(
                "SensorManager initialized in %s mode (port=%s, baud=%d)",
                "SIMULATED" if self._simulated else "HARDWARE",
                self.serial_config.get("port", "N/A"),
                self.serial_config.get("baudrate", 115200),
            )
            return True
        except Exception as e:
            logger.error("SensorManager initialization failed: %s", e)
            return False

    def _open_serial(self) -> None:
        """Open the serial port connection to the MCU."""
        try:
            import serial as pyserial_mod

            self._serial = pyserial_mod.Serial(
                port=self.serial_config["port"],
                baudrate=self.serial_config["baudrate"],
                timeout=self.serial_config.get("timeout", 1.0),
            )
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
            logger.info(
                "Serial port %s opened at %d baud",
                self.serial_config["port"],
                self.serial_config["baudrate"],
            )
        except ImportError:
            logger.error("pyserial module not installed; falling back to simulated mode")
            self._simulated = True
        except Exception as e:
            logger.error("Failed to open serial port: %s", e)
            raise

    def set_data_callback(
        self, callback: Callable[[SensorData], None]
    ) -> None:
        """Register a callback to be invoked when new sensor data arrives.

        Args:
            callback: Callable that receives a SensorData object.
        """
        self._data_callback = callback
        logger.debug("SensorManager data callback registered")

    def start(self) -> None:
        """Start continuous data acquisition in a background thread."""
        if not self._initialized:
            raise RuntimeError("SensorManager must be initialized before starting")

        if self._running:
            logger.warning("SensorManager already running")
            return

        self._running = True
        if not self._simulated and self._serial is not None:
            self._read_thread = threading.Thread(
                target=self._read_loop,
                name="SensorManager-Reader",
                daemon=True,
            )
            self._read_thread.start()
            logger.info("SensorManager data acquisition started")
        elif self._simulated:
            logger.info("SensorManager running in simulated mode (no background read)")

    def stop(self) -> None:
        """Stop data acquisition and close resources."""
        self._running = False

        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=2.0)

        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
                logger.info("Serial port closed")
            except Exception as e:
                logger.error("Error closing serial port: %s", e)

        self._initialized = False
        logger.info("SensorManager stopped")

    def read_all(self) -> Optional[SensorData]:
        """Read data from all sensors and return a unified SensorData object.

        In hardware mode, attempts to read a single packet from serial.
        In simulation mode, returns None (use simulator separately).

        Returns:
            SensorData object, or None if no data available.
        """
        if not self._initialized:
            logger.warning("SensorManager not initialized")
            return None

        if self._simulated:
            logger.debug("SensorManager.read_all() in simulated mode returns None")
            return self._last_sensor_data

        try:
            packet = self._read_packet()
            if packet is not None:
                data = self._parse_sensor_packet(packet)
                if data is not None:
                    self._last_sensor_data = data
                    if self._data_callback:
                        try:
                            self._data_callback(data)
                        except Exception as e:
                            logger.error("Data callback error: %s", e)
                    return data
            return None
        except Exception as e:
            logger.error("read_all error: %s", e)
            self._stats["read_errors"] += 1
            return None

    def read_single_shot(self) -> Optional[SensorData]:
        """Perform a single acquisition and return the result.

        This is a synchronous blocking call suitable for use by the
        acquisition scheduler.

        Returns:
            SensorData object, or None on failure.
        """
        return self.read_all()

    def set_simulated_data(self, data: SensorData) -> None:
        """Inject simulated sensor data (for test/simulation scenarios).

        Args:
            data: Simulated SensorData object.
        """
        if not self._simulated:
            logger.warning(
                "set_simulated_data called in hardware mode; data will not be used"
            )
            return

        self._last_sensor_data = data
        self._process_sensor_data(data)
        logger.debug("Simulated sensor data injected: T=%.2f°C, RH=%.1f%%", data.T, data.RH)

    def _process_sensor_data(self, data: SensorData) -> None:
        """Process and validate sensor data after acquisition.

        Args:
            data: SensorData object to process.
        """
        ratio = ERProbeDriver.calculate_ratio_from_voltage(data.V_mid, data.V_diff)

        if not ERProbeDriver.validate_ratio(ratio):
            data.valid_flag = False
            logger.warning("ER probe ratio validation failed: %.4f", ratio)

        self._V_ref_history.append(data.V_mid)
        if len(self._V_ref_history) > 100:
            self._V_ref_history.pop(0)

        if not ERProbeDriver.check_current_source_stability(self._V_ref_history):
            logger.warning("Current source stability check failed")

        is_valid, reason = ERProbeDriver.is_data_valid_in_dry_conditions(
            data.delta_d_ER, data.RH, self._config["RH_crit"], self._config["epsilon_noise_um"]
        )
        if not is_valid:
            data.valid_flag = False
            logger.warning("Humidity gate: %s", reason)

    def _read_loop(self) -> None:
        """Background thread loop for continuous serial reading."""
        logger.debug("Serial read loop started")
        while self._running:
            try:
                if self._serial and self._serial.is_open and self._serial.in_waiting > 0:
                    chunk = self._serial.read(self._serial.in_waiting)
                    self._rx_buffer.extend(chunk)
                    self._extract_packets()
                else:
                    time.sleep(0.01)
            except Exception as e:
                logger.error("Read loop error: %s", e)
                self._stats["read_errors"] += 1
                time.sleep(0.1)
        logger.debug("Serial read loop stopped")

    def _extract_packets(self) -> None:
        """Extract complete packets from the receive buffer."""
        while True:
            header_idx = self._rx_buffer.find(self.PACKET_HEADER)
            if header_idx == -1:
                if len(self._rx_buffer) > 1024:
                    self._rx_buffer.clear()
                break

            if header_idx > 0:
                del self._rx_buffer[:header_idx]

            if len(self._rx_buffer) < 8:
                break

            pkt_type = self._rx_buffer[2]
            pkt_len = (self._rx_buffer[3] << 8) | self._rx_buffer[4]
            total_len = 5 + pkt_len + 4

            if len(self._rx_buffer) < total_len:
                break

            if (
                self._rx_buffer[total_len - 2] == self.PACKET_FOOTER[0]
                and self._rx_buffer[total_len - 1] == self.PACKET_FOOTER[1]
            ):
                packet = bytes(self._rx_buffer[:total_len])
                del self._rx_buffer[:total_len]
                self._handle_packet(packet)
            else:
                del self._rx_buffer[:2]

    def _read_packet(self) -> Optional[bytes]:
        """Read a single complete packet from the serial port (blocking).

        Returns:
            Complete packet bytes, or None if timed out.
        """
        if not self._serial or not self._serial.is_open:
            return None

        try:
            header = self._serial.read_until(self.PACKET_HEADER)
            if len(header) < 2 or header[-2:] != self.PACKET_HEADER:
                return None

            pkt_type = self._serial.read(1)
            if len(pkt_type) < 1:
                return None

            pkt_len_bytes = self._serial.read(2)
            if len(pkt_len_bytes) < 2:
                return None
            pkt_len = struct.unpack('>H', pkt_len_bytes)[0]

            payload = self._serial.read(pkt_len + 2)
            if len(payload) < pkt_len + 2:
                return None

            footer = self._serial.read(2)
            if len(footer) < 2 or footer != self.PACKET_FOOTER:
                return None

            packet = (
                self.PACKET_HEADER
                + pkt_type
                + pkt_len_bytes
                + payload[:pkt_len]
                + payload[pkt_len:pkt_len + 2]
                + footer
            )
            return packet
        except Exception as e:
            logger.error("Packet read error: %s", e)
            self._stats["read_errors"] += 1
            return None

    def _handle_packet(self, packet: bytes) -> None:
        """Handle a received packet based on its type.

        Args:
            packet: Complete binary packet.
        """
        pkt_type = packet[2]

        if pkt_type == self.PKT_TYPE_SENSOR_DATA:
            data = self._parse_sensor_packet(packet)
            if data is not None:
                self._last_sensor_data = data
                self._process_sensor_data(data)
                if self._data_callback:
                    try:
                        self._data_callback(data)
                    except Exception as e:
                        logger.error("Data callback error: %s", e)
        elif pkt_type == self.PKT_TYPE_HEARTBEAT:
            logger.debug("Heartbeat packet received")
        elif pkt_type == self.PKT_TYPE_ACK:
            logger.debug("ACK packet received")
        else:
            logger.warning("Unknown packet type: 0x%02X", pkt_type)

    def _parse_sensor_packet(self, packet: bytes) -> Optional[SensorData]:
        """Parse a full sensor data packet into a SensorData object.

        Full sensor data packet payload format:
            [T_int16:2][RH_uint16:2][V_mid_uint16:2][V_diff_int16:2]
            [L_raw_uint32:4][delta_f_int32:4][flags_uint8:1]

        Args:
            packet: Complete binary packet.

        Returns:
            SensorData object, or None on parse error.
        """
        try:
            pkt_len = (packet[3] << 8) | packet[4]
            payload = packet[5:5 + pkt_len]
            crc_received = struct.unpack('>H', packet[5 + pkt_len:7 + pkt_len])[0]

            if len(payload) != self.FULL_SENSOR_PAYLOAD_SIZE:
                logger.error(
                    "Sensor packet payload size mismatch: expected %d, got %d",
                    self.FULL_SENSOR_PAYLOAD_SIZE,
                    len(payload),
                )
                self._stats["packets_parse_errors"] += 1
                return None

            crc_computed = self._crc16(payload)
            if crc_computed != crc_received:
                logger.error(
                    "Sensor packet CRC mismatch: computed=0x%04X, received=0x%04X",
                    crc_computed,
                    crc_received,
                )
                self._stats["packets_crc_errors"] += 1
                return None

            fields = struct.unpack(self.FULL_SENSOR_PAYLOAD_FORMAT, payload)
            T_raw, RH_raw, V_mid_raw, V_diff_raw, L_raw, delta_f_raw, flags = fields

            T = T_raw / 100.0
            RH = RH_raw / 100.0
            V_mid = V_mid_raw / 1000.0
            V_diff = V_diff_raw / 1000.0

            L_config = self._make_ldc_config()
            L_eq = InductiveDriver.convert_raw_to_inductance(L_raw, L_config)

            delta_f = delta_f_raw / 1000.0

            d0_m = self._config["d0_m"]
            delta_d_ER = ERProbeDriver.calculate_delta_d_raw(V_mid, V_diff, d0_m)

            delta_d_Inductive = self._estimate_inductive_delta_d(L_eq)

            Cl_deposition = self._estimate_cl_deposition(delta_f)
            valid_flag = bool(flags & 0x01)

            data = SensorData(
                timestamp=datetime.now(timezone.utc),
                T=T,
                RH=RH,
                Cl_deposition=Cl_deposition,
                delta_d_ER=delta_d_ER,
                delta_d_Inductive=delta_d_Inductive,
                V_mid=V_mid,
                V_diff=V_diff,
                L_eq=L_eq,
                delta_f=delta_f,
                valid_flag=valid_flag,
            )

            self._stats["packets_received"] += 1
            logger.debug(
                "Sensor data: T=%.2fC, RH=%.2f%%, ER=%.4fum, Ind=%.4fum, valid=%s",
                T, RH, delta_d_ER, delta_d_Inductive, valid_flag,
            )
            return data

        except struct.error as e:
            logger.error("Sensor packet unpack error: %s", e)
            self._stats["packets_parse_errors"] += 1
            return None
        except Exception as e:
            logger.error("Sensor packet parse error: %s", e)
            self._stats["packets_parse_errors"] += 1
            return None

    def _estimate_inductive_delta_d(self, L_eq: float) -> float:
        """Estimate inductive delta_d from current L_eq.

        Uses a stored initial L_eq if available, otherwise returns 0.

        Args:
            L_eq: Current equivalent inductance in H.

        Returns:
            Estimated corrosion depth in µm.
        """
        if not hasattr(self, '_L_eq_initial'):
            self._L_eq_initial = L_eq
            return 0.0

        try:
            return InductiveDriver.calculate_delta_d_inductive(
                L_eq,
                self._L_eq_initial,
                self._config.get("calibration_factor_um_per_H", 1.0e6),
            )
        except Exception:
            return 0.0

    def _estimate_cl_deposition(self, delta_f_Hz: float) -> float:
        """Estimate Cl deposition rate from frequency shift.

        Args:
            delta_f_Hz: Frequency shift in Hz.

        Returns:
            Estimated Cl deposition in mg/(m²·day).
        """
        electrode_area = self._config.get("electrode_area_m2", 1.0e-4)
        try:
            mass = QCMDriver.mass_from_frequency_shift(delta_f_Hz, electrode_area)

            if not hasattr(self, '_qcm_mass_previous'):
                self._qcm_mass_previous = mass
                self._qcm_mass_time = time.time()
                return 0.0

            dt = time.time() - self._qcm_mass_time
            if dt < 1.0:
                return 0.0

            rate = QCMDriver.deposition_rate(
                mass, self._qcm_mass_previous, dt, electrode_area
            )
            self._qcm_mass_previous = mass
            self._qcm_mass_time = time.time()
            return rate
        except Exception:
            return 0.0

    def _make_ldc_config(self):
        """Create an LDC1614Config from current settings."""
        from .inductive_driver import LDC1614Config
        return LDC1614Config()

    @classmethod
    def _crc16(cls, data: bytes) -> int:
        """Compute CRC-16-IBM (polynomial 0x8005) for packet validation.

        Args:
            data: Input bytes.

        Returns:
            16-bit CRC value.
        """
        if cls._CRC16_TABLE is None:
            cls._CRC16_TABLE = cls._build_crc16_table()

        crc = 0x0000
        for byte in data:
            idx = ((crc >> 8) ^ byte) & 0xFF
            crc = ((crc << 8) ^ cls._CRC16_TABLE[idx]) & 0xFFFF
        return crc

    @classmethod
    def _build_crc16_table(cls) -> List[int]:
        """Build CRC-16 lookup table for polynomial 0x8005.

        Returns:
            List of 256 16-bit CRC values.
        """
        table = []
        for i in range(256):
            crc = i << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x8005) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
            table.append(crc)
        return table

    def send_command(self, command_byte: int, payload: bytes = b'') -> bool:
        """Send a command packet to the MCU.

        Args:
            command_byte: Command identifier byte.
            payload: Optional command payload.

        Returns:
            True if send succeeded.
        """
        if self._simulated or self._serial is None:
            logger.debug("Command 0x%02X not sent (simulated mode)", command_byte)
            return True

        try:
            pkt_len = 1 + len(payload)
            pkt_data = struct.pack('>B', command_byte) + payload
            crc = self._crc16(pkt_data)

            packet = (
                self.PACKET_HEADER
                + struct.pack('>BH', self.PKT_TYPE_ACK, pkt_len)
                + pkt_data
                + struct.pack('>H', crc)
                + self.PACKET_FOOTER
            )

            self._serial.write(packet)
            self._serial.flush()
            logger.debug("Command 0x%02X sent (%d bytes)", command_byte, len(packet))
            return True
        except Exception as e:
            logger.error("Failed to send command 0x%02X: %s", command_byte, e)
            return False

    def get_stats(self) -> Dict:
        """Get runtime statistics.

        Returns:
            Dictionary of statistics counters.
        """
        return dict(self._stats)

    def get_last_data(self) -> Optional[SensorData]:
        """Get the most recently acquired SensorData.

        Returns:
            SensorData object, or None if no data has been acquired.
        """
        return self._last_sensor_data

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        for key in self._stats:
            self._stats[key] = 0
        logger.debug("SensorManager stats reset")

    @property
    def is_initialized(self) -> bool:
        """Check if the sensor manager is initialized."""
        return self._initialized

    @property
    def is_running(self) -> bool:
        """Check if continuous acquisition is running."""
        return self._running

    @property
    def is_simulated(self) -> bool:
        """Check if running in simulation mode."""
        return self._simulated
