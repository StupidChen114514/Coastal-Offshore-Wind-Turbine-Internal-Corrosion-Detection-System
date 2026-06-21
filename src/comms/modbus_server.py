"""
Modbus TCP server for local SCADA / PLC integration.

Implements a Modbus TCP server (default port 502) with the following
register map per spec.md Requirement 8:

Holding Registers (Func 03 Read, 06/16 Write):
    40001: Temperature T (×10, 16-bit signed int)
    40002: Humidity RH (×10, 16-bit unsigned int)
    40003: Δd (×1000, μm, 16-bit unsigned int)
    40004: CR (×1000, μm/year, 16-bit unsigned int)
    40005: η (×100, 16-bit unsigned int)
    40006: Status word (bit flags)

Input Registers (Func 04 Read):
    30001-30004: Sensor raw values
    30005-30008: Diagnostic information

Coils (Func 01/02 Read, 05 Write):
    00001-00008: Alarm flag bits
    00009-00016: Remote control command acknowledgment

Supported Function Codes:
    01 – Read Coils
    02 – Read Discrete Inputs
    03 – Read Holding Registers
    04 – Read Input Registers
    05 – Write Single Coil
    06 – Write Single Register
    16 – Write Multiple Registers
"""

import socket
import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core.logger import CorrosionLogger

_logger = CorrosionLogger().get_logger("ModbusServer")

_MAX_CONNECTIONS = 4
_RESPONSE_TIMEOUT = 0.5


class ModbusRegisterMap:
    """
    Modbus register data store with bounds checking and scaling.

    Register Address Ranges:
        Coils:              00001 – 09999
        Discrete Inputs:    10001 – 19999
        Input Registers:    30001 – 39999
        Holding Registers:  40001 – 49999
    """

    _HOLDING_BASE = 40001
    _INPUT_BASE = 30001
    _COIL_BASE = 1
    _DISCRETE_BASE = 10001

    _HOLDING_COUNT = 64
    _INPUT_COUNT = 32
    _COIL_COUNT = 32
    _DISCRETE_COUNT = 32

    def __init__(self) -> None:
        self._holding_registers = [0] * self._HOLDING_COUNT
        self._input_registers = [0] * self._INPUT_COUNT
        self._coils = [False] * self._COIL_COUNT
        self._discrete_inputs = [False] * self._DISCRETE_COUNT
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Holding Registers (40001+)
    # ------------------------------------------------------------------

    def update_process_data(
        self,
        temperature: float = 0.0,
        humidity: float = 0.0,
        delta_d: float = 0.0,
        cr_out: float = 0.0,
        eta: float = 0.0,
        status_word: int = 0,
    ) -> None:
        """Update the process data registers with current values."""
        with self._lock:
            self._holding_registers[0] = self._clamp_int16(int(temperature * 10))
            self._holding_registers[1] = self._clamp_uint16(int(humidity * 10))
            self._holding_registers[2] = self._clamp_uint16(int(delta_d * 1000))
            self._holding_registers[3] = self._clamp_uint16(int(cr_out * 1000))
            self._holding_registers[4] = self._clamp_uint16(int(eta * 100))
            self._holding_registers[5] = self._clamp_uint16(status_word)

    def update_status_word(self, status_word: int) -> None:
        """Update only the status word register (40006)."""
        with self._lock:
            self._holding_registers[5] = self._clamp_uint16(status_word)

    def get_holding_register(self, offset: int) -> int:
        """Read a single holding register by offset (0-based)."""
        if 0 <= offset < self._HOLDING_COUNT:
            return self._holding_registers[offset]
        return 0

    def set_holding_register(self, offset: int, value: int) -> bool:
        """Write a single holding register."""
        if 0 <= offset < self._HOLDING_COUNT:
            self._holding_registers[offset] = self._clamp_uint16(value)
            return True
        return False

    def get_holding_registers(self, offset: int, count: int) -> List[int]:
        """Read a block of holding registers."""
        end = min(offset + count, self._HOLDING_COUNT)
        if offset >= self._HOLDING_COUNT:
            return []
        return self._holding_registers[offset:end]

    def set_holding_registers(self, offset: int, values: List[int]) -> bool:
        """Write a block of holding registers."""
        end = offset + len(values)
        if 0 <= offset and end <= self._HOLDING_COUNT:
            for i, v in enumerate(values):
                self._holding_registers[offset + i] = self._clamp_uint16(v)
            return True
        return False

    # ------------------------------------------------------------------
    # Input Registers (30001+)
    # ------------------------------------------------------------------

    def update_input_registers(self, raw_values: List[float]) -> None:
        """Update input registers with raw sensor values."""
        with self._lock:
            for i, val in enumerate(raw_values[:8]):
                self._input_registers[i] = self._clamp_uint16(int(val))

    def update_diagnostics(self, diag_values: List[int]) -> None:
        """Update diagnostic registers (30005-30008)."""
        with self._lock:
            for i, val in enumerate(diag_values[:4]):
                self._input_registers[4 + i] = self._clamp_uint16(val)

    def get_input_register(self, offset: int) -> int:
        """Read a single input register."""
        if 0 <= offset < self._INPUT_COUNT:
            return self._input_registers[offset]
        return 0

    def get_input_registers(self, offset: int, count: int) -> List[int]:
        """Read a block of input registers."""
        end = min(offset + count, self._INPUT_COUNT)
        if offset >= self._INPUT_COUNT:
            return []
        return self._input_registers[offset:end]

    # ------------------------------------------------------------------
    # Coils (00001+)
    # ------------------------------------------------------------------

    def set_alarm_coils(self, alarm_flags: int) -> None:
        """
        Set coils 1-8 based on alarm bitmask.

        Args:
            alarm_flags: 8-bit mask where bit 0 → coil 1, etc.
        """
        with self._lock:
            for i in range(8):
                self._coils[i] = bool(alarm_flags & (1 << i))

    def set_cmd_ack_coils(self, ack_flags: int) -> None:
        """Set coils 9-16 for remote command acknowledgment."""
        with self._lock:
            for i in range(8):
                self._coils[8 + i] = bool(ack_flags & (1 << i))

    def get_coil(self, offset: int) -> bool:
        """Read a single coil."""
        if 0 <= offset < self._COIL_COUNT:
            return self._coils[offset]
        return False

    def set_coil(self, offset: int, value: bool) -> bool:
        """Write a single coil."""
        if 0 <= offset < self._COIL_COUNT:
            self._coils[offset] = value
            return True
        return False

    def get_coils(self, offset: int, count: int) -> List[bool]:
        """Read a block of coils."""
        end = min(offset + count, self._COIL_COUNT)
        if offset >= self._COIL_COUNT:
            return []
        return self._coils[offset:end]

    # ------------------------------------------------------------------
    # Discrete Inputs (10001+)
    # ------------------------------------------------------------------

    def set_discrete_input(self, offset: int, value: bool) -> None:
        """Set a single discrete input."""
        if 0 <= offset < self._DISCRETE_COUNT:
            self._discrete_inputs[offset] = value

    def get_discrete_input(self, offset: int) -> bool:
        """Read a single discrete input."""
        if 0 <= offset < self._DISCRETE_COUNT:
            return self._discrete_inputs[offset]
        return False

    def get_discrete_inputs(self, offset: int, count: int) -> List[bool]:
        """Read a block of discrete inputs."""
        end = min(offset + count, self._DISCRETE_COUNT)
        if offset >= self._DISCRETE_COUNT:
            return []
        return self._discrete_inputs[offset:end]

    # ------------------------------------------------------------------
    # Bulk Snapshot
    # ------------------------------------------------------------------

    def get_all_holding(self) -> List[int]:
        """Return a snapshot of all holding registers."""
        with self._lock:
            return list(self._holding_registers)

    def get_all_input(self) -> List[int]:
        """Return a snapshot of all input registers."""
        with self._lock:
            return list(self._input_registers)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clamp_int16(value: int) -> int:
        return max(-32768, min(32767, value))

    @staticmethod
    def _clamp_uint16(value: int) -> int:
        return max(0, min(65535, value))


class ModbusServer:
    """
    Modbus TCP server for local industrial protocol integration.

    Implements Modbus TCP/IP frame format:
        [Transaction ID:2B][Protocol ID:2B][Length:2B][Unit ID:1B][Func:1B][Data:nB]
    """

    _MBAP_HEADER_FMT = ">HHHBB"
    _MBAP_HEADER_SIZE = 7

    _FUNC_READ_COILS = 0x01
    _FUNC_READ_DISCRETE = 0x02
    _FUNC_READ_HOLDING = 0x03
    _FUNC_READ_INPUT = 0x04
    _FUNC_WRITE_SINGLE_COIL = 0x05
    _FUNC_WRITE_SINGLE_REG = 0x06
    _FUNC_WRITE_MULTIPLE_REGS = 0x10

    _EXCEPTION_ILLEGAL_FUNC = 0x01
    _EXCEPTION_ILLEGAL_ADDR = 0x02
    _EXCEPTION_ILLEGAL_DATA = 0x03

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 502,
    ) -> None:
        self._host = host
        self._port = port
        self._registers = ModbusRegisterMap()
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._initialized = False
        self._lock = threading.Lock()
        self._client_threads: List[threading.Thread] = []
        self._session_counter: int = 0

        self._on_coil_write: Optional[Callable[[int, bool], None]] = None
        self._on_register_write: Optional[Callable[[int, int], None]] = None

        self._connection_count: int = 0
        self._total_requests: int = 0

    def initialize(self) -> bool:
        """Create the listening socket."""
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.settimeout(1.0)
            self._initialized = True
            _logger.info("Modbus server socket created for %s:%d", self._host, self._port)
            return True
        except OSError as exc:
            _logger.error("Modbus server socket creation failed: %s", exc)
            return False

    def start(self) -> None:
        """Start the Modbus TCP server and begin accepting connections."""
        if not self._initialized or self._socket is None:
            _logger.error("Modbus server not initialised")
            return

        try:
            self._socket.bind((self._host, self._port))
            self._socket.listen(_MAX_CONNECTIONS)
            self._running = True

            accept_thread = threading.Thread(
                target=self._accept_loop,
                daemon=True,
                name="modbus-accept",
            )
            accept_thread.start()

            _logger.info("Modbus TCP server started on %s:%d", self._host, self._port)
        except OSError as exc:
            _logger.error("Modbus server bind failed: %s", exc)

    def stop(self) -> None:
        """Stop the Modbus server gracefully."""
        self._running = False
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        _logger.info("Modbus TCP server stopped")

    # ------------------------------------------------------------------
    # Register Access
    # ------------------------------------------------------------------

    @property
    def registers(self) -> ModbusRegisterMap:
        return self._registers

    def update_process_data(
        self,
        temperature: float = 0.0,
        humidity: float = 0.0,
        delta_d: float = 0.0,
        cr_out: float = 0.0,
        eta: float = 0.0,
        status_word: int = 0,
    ) -> None:
        """Update holding registers with latest process data."""
        self._registers.update_process_data(
            temperature, humidity, delta_d, cr_out, eta, status_word
        )

    def update_raw_sensors(self, raw_values: List[float]) -> None:
        """Update input registers with raw sensor values."""
        self._registers.update_input_registers(raw_values)

    def update_diagnostics(self, diag_values: List[int]) -> None:
        """Update diagnostic input registers."""
        self._registers.update_diagnostics(diag_values)

    def set_alarm_flags(self, alarm_bitmask: int) -> None:
        """Map alarm bitmask to coils 1-8."""
        self._registers.set_alarm_coils(alarm_bitmask)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def set_on_coil_write(self, callback: Callable[[int, bool], None]) -> None:
        """Callback for when a coil is written by a remote client."""
        self._on_coil_write = callback

    def set_on_register_write(self, callback: Callable[[int, int], None]) -> None:
        """Callback for when a holding register is written."""
        self._on_register_write = callback

    # ------------------------------------------------------------------
    # Connection Handling
    # ------------------------------------------------------------------

    def _accept_loop(self) -> None:
        """Accept incoming connections and spawn handler threads."""
        while self._running:
            try:
                if self._socket is None:
                    break
                client_sock, addr = self._socket.accept()
                client_sock.settimeout(_RESPONSE_TIMEOUT)

                if self._connection_count >= _MAX_CONNECTIONS:
                    client_sock.close()
                    _logger.warning("Max connections reached, rejected %s", addr)
                    continue

                self._connection_count += 1
                self._session_counter += 1

                thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, addr, self._session_counter),
                    daemon=True,
                    name=f"modbus-client-{self._session_counter}",
                )
                thread.start()
                self._client_threads.append(thread)

            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    _logger.debug("Modbus accept loop interrupted")
                break

    def _handle_client(
        self,
        client_sock: socket.socket,
        addr: Tuple[str, int],
        session_id: int,
    ) -> None:
        """Handle a single Modbus client connection."""
        _logger.debug("Modbus client connected: %s:%d (session %d)", addr[0], addr[1], session_id)

        try:
            while self._running:
                try:
                    header_data = self._recv_exactly(client_sock, self._MBAP_HEADER_SIZE)
                    if header_data is None:
                        break

                    trans_id, proto_id, length, unit_id = struct.unpack(
                        ">HHHB", header_data
                    )

                    remaining = length - 1
                    if remaining < 1:
                        break

                    pdu_data = self._recv_exactly(client_sock, remaining)
                    if pdu_data is None:
                        break

                    response = self._process_pdu(pdu_data, unit_id)
                    if response is not None:
                        resp_len = len(response) + 1
                        mbap = struct.pack(
                            ">HHHB",
                            trans_id,
                            0x0000,
                            resp_len,
                            unit_id,
                        )
                        self._send_all(client_sock, mbap + response)

                    self._total_requests += 1

                except socket.timeout:
                    continue
                except OSError:
                    break

        finally:
            try:
                client_sock.close()
            except OSError:
                pass
            self._connection_count -= 1
            _logger.debug("Modbus client disconnected: %s:%d", addr[0], addr[1])

    # ------------------------------------------------------------------
    # PDU Processing
    # ------------------------------------------------------------------

    def _process_pdu(self, pdu: bytes, unit_id: int) -> Optional[bytes]:
        """Route PDU to the appropriate function handler."""
        if len(pdu) < 1:
            return None

        func_code = pdu[0]
        data = pdu[1:]

        try:
            if func_code == self._FUNC_READ_COILS:
                return self._handle_read_coils(data)
            elif func_code == self._FUNC_READ_DISCRETE:
                return self._handle_read_discrete_inputs(data)
            elif func_code == self._FUNC_READ_HOLDING:
                return self._handle_read_holding(data)
            elif func_code == self._FUNC_READ_INPUT:
                return self._handle_read_input(data)
            elif func_code == self._FUNC_WRITE_SINGLE_COIL:
                return self._handle_write_single_coil(data)
            elif func_code == self._FUNC_WRITE_SINGLE_REG:
                return self._handle_write_single_register(data)
            elif func_code == self._FUNC_WRITE_MULTIPLE_REGS:
                return self._handle_write_multiple_registers(data)
            else:
                return self._exception(func_code, self._EXCEPTION_ILLEGAL_FUNC)
        except Exception as exc:
            _logger.error("Modbus PDU processing error: %s", exc)
            return self._exception(func_code, self._EXCEPTION_ILLEGAL_DATA)

    def _handle_read_coils(self, data: bytes) -> bytes:
        if len(data) < 4:
            return self._exception(self._FUNC_READ_COILS, self._EXCEPTION_ILLEGAL_DATA)

        start_addr, quantity = struct.unpack(">HH", data[:4])
        start_offset = start_addr - self._registers._COIL_BASE

        if quantity < 1 or quantity > 2000:
            return self._exception(self._FUNC_READ_COILS, self._EXCEPTION_ILLEGAL_DATA)

        coils = self._registers.get_coils(start_offset, quantity)
        byte_count = (len(coils) + 7) // 8

        result = bytearray([byte_count])
        for i in range(byte_count):
            b = 0
            for j in range(8):
                idx = i * 8 + j
                if idx < len(coils) and coils[idx]:
                    b |= 1 << j
            result.append(b)

        return bytes([self._FUNC_READ_COILS]) + bytes(result)

    def _handle_read_discrete_inputs(self, data: bytes) -> bytes:
        if len(data) < 4:
            return self._exception(self._FUNC_READ_DISCRETE, self._EXCEPTION_ILLEGAL_DATA)

        start_addr, quantity = struct.unpack(">HH", data[:4])
        start_offset = start_addr - self._registers._DISCRETE_BASE

        if quantity < 1 or quantity > 2000:
            return self._exception(self._FUNC_READ_DISCRETE, self._EXCEPTION_ILLEGAL_DATA)

        inputs = self._registers.get_discrete_inputs(start_offset, quantity)
        byte_count = (len(inputs) + 7) // 8

        result = bytearray([byte_count])
        for i in range(byte_count):
            b = 0
            for j in range(8):
                idx = i * 8 + j
                if idx < len(inputs) and inputs[idx]:
                    b |= 1 << j
            result.append(b)

        return bytes([self._FUNC_READ_DISCRETE]) + bytes(result)

    def _handle_read_holding(self, data: bytes) -> bytes:
        if len(data) < 4:
            return self._exception(self._FUNC_READ_HOLDING, self._EXCEPTION_ILLEGAL_DATA)

        start_addr, quantity = struct.unpack(">HH", data[:4])
        start_offset = start_addr - self._registers._HOLDING_BASE

        if quantity < 1 or quantity > 125:
            return self._exception(self._FUNC_READ_HOLDING, self._EXCEPTION_ILLEGAL_DATA)

        regs = self._registers.get_holding_registers(start_offset, quantity)
        byte_count = len(regs) * 2

        result = bytearray([self._FUNC_READ_HOLDING, byte_count])
        for r in regs:
            result.extend(struct.pack(">H", r))

        return bytes(result)

    def _handle_read_input(self, data: bytes) -> bytes:
        if len(data) < 4:
            return self._exception(self._FUNC_READ_INPUT, self._EXCEPTION_ILLEGAL_DATA)

        start_addr, quantity = struct.unpack(">HH", data[:4])
        start_offset = start_addr - self._registers._INPUT_BASE

        if quantity < 1 or quantity > 125:
            return self._exception(self._FUNC_READ_INPUT, self._EXCEPTION_ILLEGAL_DATA)

        regs = self._registers.get_input_registers(start_offset, quantity)
        byte_count = len(regs) * 2

        result = bytearray([self._FUNC_READ_INPUT, byte_count])
        for r in regs:
            result.extend(struct.pack(">H", r))

        return bytes(result)

    def _handle_write_single_coil(self, data: bytes) -> bytes:
        if len(data) < 4:
            return self._exception(self._FUNC_WRITE_SINGLE_COIL, self._EXCEPTION_ILLEGAL_DATA)

        addr, value = struct.unpack(">HH", data[:4])
        offset = addr - self._registers._COIL_BASE
        coil_value = value == 0xFF00

        if not self._registers.set_coil(offset, coil_value):
            return self._exception(self._FUNC_WRITE_SINGLE_COIL, self._EXCEPTION_ILLEGAL_ADDR)

        _logger.debug("Coil %d set to %s", addr, coil_value)
        if self._on_coil_write:
            try:
                self._on_coil_write(addr, coil_value)
            except Exception:
                pass

        return bytes([self._FUNC_WRITE_SINGLE_COIL]) + data[:4]

    def _handle_write_single_register(self, data: bytes) -> bytes:
        if len(data) < 4:
            return self._exception(self._FUNC_WRITE_SINGLE_REG, self._EXCEPTION_ILLEGAL_DATA)

        addr, value = struct.unpack(">HH", data[:4])
        offset = addr - self._registers._HOLDING_BASE

        if not self._registers.set_holding_register(offset, value):
            return self._exception(self._FUNC_WRITE_SINGLE_REG, self._EXCEPTION_ILLEGAL_ADDR)

        _logger.debug("Register %d written: %d", addr, value)
        if self._on_register_write:
            try:
                self._on_register_write(addr, value)
            except Exception:
                pass

        return bytes([self._FUNC_WRITE_SINGLE_REG]) + data[:4]

    def _handle_write_multiple_registers(self, data: bytes) -> bytes:
        if len(data) < 5:
            return self._exception(self._FUNC_WRITE_MULTIPLE_REGS, self._EXCEPTION_ILLEGAL_DATA)

        start_addr, quantity, byte_count = struct.unpack(">HHB", data[:5])

        if quantity < 1 or quantity > 123 or byte_count != quantity * 2:
            return self._exception(self._FUNC_WRITE_MULTIPLE_REGS, self._EXCEPTION_ILLEGAL_DATA)

        if len(data) < 5 + byte_count:
            return self._exception(self._FUNC_WRITE_MULTIPLE_REGS, self._EXCEPTION_ILLEGAL_DATA)

        values_data = data[5 : 5 + byte_count]
        values = []
        for i in range(quantity):
            val = struct.unpack(">H", values_data[i * 2 : (i + 1) * 2])[0]
            values.append(val)

        offset = start_addr - self._registers._HOLDING_BASE
        if not self._registers.set_holding_registers(offset, values):
            return self._exception(self._FUNC_WRITE_MULTIPLE_REGS, self._EXCEPTION_ILLEGAL_ADDR)

        _logger.debug("Registers %d-%d written (%d values)", start_addr, start_addr + quantity - 1, quantity)

        return struct.pack(">BHH", self._FUNC_WRITE_MULTIPLE_REGS, start_addr, quantity)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _exception(func_code: int, exception_code: int) -> bytes:
        return bytes([func_code | 0x80, exception_code])

    @staticmethod
    def _recv_exactly(sock: socket.socket, num_bytes: int) -> Optional[bytes]:
        data = bytearray()
        while len(data) < num_bytes:
            try:
                chunk = sock.recv(num_bytes - len(data))
                if not chunk:
                    return None
                data.extend(chunk)
            except socket.timeout:
                return None
            except OSError:
                return None
        return bytes(data)

    @staticmethod
    def _send_all(sock: socket.socket, data: bytes) -> None:
        total = 0
        while total < len(data):
            try:
                sent = sock.send(data[total:])
                if sent == 0:
                    raise OSError("Socket send returned 0")
                total += sent
            except OSError:
                raise

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def connection_count(self) -> int:
        return self._connection_count

    @property
    def statistics(self) -> dict:
        return {
            "running": self._running,
            "port": self._port,
            "connections": self._connection_count,
            "total_requests": self._total_requests,
            "max_connections": _MAX_CONNECTIONS,
        }

    def shutdown(self) -> None:
        """Gracefully shutdown the Modbus server."""
        self.stop()
        _logger.info("Modbus server shut down")
