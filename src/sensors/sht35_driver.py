"""
SHT35-DIS-B Humidity and Temperature Sensor Driver.

Implements CRC-8 validation and data parsing for Sensirion SHT35
digital humidity/temperature sensor data received via I2C (through MCU).

SHT35 Data Format (6 bytes from I2C read):
    Byte 0-1: Temperature raw (MSB, LSB)
    Byte 2:   Temperature CRC-8
    Byte 3-4: Humidity raw (MSB, LSB)
    Byte 5:   Humidity CRC-8

CRC-8 Parameters:
    Polynomial: 0x31 (x^8 + x^5 + x^4 + 1)
    Initial value: 0xFF
    No final XOR

Conversion Formulas:
    T[°C] = -45 + 175 * (S_T / (2^16 - 1))
    RH[%] = 100 * (S_RH / (2^16 - 1))

Typical accuracy: ±1.5% RH (20% to 80% RH range), ±0.1°C
"""

from typing import Dict, Optional

from ..core.logger import CorrosionLogger

logger = CorrosionLogger().get_logger(__name__)


class SHT35Driver:
    """SHT35 digital humidity and temperature sensor driver.

    Handles CRC-8 validation and raw data parsing for SHT35 sensor data
    forwarded from the MCU via serial communication.

    Attributes:
        CRC_POLYNOMIAL: CRC-8 polynomial (0x31).
        CRC_INIT: CRC-8 initial value (0xFF).
        I2C_ADDRESS: Default I2C address (0x44).
        ACCURACY_RH: Typical humidity accuracy (±% RH).
        ACCURACY_T: Typical temperature accuracy (±°C).
    """

    CRC_POLYNOMIAL: int = 0x31
    CRC_INIT: int = 0xFF
    I2C_ADDRESS: int = 0x44

    ACCURACY_RH: float = 1.5
    ACCURACY_T: float = 0.1

    @classmethod
    def compute_crc8(cls, data: bytes) -> int:
        """Compute CRC-8 checksum for SHT35 data validation.

        Uses polynomial 0x31 (x^8 + x^5 + x^4 + 1) with initial value 0xFF.

        Args:
            data: Input bytes for CRC calculation.

        Returns:
            8-bit CRC value.
        """
        crc = cls.CRC_INIT
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = ((crc << 1) ^ cls.CRC_POLYNOMIAL) & 0xFF
                else:
                    crc = (crc << 1) & 0xFF
        return crc

    @classmethod
    def validate_crc(cls, data: bytes, crc_byte: int) -> bool:
        """Validate SHT35 data bytes against provided CRC-8.

        Args:
            data: Two data bytes (MSB, LSB) for CRC validation.
            crc_byte: Expected CRC-8 value.

        Returns:
            True if CRC matches, False otherwise.
        """
        computed = cls.compute_crc8(data)
        is_valid = computed == crc_byte
        if not is_valid:
            logger.warning(
                "SHT35 CRC mismatch: computed=0x%02X, expected=0x%02X, data=%s",
                computed,
                crc_byte,
                data.hex(),
            )
        return is_valid

    @classmethod
    def _convert_temperature_raw(cls, raw: int) -> float:
        """Convert raw temperature ADC value to °C.

        Formula: T[°C] = -45 + 175 * (S_T / (2^16 - 1))

        Args:
            raw: Raw 16-bit temperature reading.

        Returns:
            Temperature in °C.
        """
        return -45.0 + 175.0 * (raw / 65535.0)

    @classmethod
    def _convert_humidity_raw(cls, raw: int) -> float:
        """Convert raw humidity ADC value to % RH.

        Formula: RH[%] = 100 * (S_RH / (2^16 - 1))

        Args:
            raw: Raw 16-bit humidity reading.

        Returns:
            Relative humidity in %.
        """
        return 100.0 * (raw / 65535.0)

    @classmethod
    def parse_sht35_data(cls, raw_bytes: bytes) -> Dict[str, float]:
        """Parse a 6-byte SHT35 data packet into temperature and humidity.

        Packet structure:
            Byte 0-1: Temperature raw (MSB first)
            Byte 2:   Temperature CRC-8
            Byte 3-4: Humidity raw (MSB first)
            Byte 5:   Humidity CRC-8

        Args:
            raw_bytes: 6-byte raw SHT35 data packet from I2C read.

        Returns:
            Dictionary with keys 'T' (°C) and 'RH' (%), and '_valid' (bool).

        Raises:
            ValueError: If raw_bytes is not exactly 6 bytes.
        """
        if len(raw_bytes) != 6:
            raise ValueError(
                f"SHT35 data packet must be 6 bytes, got {len(raw_bytes)}"
            )

        temp_raw = (raw_bytes[0] << 8) | raw_bytes[1]
        temp_crc = raw_bytes[2]
        hum_raw = (raw_bytes[3] << 8) | raw_bytes[4]
        hum_crc = raw_bytes[5]

        temp_valid = cls.validate_crc(raw_bytes[:2], temp_crc)
        hum_valid = cls.validate_crc(raw_bytes[3:5], hum_crc)
        all_valid = temp_valid and hum_valid

        T = cls._convert_temperature_raw(temp_raw)
        RH = cls._convert_humidity_raw(hum_raw)

        if not all_valid:
            logger.warning(
                "SHT35 data CRC failure: T_valid=%s, RH_valid=%s, T=%.2f°C, RH=%.2f%%",
                temp_valid,
                hum_valid,
                T,
                RH,
            )

        RH = max(0.0, min(100.0, RH))

        logger.debug(
            "SHT35 parsed: T=%.2f°C (±%.2f°C), RH=%.2f%% (±%.2f%% RH), valid=%s",
            T,
            cls.ACCURACY_T,
            RH,
            cls.ACCURACY_RH,
            all_valid,
        )

        return {"T": T, "RH": RH, "_valid": all_valid}

    @classmethod
    def parse_sht35_from_integers(
        cls, temp_raw: int, hum_raw: int
    ) -> Dict[str, float]:
        """Parse SHT35 data from pre-extracted raw integer values.

        Useful when the MCU has already extracted and CRC-validated the
        raw values before sending.

        Args:
            temp_raw: Raw 16-bit temperature value.
            hum_raw: Raw 16-bit humidity value.

        Returns:
            Dictionary with keys 'T' (°C) and 'RH' (%).
        """
        T = cls._convert_temperature_raw(temp_raw)
        RH = cls._convert_humidity_raw(hum_raw)
        RH = max(0.0, min(100.0, RH))

        logger.debug(
            "SHT35 parsed from integers: T=%.2f°C, RH=%.2f%%",
            T,
            RH,
        )
        return {"T": T, "RH": RH, "_valid": True}

    @classmethod
    def is_above_critical_humidity(
        cls, RH: float, RH_crit: float = 76.0
    ) -> bool:
        """Check if relative humidity exceeds the NaCl deliquescence threshold.

        For NaCl, the critical relative humidity is approximately 75.5% at 20°C.
        When RH > 76%, NaCl particles begin to deliquesce and form an
        electrolyte film, initiating corrosion.

        Args:
            RH: Current relative humidity in %.
            RH_crit: Critical relative humidity threshold (default 76%).

        Returns:
            True if RH is above the critical threshold.
        """
        return RH >= RH_crit
