"""
Sensor data acquisition module.

Provides sensor drivers, the acquisition manager, scheduler,
and simulator for the coastal offshore wind turbine corrosion
detection system.

Sensor Drivers:
    - Pt1000Driver: Temperature sensor (Callendar-Van Dusen equation)
    - SHT35Driver: Humidity/temperature sensor (CRC-8 validation)
    - QCMDriver: Salinity sensor (Sauerbrey equation)
    - ERProbeDriver: Electrical resistance probe (dual-ring differential)
    - InductiveDriver: Inductive probe (LDC1614 eddy current)
    - LDC1614Config: LDC1614 converter configuration

Infrastructure:
    - SensorManager: Serial communication and data acquisition
    - AcquisitionScheduler: Timed acquisition scheduling
    - SensorSimulator: Simulated data generation for testing
"""

from .acquisition_scheduler import (
    AcquisitionScheduler,
    SchedulerState,
    SensorAcquisitionStatus,
)
from .er_probe_driver import ERProbeDriver
from .inductive_driver import InductiveDriver, LDC1614Config
from .pt1000_driver import Pt1000Driver
from .qcm_driver import QCMDriver
from .sensor_manager import SensorManager
from .sensor_simulator import SensorSimulator
from .sht35_driver import SHT35Driver

__all__ = [
    "Pt1000Driver",
    "SHT35Driver",
    "QCMDriver",
    "ERProbeDriver",
    "InductiveDriver",
    "LDC1614Config",
    "SensorManager",
    "AcquisitionScheduler",
    "SchedulerState",
    "SensorAcquisitionStatus",
    "SensorSimulator",
]
