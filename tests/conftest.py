"""
共享测试 fixtures – 沿海海上风电腐蚀检测系统集成测试。

提供 App、SensorSimulator、StorageManager、AlgorithmEngine、
AlarmManager 等核心模块的测试实例，均使用内存模式，不依赖硬件。
"""

import os
import sys
import threading
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generator, List, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.data_models import (
    AlarmLevel,
    AlarmRecord,
    AlarmStatus,
    AlarmType,
    AuditLogEntry,
    CorrosionRecord,
    OperationType,
    SensorData,
)
from src.core.config_manager import ConfigManager
from src.core.alarm_manager import AlarmManager
from src.sensors.sensor_simulator import SensorSimulator
from src.sensors.sensor_manager import SensorManager


# ============================================================================
# 单例重置工具
# ============================================================================


def reset_all_singletons() -> None:
    """重置所有单例，确保测试隔离。"""
    from src.core.config_manager import ConfigManager
    from src.core.alarm_manager import AlarmManager
    from src.core.app import App

    ConfigManager.reset_instance()
    AlarmManager.reset_instance()
    App.reset_instance()


# ============================================================================
# 核心 fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _reset_singletons() -> Generator[None, None, None]:
    """每个测试前后自动重置所有单例。"""
    reset_all_singletons()
    yield
    reset_all_singletons()


@pytest.fixture
def config_manager() -> ConfigManager:
    """ConfigManager 实例，已加载测试配置。"""
    cm = ConfigManager(config_dir="config")
    cm.load()
    return cm


@pytest.fixture
def simulator() -> SensorSimulator:
    """传感器模拟器，种子固定以保证可复现。"""
    return SensorSimulator(
        seed=42,
        baseline_T=25.0,
        baseline_RH=80.0,
        baseline_corrosion_um=0.0,
        corrosion_rate_um_per_day=0.15,
    )


@pytest.fixture
def storage() -> "Generator[Any, None, None]":
    """StorageManager 使用内存 SQLite 数据库。"""
    from src.storage.storage_manager import StorageManager

    sm = StorageManager(db_path=":memory:", ring_buffer_capacity=10000)
    sm.initialize()
    yield sm
    sm.shutdown()


@pytest.fixture
def algorithm_engine(config_manager: ConfigManager):
    """算法引擎，已从配置初始化。"""
    from src.algorithms.algorithm_engine import AlgorithmEngine

    engine = AlgorithmEngine(config_manager)
    engine.initialize()
    return engine


@pytest.fixture
def algorithm_engine_with_noise(config_manager: ConfigManager):
    """算法引擎，包含已标定的噪声参数。"""
    from src.algorithms.algorithm_engine import AlgorithmEngine
    from src.algorithms.algorithm_engine import DEFAULT_ALPHA_RES, DEFAULT_BETA_RES
    from src.sensors.sensor_simulator import SensorSimulator
    from datetime import datetime, timedelta, timezone

    engine = AlgorithmEngine(config_manager)
    engine.initialize()

    sim = SensorSimulator(seed=99)
    samples = []
    t0 = datetime.now(timezone.utc)
    for i in range(144):
        sd = sim.generate_sample()
        sd.timestamp = t0 + timedelta(minutes=10 * i)
        samples.append(sd)

    engine.calibrate_noise_threshold(samples)
    return engine


@pytest.fixture
def alarm_manager(storage) -> AlarmManager:
    """告警管理器，绑定到内存存储。"""
    reset_all_singletons()
    am = AlarmManager(storage_manager=storage)
    return am


@pytest.fixture
def sensor_manager_simulated() -> SensorManager:
    """SensorManager 在模拟模式下运行。"""
    sm = SensorManager(simulated=True)
    sm.initialize()
    return sm


@pytest.fixture
def app() -> "Generator[Any, None, None]":
    """App 实例，最小初始化（无硬件依赖）。"""
    from src.core.app import App

    app = App(config_dir="config")
    ok = app.initialize()
    assert ok, "[TEST] 应用初始化失败"
    yield app
    try:
        app.stop()
    except Exception:
        pass
    App.reset_instance()


# ============================================================================
# 数据 fixtures
# ============================================================================


@pytest.fixture
def sample_sensor_data() -> SensorData:
    """标准测试用 SensorData。"""
    return SensorData(
        timestamp=datetime.now(timezone.utc),
        T=25.0,
        RH=80.0,
        Cl_deposition=5.0,
        delta_d_ER=10.0,
        delta_d_Inductive=10.0,
        V_mid=1.65,
        V_diff=0.01,
        L_eq=0.001,
        delta_f=0.0,
        valid_flag=True,
    )


@pytest.fixture
def sample_corrosion_record() -> CorrosionRecord:
    """标准测试用 CorrosionRecord。"""
    return CorrosionRecord(
        timestamp=datetime.now(timezone.utc),
        delta_d_raw=10.0,
        delta_d_corrected=9.95,
        delta_d_filtered=9.90,
        CR_ER=0.15,
        CR_Inductive=0.152,
        CR_out=0.1508,
        eta=1.0,
        valid_flag=True,
        status="OK",
    )


@pytest.fixture
def sample_alarm_record() -> AlarmRecord:
    """标准测试用 AlarmRecord。"""
    return AlarmRecord(
        level=AlarmLevel.LEVEL_2,
        alarm_type=AlarmType.SENSOR_COMM_FAILURE,
        details={"sensor_id": "pt1000", "error_detail": "通信超时"},
        sensor_id="pt1000",
        status=AlarmStatus.ACTIVE,
    )


@pytest.fixture
def sensor_data_sequence() -> List[SensorData]:
    """生成 50 个连续的传感器数据样本序列。"""
    t0 = datetime.now(timezone.utc)
    samples = []
    for i in range(50):
        samples.append(
            SensorData(
                timestamp=t0 + timedelta(minutes=10 * i),
                T=25.0 + i * 0.02,
                RH=80.0 - i * 0.1,
                Cl_deposition=5.0,
                delta_d_ER=10.0 + i * 0.05,
                delta_d_Inductive=10.0 + i * 0.048,
                V_mid=1.65,
                V_diff=0.01 + i * 0.0001,
                L_eq=0.001,
                delta_f=0.0,
                valid_flag=True,
            )
        )
    return samples
