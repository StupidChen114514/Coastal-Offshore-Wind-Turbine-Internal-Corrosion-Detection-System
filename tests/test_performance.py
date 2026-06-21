"""
性能基准测试 – 沿海海上风电腐蚀检测系统。

验证核心路径满足 spec.md 需求12 的性能指标：
    - 单次采集+计算 < 110ms
    - 卡尔曼滤波更新 < 5ms
    - 1年数据查询 < 2秒
    - 内存使用量在限制内
    - 环形缓冲区持续写入吞吐量
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.data_models import SensorData
from src.sensors.sensor_simulator import SensorSimulator


PERF_ITERATIONS = 100


def _report_stats(name: str, times_ms: list) -> dict:
    """汇总 min/avg/max 并打印报告。"""
    if not times_ms:
        return {"min": 0, "avg": 0, "max": 0}

    avg = sum(times_ms) / len(times_ms)
    stats = {"min": min(times_ms), "avg": avg, "max": max(times_ms)}
    print(
        f"  [{name}] min={stats['min']:.3f}ms, avg={stats['avg']:.3f}ms, "
        f"max={stats['max']:.3f}ms (iter={len(times_ms)})"
    )
    return stats


class TestPerformance:
    """系统性能基准测试。"""

    def test_acquisition_computation_time(
        self, config_manager, algorithm_engine
    ):
        """单次采集+计算周期 < 110ms。"""
        sim = SensorSimulator(seed=42)
        engine = algorithm_engine

        times = []
        for _ in range(PERF_ITERATIONS):
            data = sim.generate_sample()

            start = time.perf_counter()
            engine.process_sensor_data(data)
            elapsed = (time.perf_counter() - start) * 1000

            times.append(elapsed)

        stats = _report_stats("采集+计算", times)
        assert stats["avg"] < 110.0, (
            f"平均 {stats['avg']:.1f}ms 超出 110ms 的性能限制"
        )
        print("  ✓ 单次采集+计算 < 110ms 指标通过")

    def test_kalman_filter_latency(self, config_manager):
        """卡尔曼滤波更新 < 5ms。"""
        from src.algorithms.kalman_filter import KalmanFilter

        kf = KalmanFilter(measurement_noise_var=0.01)
        times = []

        for i in range(PERF_ITERATIONS):
            start = time.perf_counter()
            kf.predict(dt_seconds=600.0, dT_dt=0.01, dRH_dt=0.1)
            kf.update(float(i) * 0.001)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        stats = _report_stats("Kalman滤波", times)
        assert stats["avg"] < 5.0, (
            f"平均 {stats['avg']:.3f}ms 超出 5ms 的性能限制"
        )
        print("  ✓ 卡尔曼滤波更新 < 5ms 指标通过")

    def test_query_performance_1year(self, storage, config_manager):
        """1 年数据范围查询 < 2 秒。"""
        sim = SensorSimulator(seed=1)

        print("  准备测试数据（写入 1000 条传感器记录）...")
        t0 = datetime.now(timezone.utc) - timedelta(days=365)
        for i in range(1000):
            data = sim.generate_sample()
            data.timestamp = t0 + timedelta(hours=i * 8)
            storage.save_sensor_reading(data)

        start = t0
        end = datetime.now(timezone.utc)
        times = []

        for _ in range(10):
            q_start = time.perf_counter()
            result = storage.query_sensor_data(start, end)
            elapsed = (time.perf_counter() - q_start) * 1000
            times.append(elapsed)

        stats = _report_stats("1年数据查询", times)
        assert stats["avg"] < 2000.0, (
            f"平均 {stats['avg']:.1f}ms 超出 2s 的性能限制"
        )
        print(f"  ✓ 1年数据查询 < 2s 指标通过 (返回 {result['total_count']} 条记录)")

    def test_memory_usage_ring_buffer(self, storage, config_manager):
        """环形缓冲区在限制内。"""
        import sys as _sys

        sim = SensorSimulator(seed=3)

        for _ in range(5000):
            data = sim.generate_sample()
            storage.push_raw_sensor_data(data)

        latest = storage.get_latest_raw_data(100)
        assert len(latest) <= 100

        mem_before = _sys.getsizeof(storage._ring_buffer._buffer)
        print(f"  环形缓冲区5000条数据对象大小: {mem_before} bytes")

        assert mem_before < 50_000_000, "环形缓冲区内存使用量异常大"
        print("  ✓ 内存使用量在合理范围内")

    def test_ring_buffer_throughput(self, storage, config_manager):
        """环形缓冲区持续写入吞吐量。"""
        sim = SensorSimulator(seed=5)

        times = []
        for _ in range(PERF_ITERATIONS):
            data = sim.generate_sample()
            start = time.perf_counter()
            storage.push_raw_sensor_data(data)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        stats = _report_stats("环形缓冲区写入", times)
        assert stats["avg"] < 1.0, (
            f"平均 {stats['avg']:.3f}ms ，环形缓冲区写入性能差"
        )
        print("  ✓ 环形缓冲区写入性能良好")

    def test_storage_save_throughput(self, storage, config_manager):
        """SQLite 写入吞吐量。"""
        sim = SensorSimulator(seed=7)

        times = []
        for _ in range(50):
            data = sim.generate_sample()
            start = time.perf_counter()
            storage.save_sensor_reading(data)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        stats = _report_stats("SQLite写入", times)
        print(f"  ✓ SQLite 写入吞吐量: {stats['avg']:.3f}ms/条")

    def test_dual_mode_validator_latency(self, config_manager):
        """双模验证器延迟。"""
        from src.algorithms.dual_mode_validator import DualModeValidator

        validator = DualModeValidator(config_manager)
        t0 = datetime.now(timezone.utc)
        validator.validate(10.0, 10.0, t0, 0.5)

        times = []
        for i in range(PERF_ITERATIONS):
            t = t0 + timedelta(minutes=10 * (i + 1))
            start = time.perf_counter()
            validator.validate(
                10.0 + i * 0.01,
                10.0 + i * 0.008,
                t,
                0.5,
            )
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        stats = _report_stats("双模验证器", times)
        assert stats["avg"] < 5.0, (
            f"平均 {stats['avg']:.3f}ms 超出预期"
        )

    def test_crc16_throughput(self):
        """CRC-16 校验吞吐量。"""
        from src.core.crypto_utils import CryptoUtils

        data = b"x" * 256
        times = []

        for _ in range(PERF_ITERATIONS):
            start = time.perf_counter()
            CryptoUtils.crc16(data)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        stats = _report_stats("CRC-16校验", times)
        assert stats["avg"] < 0.5, "CRC-16 校验性能差"

    def test_json_serialization_throughput(self, config_manager):
        """JSON 序列化吞吐量。"""
        from src.comms.data_packet import DataPacket
        import json

        dp = DataPacket()
        sensor_data = {"T": 25.5, "RH": 82.3, "Cl_deposition": 5.2}
        corrosion_data = {
            "delta_d_ER": 10.123,
            "delta_d_Inductive": 10.456,
            "CR_out": 0.15,
            "eta": 1.0,
            "valid_flag": True,
            "alarm_bitmask": 0,
        }

        times = []
        for _ in range(PERF_ITERATIONS):
            start = time.perf_counter()
            dp.pack_sensor_json(sensor_data, corrosion_data)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        stats = _report_stats("JSON报文生成", times)
        assert stats["avg"] < 2.0, "JSON 报文生成性能差"

    def test_binary_pack_throughput(self, config_manager):
        """二进制组包吞吐量。"""
        from src.comms.data_packet import DataPacket

        dp = DataPacket()
        sensor_data = {"T": 25.5, "RH": 82.3, "Cl_deposition": 5.2}
        corrosion_data = {
            "delta_d_ER": 10.1,
            "delta_d_Inductive": 10.4,
            "CR_out": 0.15,
            "eta": 1.0,
            "valid_flag": True,
            "alarm_status": 0,
            "alarm_bitmask": 0,
        }

        times = []
        for _ in range(PERF_ITERATIONS):
            start = time.perf_counter()
            dp.pack_sensor_data(sensor_data, corrosion_data)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        stats = _report_stats("二进制报文生成", times)
        assert stats["avg"] < 0.5, "二进制报文生成性能差"

    def test_algorithm_engine_cold_start(self, config_manager):
        """算法引擎冷启动延迟。"""
        from src.algorithms.algorithm_engine import AlgorithmEngine

        times = []
        for _ in range(20):
            engine = AlgorithmEngine(config_manager)
            start = time.perf_counter()
            engine.initialize()
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        stats = _report_stats("算法引擎冷启动", times)
        print(f"  ✓ 算法引擎冷启动: {stats['avg']:.3f}ms")

    def test_simulator_generation_throughput(self, config_manager):
        """模拟器数据生成吞吐量。"""
        sim = SensorSimulator(seed=42)

        times = []
        for _ in range(PERF_ITERATIONS):
            start = time.perf_counter()
            sim.generate_sample()
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        stats = _report_stats("模拟器数据生成", times)
        assert stats["avg"] < 2.0, "模拟器数据生成性能差"

    def test_end_to_end_pipeline_latency(self, config_manager):
        """端到端管线延迟：模拟 → 算法 → 序列化"""
        from src.algorithms.algorithm_engine import AlgorithmEngine
        from src.comms.data_packet import DataPacket

        sim = SensorSimulator(seed=42)
        engine = AlgorithmEngine(config_manager)
        engine.initialize()
        dp = DataPacket()

        for i in range(36):
            sd = sim.generate_sample()
            engine.process_sensor_data(sd)

        times = []
        for _ in range(PERF_ITERATIONS):
            sd = sim.generate_sample()

            start = time.perf_counter()
            record = engine.process_sensor_data(sd)
            if record:
                sensor_dict = {"T": sd.T, "RH": sd.RH, "Cl_deposition": sd.Cl_deposition}
                corrosion_dict = record.to_dict()
                dp.pack_sensor_json(sensor_dict, corrosion_dict)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        stats = _report_stats("端到端管线", times)
        assert stats["avg"] < 150.0, (
            f"端到端平均 {stats['avg']:.1f}ms ，性能需优化"
        )
        print("  ✓ 端到端管线性能可接受")


class TestPerformanceSpecLimits:
    """spec.md 明确指标验证。"""

    def test_acquisition_lt_110ms(self, config_manager):
        """需求12：单次采集+计算周期 < 110ms"""
        from src.algorithms.algorithm_engine import AlgorithmEngine

        sim = SensorSimulator(seed=99)
        engine = AlgorithmEngine(config_manager)
        engine.initialize()

        times = []
        for _ in range(50):
            data = sim.generate_sample()
            start = time.perf_counter()
            engine.process_sensor_data(data)
            elapsed_ms = (time.perf_counter() - start) * 1000
            times.append(elapsed_ms)

        avg_ms = sum(times) / len(times)
        max_ms = max(times)

        print(f"  需求12: 单次采集+计算 avg={avg_ms:.2f}ms, max={max_ms:.2f}ms")
        assert max_ms < 110.0, f"最慢 {max_ms:.2f}ms 超过 110ms 限制"

    def test_kalman_lt_5ms(self, config_manager):
        """需求12：卡尔曼滤波延迟 < 5ms"""
        from src.algorithms.kalman_filter import KalmanFilter

        kf = KalmanFilter()
        times = []
        for i in range(200):
            start = time.perf_counter()
            kf.predict(dt_seconds=600.0, dT_dt=0.1, dRH_dt=0.5)
            kf.update(float(i) * 0.001)
            elapsed_ms = (time.perf_counter() - start) * 1000
            times.append(elapsed_ms)

        avg_ms = sum(times) / len(times)
        print(f"  需求12: 卡尔曼滤波 avg={avg_ms:.3f}ms")
        assert avg_ms < 5.0, f"卡尔曼滤波 {avg_ms:.3f}ms 超过 5ms 限制"
