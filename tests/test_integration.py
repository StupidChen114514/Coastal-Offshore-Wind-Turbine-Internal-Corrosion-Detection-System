"""
端到端集成测试 – 沿海海上风电腐蚀检测系统。

覆盖采集管线、算法流水线、数据持久化、告警系统、安全系统、通信报文。
所有测试不依赖实际硬件，使用内存数据库和模拟器。
"""

import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.data_models import (
    AlarmLevel,
    AlarmRecord,
    AlarmStatus,
    AlarmType,
    AuditLogEntry,
    CorrosionRecord,
    CrossValidationResult,
    DualModeResult,
    DualModeStatus,
    OperationType,
    SensorData,
)
from src.core.data_integrity import DataIntegrityGuard
from src.sensors.sensor_simulator import SensorSimulator
from src.sensors.acquisition_scheduler import AcquisitionScheduler, SchedulerState
from src.sensors.sensor_manager import SensorManager


# ============================================================================
# TestSensorAcquisitionPipeline
# ============================================================================


class TestSensorAcquisitionPipeline:
    """传感器采集管线测试：模拟器 → 数据流。"""

    def test_simulator_produces_valid_data(self, simulator):
        """SensorSimulator 产出有效的 SensorData。"""
        data = simulator.generate_sample()

        assert isinstance(data, SensorData)
        assert isinstance(data.timestamp, datetime)
        assert data.timestamp.tzinfo is not None
        assert 15.0 <= data.T <= 35.0, f"温度 {data.T}°C 超出合理范围 15-35°C"
        assert 55.0 <= data.RH <= 98.0, f"湿度 {data.RH}% 超出合理范围 55-98%"
        assert data.delta_d_ER >= 0, f"ER 腐蚀深度应为非负值，实际: {data.delta_d_ER}"
        assert data.delta_d_Inductive >= 0, f"Inductive 腐蚀深度应为非负值，实际: {data.delta_d_Inductive}"

        d = data.to_dict()
        assert "T" in d
        assert "RH" in d
        assert "delta_d_ER" in d
        assert "delta_d_Inductive" in d
        assert "valid_flag" in d

    def test_simulator_reproducibility(self):
        """相同种子产出相同数据。"""
        sim1 = SensorSimulator(seed=123)
        sim2 = SensorSimulator(seed=123)

        d1 = sim1.generate_sample()
        d2 = sim2.generate_sample()

        assert pytest.approx(d1.T) == d2.T
        assert pytest.approx(d1.RH) == d2.RH
        assert pytest.approx(d1.delta_d_ER) == d2.delta_d_ER
        assert pytest.approx(d1.delta_d_Inductive) == d2.delta_d_Inductive

    def test_simulator_fault_injection(self, simulator):
        """故障注入导致 NaN 值。"""
        simulator.set_fault("pt1000_fault", True)

        data = simulator.generate_sample()
        assert math.isnan(data.T), f"Pt1000 故障应产生 NaN T，实际: {data.T}"
        assert not data.valid_flag, "故障注入后 valid_flag 应为 False"

        simulator.clear_all_faults()
        data2 = simulator.generate_sample()
        assert not math.isnan(data2.T)
        assert data2.valid_flag

    def test_simulator_reset(self, simulator):
        """模拟器重置后 count 归零。"""
        simulator.generate_sample()
        simulator.generate_sample()
        assert simulator.sample_count == 2

        simulator.reset()
        assert simulator.sample_count == 0

    def test_acquisition_scheduler_state_transitions(self, sensor_manager_simulated):
        """调度器状态转换：IDLE → NORMAL → STOPPED。"""
        scheduler = AcquisitionScheduler(
            normal_interval_s=0.1,
            emergency_interval_s=0.05,
            emergency_duration_s=0.5,
        )
        scheduler.set_sensor_manager(sensor_manager_simulated)

        assert scheduler.get_state() == SchedulerState.IDLE

        scheduler.start()
        assert scheduler.get_state() == SchedulerState.NORMAL

        scheduler.stop()
        assert scheduler.get_state() == SchedulerState.STOPPED

    def test_acquisition_scheduler_requires_sensor_manager(self):
        """未绑定 SensorManager 时启动应失败。"""
        scheduler = AcquisitionScheduler()
        with pytest.raises(RuntimeError, match="SensorManager must be bound"):
            scheduler.start()

    def test_acquisition_scheduler_emergency_trigger(self, sensor_manager_simulated):
        """应急模式触发与状态转换。"""
        scheduler = AcquisitionScheduler(
            normal_interval_s=0.3,
            emergency_interval_s=0.05,
            emergency_duration_s=1.0,
        )
        scheduler.set_sensor_manager(sensor_manager_simulated)
        scheduler.start()
        assert scheduler.get_state() == SchedulerState.NORMAL

        scheduler.trigger_emergency("测试触发")
        assert scheduler.get_state() == SchedulerState.EMERGENCY, (
            "应进入应急模式"
        )

        scheduler.stop()
        assert scheduler.get_state() == SchedulerState.STOPPED

    def test_sensor_fault_handling(
        self, simulator, sensor_manager_simulated, algorithm_engine
    ):
        """传感器故障注入 → 数据标记无效 → 算法引擎处理。"""
        simulator.set_fault("all_fault", True)
        data = simulator.generate_sample()
        sensor_manager_simulated.set_simulated_data(data)

        assert not data.valid_flag
        assert math.isnan(data.T)

        engine = algorithm_engine
        record = engine.process_sensor_data(data)

        if record is not None:
            assert record.delta_d_raw >= 0, "故障数据仍应有合理的补偿值"

        simulator.clear_all_faults()
        data2 = simulator.generate_sample()
        assert data2.valid_flag


# ============================================================================
# TestAlgorithmPipeline
# ============================================================================


class TestAlgorithmPipeline:
    """算法处理流水线测试。"""

    def test_full_error_compensation_chain(
        self, algorithm_engine_with_noise, sample_sensor_data
    ):
        """Level 1-4 完整补偿链路处理传感器数据。"""
        engine = algorithm_engine_with_noise

        record = engine.process_sensor_data(sample_sensor_data)
        assert record is not None
        assert isinstance(record, CorrosionRecord)
        assert record.delta_d_raw >= 0
        assert record.delta_d_corrected >= 0

        d = record.to_dict()
        required = [
            "delta_d_raw",
            "delta_d_corrected",
            "delta_d_filtered",
            "CR_ER",
            "CR_out",
            "valid_flag",
        ]
        for key in required:
            assert key in d, f"CorrosionRecord.to_dict() 缺少字段: {key}"

    def test_kalman_filter_warm_up(self, algorithm_engine, sensor_data_sequence):
        """卡尔曼滤波需要 36 个样本才完成预热。"""
        engine = algorithm_engine
        assert not engine.is_kalman_warmed_up()

        for i in range(37):
            engine.process_sensor_data(sensor_data_sequence[i])

        assert engine.is_kalman_warmed_up()

    def test_kalman_filter_convergence(self, algorithm_engine, sensor_data_sequence):
        """卡尔曼滤波对含噪声数据的收敛验证。"""
        engine = algorithm_engine

        for sd in sensor_data_sequence[:10]:
            engine.process_sensor_data(sd)

        for sd in sensor_data_sequence[10:]:
            record = engine.process_sensor_data(sd)
            if record:
                assert record.delta_d_filtered >= 0

        if engine.is_kalman_warmed_up():
            dd, cr = engine.get_kalman_state()
            assert dd > 0, f"Kalman 滤波后 Δd 应 > 0，实际: {dd}"
            assert cr >= 0, f"Kalman 滤波后 CR 应 >= 0，实际: {cr}"

    def test_level1_hardware_diff(self, algorithm_engine):
        """Level 1: 硬件差分补偿计算正确。"""
        engine = algorithm_engine

        delta_d, status = engine._compensate_level1_hardware_diff(
            V_mid=1.65, V_diff=0.01, d0=100.0
        )
        assert delta_d > 0
        assert status == "OK" or "OK" in status

        delta_d2, status2 = engine._compensate_level1_hardware_diff(
            V_mid=0.0, V_diff=0.01, d0=100.0
        )
        assert status2 == "V_mid_zero"

        delta_d3, _ = engine._compensate_level1_hardware_diff(
            V_mid=1.65, V_diff=100.0, d0=100.0
        )
        assert delta_d3 >= 0

    def test_level3a_temperature_correction(self, algorithm_engine):
        """Level 3A: 残余温度多项式修正。"""
        engine = algorithm_engine

        corrected = engine._compensate_level3a_temperature(
            delta_d_raw=10.0,
            T=35.0,
            alpha_res=0.003,
            beta_res=0.0001,
            T0=25.0,
        )
        assert corrected < 10.0, f"高温下应修正为更小值，实际: {corrected}"

        corrected_cold = engine._compensate_level3a_temperature(
            delta_d_raw=10.0,
            T=15.0,
            alpha_res=0.003,
            beta_res=0.0001,
            T0=25.0,
        )
        assert corrected_cold > 10.0

        corrected_skip = engine._compensate_level3a_temperature(
            delta_d_raw=10.0,
            T=35.0,
            alpha_res=0.0,
            beta_res=0.0,
            T0=25.0,
        )
        assert corrected_skip == 10.0

    def test_level3b_humidity_gate(self, algorithm_engine):
        """Level 3B: 湿度门控过滤。"""
        engine = algorithm_engine

        valid, _ = engine._filter_level3b_humidity_gate(
            delta_d_raw=0.5,
            RH=70.0,
            epsilon_noise=0.2,
            consecutive_invalid=0,
        )
        assert not valid, "RH=70% 低于 76% 临界值，有噪声信号时无效"

        valid2, _ = engine._filter_level3b_humidity_gate(
            delta_d_raw=0.1,
            RH=70.0,
            epsilon_noise=0.2,
            consecutive_invalid=0,
        )
        assert valid2, "低于噪声阈值时有效"

        valid3, _ = engine._filter_level3b_humidity_gate(
            delta_d_raw=0.5,
            RH=85.0,
            epsilon_noise=0.2,
            consecutive_invalid=0,
        )
        assert valid3, "RH=85% 高于临界值时有效"

        valid4, status4 = engine._filter_level3b_humidity_gate(
            delta_d_raw=0.5,
            RH=70.0,
            epsilon_noise=0.2,
            consecutive_invalid=9,
        )
        assert not valid4
        assert "anomaly" in status4.lower() or "异常" in status4

    def test_dual_mode_all_scenarios(self):
        """双模交叉验证三种场景全覆盖。"""
        from src.core.config_manager import ConfigManager
        from src.algorithms.dual_mode_validator import DualModeValidator

        ConfigManager.reset_instance()
        config = ConfigManager()
        config.load()

        validator = DualModeValidator(config)
        t0 = datetime.now(timezone.utc)
        t1 = t0 + timedelta(minutes=10)

        validator.validate(10.0, 10.0, t0, 0.5)
        v = validator.validate(10.5, 10.45, t1, 0.3)
        assert v.status == DualModeStatus.DUAL_CONSISTENT
        assert v.diff < 0.15

        validator2 = DualModeValidator(config)
        validator2.validate(10.0, 10.0, t0, 0.5)
        v2 = validator2.validate(15.0, 10.5, t1, 3.5)
        assert v2.status == DualModeStatus.TEMPERATURE_SHOCK
        assert v2.diff >= 0.15

        validator3 = DualModeValidator(config)
        validator3.validate(50.0, 50.0, t0, 0.5)
        v3 = validator3.validate(80.0, 50.2, t1, 1.0)
        assert v3.status == DualModeStatus.PITTING_SUSPECTED
        assert v3.eta > 1.0

        ConfigManager.reset_instance()

    def test_iso_9223_assessment_complete(self):
        """完整 ISO 9223 评估流程。"""
        from src.algorithms.iso_9223 import ISO9223Assessor

        assessor = ISO9223Assessor()
        tow_grade = assessor.classify_tow_grade(3000.0)
        assert tow_grade.label in ("τ1", "τ2", "τ3", "τ4", "τ5")

        category_measured = assessor.classify_corrosivity(30.0)
        assert category_measured.label in ("C1", "C2", "C3", "C4", "C5", "CX")

        summary = assessor.estimate_category_from_environment(tow_grade, assessor.classify_salinity(5.0))
        assert summary.label in ("C1", "C2", "C3", "C4", "C5", "CX")

    def test_iso_9224_prediction(self):
        """ISO 9224 幂函数模型预测。"""
        from src.algorithms.iso_9223 import ISO9223Assessor

        assessor = ISO9223Assessor()
        predictions = assessor.predict_long_term(30.0)

        assert 1 in predictions
        assert 5 in predictions
        assert 10 in predictions
        assert 25 in predictions
        assert predictions[25] > predictions[1]
        assert predictions[25] > predictions[10]

    def test_calibration_curve_interpolation(self):
        """标定曲线插值正确。"""
        from src.core.config_manager import ConfigManager
        from src.algorithms.calibration_curve import CalibrationCurve

        ConfigManager.reset_instance()
        config = ConfigManager()
        config.load()

        curve = CalibrationCurve(config)
        eta_0 = curve.get_eta(0.0)
        eta_05 = curve.get_eta(0.05)
        eta_45 = curve.get_eta(0.45)

        assert eta_0 >= 1.0, f"δ=0 时 η 应 ≥ 1.0，实际: {eta_0}"
        assert eta_45 > eta_05 > eta_0, f"η 应随 δ 单调递增"

        ConfigManager.reset_instance()

    def test_tow_calculator(self):
        """TOW 湿润时间计算。"""
        from src.core.config_manager import ConfigManager
        from src.algorithms.tow_calculator import TOWCalculator

        ConfigManager.reset_instance()
        config = ConfigManager()
        config.load()

        tow = TOWCalculator()
        wet_count = 0
        for _ in range(100):
            if tow.add_hour(25.0, 85.0):
                wet_count += 1

        assert wet_count == 100
        assert tow.get_tow_hours() == 100
        grade = tow.get_tow_grade()
        assert grade in ("τ1", "τ2", "τ3", "τ4", "τ5")

        ConfigManager.reset_instance()

    def test_dose_response_prediction(self):
        """剂量-响应函数预测腐蚀速率。"""
        from src.algorithms.dose_response import predict_corrosion_rate, cross_validate

        r_pred, confidence = predict_corrosion_rate(
            T_avg=25.0, RH_avg=80.0, Cl_avg=5.0
        )
        assert r_pred > 0, f"预测速率应 > 0，实际: {r_pred}"
        assert 0 <= confidence <= 1.0

        ratio, verdict, alarm_level = cross_validate(r_meas=20.0, r_pred=r_pred)
        assert ratio > 0
        assert verdict is not None
        assert isinstance(alarm_level, int)

    def test_cross_validation_engine_end_to_end(self, app):
        """CrossValidationEngine 端到端处理。"""
        from src.algorithms.cross_validation import CrossValidationEngine

        engine = CrossValidationEngine(app)
        ok = engine.initialize()
        assert ok

        sd1 = SensorData(
            timestamp=datetime.now(timezone.utc),
            T=25.0,
            RH=80.0,
            Cl_deposition=5.0,
            delta_d_ER=100.0,
            delta_d_Inductive=100.0,
            V_mid=1.65,
            V_diff=0.01,
            L_eq=0.001,
            delta_f=0.0,
            valid_flag=True,
        )

        result = engine.process_cycle(sd1)
        assert isinstance(result, CrossValidationResult)
        assert hasattr(result, "final_cr")
        assert hasattr(result, "alarms_to_trigger")

        d = result.to_dict()
        assert "final_cr" in d
        assert "timestamp" in d


# ============================================================================
# TestDataPersistence
# ============================================================================


class TestDataPersistence:
    """数据存储与检索测试。"""

    def test_ring_buffer_push_and_retrieve(self, storage, simulator):
        """环形缓冲区写入与读取。"""
        for _ in range(50):
            data = simulator.generate_sample()
            storage.push_raw_sensor_data(data)

        latest = storage.get_latest_raw_data(20)
        assert len(latest) == 20
        assert isinstance(latest[0], SensorData)

    def test_ring_buffer_overflow(self, storage, simulator):
        """环形缓冲区溢出处理正确。"""
        for _ in range(200):
            data = simulator.generate_sample()
            storage.push_raw_sensor_data(data)

        latest = storage.get_latest_raw_data(200)
        assert len(latest) <= 200

    def test_database_save_and_query_sensor(
        self, storage, sample_sensor_data
    ):
        """传感器数据写入与查询。"""
        ok = storage.save_sensor_reading(sample_sensor_data)
        assert ok

        start = sample_sensor_data.timestamp - timedelta(hours=1)
        end = sample_sensor_data.timestamp + timedelta(hours=1)
        result = storage.query_sensor_data(start, end)
        assert result["total_count"] >= 1

    def test_database_save_and_query_corrosion(
        self, storage, sample_corrosion_record
    ):
        """腐蚀记录写入与查询。"""
        ok = storage.save_corrosion_record(sample_corrosion_record)
        assert ok

        start = sample_corrosion_record.timestamp - timedelta(hours=1)
        end = sample_corrosion_record.timestamp + timedelta(hours=1)
        result = storage.query_corrosion_records(start, end)
        assert result["total_count"] >= 1

    def test_database_save_and_query_alarm(
        self, storage, sample_alarm_record
    ):
        """告警记录写入与查询。"""
        ok = storage.save_alarm_record(sample_alarm_record)
        assert ok

        result = storage.query_alarms()
        assert result["total_count"] >= 1

        result_active = storage.query_alarms(status="ACTIVE")
        assert result_active["total_count"] >= 1

    def test_database_save_audit_log(self, storage):
        """审计日志写入与查询。"""
        entry = AuditLogEntry(
            operator="test_user",
            operation_type=OperationType.CONFIG_CHANGE,
            details={"key": "value"},
            result="success",
        )
        ok = storage.save_audit_log(entry)
        assert ok

        result = storage.query_audit_log()
        assert result["total_count"] >= 1

    def test_database_stats(self, storage):
        """数据库统计信息完整。"""
        stats = storage.get_database_stats()
        assert "sensor_readings_count" in stats
        assert "corrosion_records_count" in stats
        assert "alarm_records_count" in stats
        assert isinstance(stats, dict)
        assert len(stats) >= 5

    def test_data_export_csv(self, storage, sample_sensor_data):
        """CSV 导出正确。"""
        storage.save_sensor_reading(sample_sensor_data)

        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8-sig"
        ) as f:
            path = f.name

        try:
            storage.export_csv(
                "sensor",
                sample_sensor_data.timestamp - timedelta(hours=1),
                sample_sensor_data.timestamp + timedelta(hours=1),
                path,
            )
            with open(path, "r", encoding="utf-8-sig") as f:
                content = f.read()
                assert "timestamp" in content
        finally:
            os.unlink(path)

    def test_data_export_json(self, storage, sample_sensor_data):
        """JSON 导出正确。"""
        storage.save_sensor_reading(sample_sensor_data)

        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            path = f.name

        try:
            storage.export_json(
                "sensor",
                sample_sensor_data.timestamp - timedelta(hours=1),
                sample_sensor_data.timestamp + timedelta(hours=1),
                path,
            )
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                assert "metadata" in data
                assert "records" in data
        finally:
            os.unlink(path)

    def test_database_export_csv_corrosion(
        self, storage, sample_corrosion_record
    ):
        """腐蚀记录 CSV 导出。"""
        storage.save_corrosion_record(sample_corrosion_record)

        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8-sig"
        ) as f:
            path = f.name

        try:
            storage.export_csv(
                "corrosion",
                sample_corrosion_record.timestamp - timedelta(hours=1),
                sample_corrosion_record.timestamp + timedelta(hours=1),
                path,
            )
            assert os.path.getsize(path) > 0
        finally:
            os.unlink(path)

    def test_export_invalid_type(self, storage):
        """无效类型导出报错。"""
        with pytest.raises(ValueError, match="Unknown data_type"):
            storage.export_csv(
                "invalid_type",
                datetime.now(timezone.utc),
                datetime.now(timezone.utc),
                "test.csv",
            )

    def test_cloud_sync_queue(self, storage):
        """CloudSyncQueue 队列操作。"""
        sid = storage.enqueue_cloud_sync("sensor_data", {"T": 25.0})
        assert sid > 0

        pending = storage.get_pending_sync_batch(limit=10)
        assert len(pending) >= 1

        ids_to_mark = [p["id"] for p in pending if isinstance(p, dict) and "id" in p]
        if ids_to_mark:
            storage.mark_sync_complete(ids_to_mark)

        status = storage.get_sync_status()
        assert "pending" in status
        assert "sent" in status

    def test_database_backup_unavailable_for_memory_db(self, storage):
        """内存数据库不可备份（是预期行为）。"""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            backup_path = f.name

        try:
            ok = storage.backup_database(backup_path)
            if storage._db_path == ":memory:":
                assert not ok, "内存数据库不应支持备份"
        finally:
            if os.path.exists(backup_path):
                os.unlink(backup_path)


# ============================================================================
# TestAlarmSystem
# ============================================================================


class TestAlarmSystem:
    """告警系统完整生命周期测试。"""

    def test_alarm_lifecycle_full(self, alarm_manager):
        """完整生命周期: raise → acknowledge → resolve。"""
        alarm = alarm_manager.raise_alarm(
            level=2,
            alarm_type="SENSOR_COMM_FAILURE",
            details={"sensor_id": "pt1000", "error_detail": "通信超时"},
            sensor_id="pt1000",
        )
        assert alarm is not None
        assert alarm.level == AlarmLevel.LEVEL_2
        assert alarm.status == AlarmStatus.ACTIVE

        ok = alarm_manager.acknowledge_alarm(str(alarm.alarm_id), "operator1")
        assert ok

        alarm_after = alarm_manager.get_alarm_by_id(str(alarm.alarm_id))
        assert alarm_after.status == AlarmStatus.ACKNOWLEDGED
        assert alarm_after.operator == "operator1"

        ok = alarm_manager.resolve_alarm(str(alarm.alarm_id), "operator1", auto=False)
        assert ok

        alarm_after2 = alarm_manager.get_alarm_by_id(str(alarm.alarm_id))
        assert alarm_after2.status == AlarmStatus.RESOLVED

    def test_alarm_auto_resolve(self, alarm_manager):
        """自动解除告警。"""
        alarm = alarm_manager.raise_alarm(
            level=2,
            alarm_type="SENSOR_COMM_FAILURE",
            details={"sensor_id": "sht35", "error_detail": "通信超时"},
            sensor_id="sht35",
        )
        assert alarm is not None

        ok = alarm_manager.resolve_alarm(str(alarm.alarm_id), auto=True)
        assert ok

        alarm_after = alarm_manager.get_alarm_by_id(str(alarm.alarm_id))
        assert alarm_after.status == AlarmStatus.AUTO_RESOLVED

    def test_alarm_deduplication(self, alarm_manager):
        """重复告警 10 分钟内覆盖。"""
        alarm1 = alarm_manager.raise_alarm(
            level=2,
            alarm_type="SENSOR_COMM_FAILURE",
            details={"sensor_id": "pt1000", "error_detail": "通信超时"},
            sensor_id="pt1000",
        )
        assert alarm1 is not None

        alarm2 = alarm_manager.raise_alarm(
            level=2,
            alarm_type="SENSOR_COMM_FAILURE",
            details={"sensor_id": "pt1000", "error_detail": "通信超时"},
            sensor_id="pt1000",
        )
        assert alarm2 is None, "应该去除重复告警"

    def test_alarm_notification_handlers(self, alarm_manager):
        """Level >= 2 的告警触发通知。"""
        notifications = []

        def handler(alarm_record):
            notifications.append(alarm_record)

        alarm_manager.register_notification_handler(handler)

        alarm = alarm_manager.raise_alarm(
            level=2,
            alarm_type="CURRENT_SOURCE_UNSTABLE",
            details={"fluctuation_rate": 0.002},
            sensor_id="er",
        )
        assert alarm is not None

        import time

        time.sleep(0.3)

        assert len(notifications) >= 1, "通知处理程序未被调用"

    def test_alarm_level1_no_notification(self, alarm_manager):
        """Level 1 不触发通知。"""
        notifications = []

        def handler(alarm_record):
            notifications.append(alarm_record)

        alarm_manager.register_notification_handler(handler)

        alarm = alarm_manager.raise_alarm(
            level=1,
            alarm_type="ENVIRONMENT_RAPID_CHANGE",
            details={"dt_dt": 1.5},
            sensor_id="",
        )
        assert alarm is not None

        import time

        time.sleep(0.2)

        assert len(notifications) == 0, "Level 1 不应触发通知"

    def test_alarm_statistics(self, alarm_manager):
        """告警统计正确。"""
        alarm_manager.raise_alarm(
            level=2,
            alarm_type="SENSOR_COMM_FAILURE",
            details={"sensor_id": "pt1000"},
            sensor_id="pt1000",
        )
        alarm_manager.raise_alarm(
            level=4,
            alarm_type="SEVERE_PITTING_PERFORATION",
            details={"eta": 5.5},
            sensor_id="er",
        )

        stats = alarm_manager.get_alarm_statistics()
        assert stats["total_active"] == 2
        assert stats["by_level"][2] >= 1
        assert stats["by_level"][4] >= 1

    def test_get_active_alarms_sorted(self, alarm_manager):
        """活跃告警按等级降序排列。"""
        alarm_manager.raise_alarm(
            level=2,
            alarm_type="SENSOR_COMM_FAILURE",
            details={"sensor_id": "pt1000"},
            sensor_id="pt1000",
        )
        alarm_manager.raise_alarm(
            level=4,
            alarm_type="DUAL_SENSOR_FAILURE",
            details={},
            sensor_id="both",
        )
        alarm_manager.raise_alarm(
            level=1,
            alarm_type="EMERGENCY_MODE",
            details={"reason": "测试"},
            sensor_id="",
        )

        active = alarm_manager.get_active_alarms()
        assert len(active) == 3
        assert active[0].level.value >= active[-1].level.value

    def test_alarm_persistence_to_db(self, storage):
        """告警持久化到数据库。"""
        from src.core.alarm_manager import AlarmManager

        AlarmManager.reset_instance()
        am = AlarmManager(storage_manager=storage)

        alarm = am.raise_alarm(
            level=3,
            alarm_type="PITTING_RISK",
            details={"eta": 3.5},
            sensor_id="er",
        )
        assert alarm is not None

        result = storage.query_alarms(level=3)
        assert result["total_count"] >= 1

        AlarmManager.reset_instance()

    def test_acknowledge_nonexistent_alarm(self, alarm_manager):
        """确认不存在的告警返回 False。"""
        ok = alarm_manager.acknowledge_alarm(
            "00000000-0000-0000-0000-000000000000", "op"
        )
        assert not ok

    def test_resolve_already_resolved(self, alarm_manager):
        """重复 resolve 返回 False。"""
        alarm = alarm_manager.raise_alarm(
            level=2,
            alarm_type="SENSOR_COMM_FAILURE",
            details={"sensor_id": "pt1000"},
            sensor_id="pt1000",
        )
        alarm_manager.resolve_alarm(str(alarm.alarm_id), auto=True)
        ok = alarm_manager.resolve_alarm(str(alarm.alarm_id), auto=True)
        assert not ok

    def test_alarm_check_auto_resolve_manual_only(self, alarm_manager):
        """manual_only 告警自动解除不生效。"""
        alarm = alarm_manager.raise_alarm(
            level=4,
            alarm_type="SEVERE_PITTING_PERFORATION",
            details={"eta": 6.0},
            sensor_id="er",
        )
        assert alarm is not None

        ok = alarm_manager.check_auto_resolve(str(alarm.alarm_id))
        assert not ok

        alarm_after = alarm_manager.get_alarm_by_id(str(alarm.alarm_id))
        assert alarm_after.status == AlarmStatus.ACTIVE


# ============================================================================
# TestSecuritySystem
# ============================================================================


class TestSecuritySystem:
    """安全特性测试。"""

    def test_password_hashing(self):
        """密码被哈希，不存储明文。"""
        from src.core.crypto_utils import CryptoUtils

        password = "TestPass123!"
        pwd_hash, salt = CryptoUtils.hash_password(password)

        assert pwd_hash != password
        assert len(salt) == 32

        assert CryptoUtils.verify_password(password, pwd_hash, salt)
        assert not CryptoUtils.verify_password("WrongPass", pwd_hash, salt)
        assert not CryptoUtils.verify_password(password, "badhash", salt)

    def test_hmac_constant_time(self):
        """HMAC 常量时间比较。"""
        import hmac

        result = hmac.compare_digest(b"abc", b"abc")
        assert result

        result2 = hmac.compare_digest(b"abc", b"abd")
        assert not result2

    def test_rbac_permissions(self):
        """基于角色的权限控制。"""
        from src.core.auth_manager import AuthManager, Permission, PermissionError

        auth = AuthManager()
        auth.login("admin", "admin123")

        assert auth.get_current_user() == "admin"
        assert auth.get_current_role() == "Admin"
        assert auth.has_permission(Permission.MODIFY_CONFIG)
        assert auth.has_permission(Permission.MANAGE_USERS)
        assert auth.has_permission(Permission.VIEW_REALTIME)

        import uuid
        viewer_name = f"viewer_{uuid.uuid4().hex[:8]}"
        ok = auth.create_user(viewer_name, "pass123", "Viewer")
        assert ok
        auth.logout()

        auth.login(viewer_name, "pass123")
        assert auth.get_current_role() == "Viewer"
        assert auth.has_permission(Permission.VIEW_REALTIME)
        assert auth.has_permission(Permission.VIEW_HISTORY)
        assert not auth.has_permission(Permission.MODIFY_CONFIG)
        assert not auth.has_permission(Permission.MANAGE_USERS)

        with pytest.raises(PermissionError):
            auth.require_permission(Permission.MODIFY_CONFIG)

        auth.logout()

    def test_login_lockout(self, auth_manager_instance=None):
        """5 次失败后锁定。"""
        from src.core.auth_manager import AuthManager

        auth = AuthManager()
        identifier = "user:nonexistent_user"

        assert not auth.is_locked_out(identifier)

        for _ in range(5):
            result, msg = auth.login("nonexistent_user", "wrong_pass")
            assert not result

        assert auth.is_locked_out(identifier)
        result, msg = auth.login("nonexistent_user", "wrong_pass")
        assert not result
        assert "锁定" in msg

    def test_token_auth(self):
        """Token 认证。"""
        from src.core.auth_manager import AuthManager

        auth = AuthManager()
        auth.login("admin", "admin123")

        token = auth.generate_auth_token("admin")
        assert token is not None
        assert len(token) == 64

        auth.logout()
        result, msg = auth.login_with_token(token)
        assert result
        assert auth.get_current_user() == "admin"

        auth.logout()

    def test_data_integrity_crc(self):
        """CRC-16 数据完整性验证。"""
        guard = DataIntegrityGuard()
        record = {"T": 25.0, "RH": 80.0, "delta_d_ER": 10.0}

        signed = guard.sign_sensor_record(record)
        assert "crc16" in signed

        is_valid, msg = guard.verify_sensor_record(signed)
        assert is_valid
        assert "通过" in msg or "valid" in msg.lower()

        tampered = dict(signed)
        tampered["delta_d_ER"] = 999.0
        is_valid, msg = guard.verify_sensor_record(tampered)
        assert not is_valid

        missing = {"T": 25.0, "RH": 80.0}
        is_valid, msg = guard.verify_sensor_record(missing)
        assert not is_valid
        assert "缺少" in msg or "missing" in msg.lower()

    def test_config_integrity_sha256(self):
        """SHA-256 配置完整性。"""
        guard = DataIntegrityGuard()
        config_json = '{"sensor": {"d0": 100.0}}'

        config_hash = guard.sign_config(config_json)
        assert len(config_hash) == 64

        assert guard.verify_config(config_json, config_hash)
        assert not guard.verify_config('{"sensor": {"d0": 50.0}}', config_hash)

    def test_aes_encryption(self):
        """AES-128-GCM 加解密。"""
        from src.core.crypto_utils import CryptoUtils

        key = b"0123456789abcdef"
        plaintext = b"Hello, Offshore Wind Turbine!"

        ciphertext = CryptoUtils.aes_encrypt(plaintext, key)
        assert len(ciphertext) >= len(plaintext) + 28

        decrypted = CryptoUtils.aes_decrypt(ciphertext, key)
        assert decrypted == plaintext

        with pytest.raises(ValueError):
            CryptoUtils.aes_encrypt(plaintext, b"short")

        wrong_key = b"fedcba9876543210"
        from cryptography.exceptions import InvalidTag

        with pytest.raises(InvalidTag):
            CryptoUtils.aes_decrypt(ciphertext, wrong_key)

    def test_token_generation(self):
        """Token 生成具有唯一性。"""
        from src.core.crypto_utils import CryptoUtils

        tokens = {CryptoUtils.generate_token(16) for _ in range(100)}
        assert len(tokens) == 100

    def test_secure_erase(self):
        """安全擦除不报错。"""
        from src.core.data_integrity import DataIntegrityGuard

        DataIntegrityGuard.secure_erase_sensitive_data(b"secret_password_12345678")
        DataIntegrityGuard.secure_erase_sensitive_data(b"")
        DataIntegrityGuard.secure_erase_sensitive_data(None)


# ============================================================================
# TestCommunicationPackets
# ============================================================================


class TestCommunicationPackets:
    """通信报文格式测试。"""

    def test_binary_packet_roundtrip(self):
        """28 字节二进制报文组包解包往返正确。"""
        from src.comms.data_packet import DataPacket, MessageType

        dp = DataPacket(device_id=1, message_type=MessageType.DATA)

        sensor_data = {"T": 25.5, "RH": 82.3, "Cl_deposition": 5.2}
        corrosion_data = {
            "delta_d_ER": 10.123,
            "delta_d_Inductive": 10.456,
            "CR_out": 0.15,
            "eta": 1.02,
            "valid_flag": True,
            "alarm_status": 0,
            "alarm_bitmask": 0x00,
        }

        packet = dp.pack_sensor_data(sensor_data, corrosion_data)
        assert len(packet) == 28, f"binary packet should be 28 bytes, got {len(packet)}"

        unpacked = dp.unpack_sensor_data(packet)
        assert unpacked is not None, "unpack failed"
        assert pytest.approx(unpacked["T"], abs=0.02) == 25.5
        assert pytest.approx(unpacked["RH"], abs=0.1) == 82.3
        assert pytest.approx(unpacked["delta_d_ER"], abs=0.002) == 10.123

    def test_packet_size_under_100_bytes(self):
        """报文大小 < 100 字节。"""
        from src.comms.data_packet import DataPacket

        dp = DataPacket(device_id=1)
        packet = dp.pack_sensor_data(
            {"T": 25.0, "RH": 80.0, "Cl_deposition": 5.0},
            {
                "delta_d_ER": 10.0,
                "delta_d_Inductive": 10.0,
                "CR_out": 0.15,
                "eta": 1.0,
                "valid_flag": True,
                "alarm_status": 0,
                "alarm_bitmask": 0x00,
            },
        )
        assert len(packet) < 100

        json_packet = dp.pack_sensor_json(
            {"T": 25.0, "RH": 80.0, "Cl_deposition": 5.0},
            {
                "delta_d_ER": 10.0,
                "delta_d_Inductive": 10.0,
                "CR_out": 0.15,
                "eta": 1.0,
                "valid_flag": True,
                "alarm_bitmask": 0,
            },
        )
        assert len(json_packet.encode("utf-8")) < 1000

    def test_json_packet_format(self):
        """JSON 报文包含所有必要字段。"""
        from src.comms.data_packet import DataPacket

        dp = DataPacket(device_id=1)

        json_str = dp.pack_sensor_json(
            {"T": 25.0, "RH": 80.0, "Cl_deposition": 5.0},
            {
                "delta_d_ER": 10.0,
                "delta_d_Inductive": 10.0,
                "CR_out": 0.15,
                "eta": 1.0,
                "valid_flag": True,
                "alarm_bitmask": 0,
            },
        )

        data = json.loads(json_str)
        assert "version" in data
        assert "protocol" in data
        assert "device_id" in data
        assert "timestamp" in data
        assert "message_type" in data
        assert "data" in data
        assert "corrosion" in data
        assert "status" in data
        assert "seq" in data

        assert "temperature" in data["data"]
        assert "humidity" in data["data"]
        assert "cl_deposition" in data["data"]
        assert "delta_d_ER" in data["corrosion"]
        assert "delta_d_Inductive" in data["corrosion"]
        assert "CR_out" in data["corrosion"]
        assert "eta" in data["corrosion"]

    def test_json_unpack(self):
        """JSON 解包正确。"""
        from src.comms.data_packet import DataPacket

        dp = DataPacket()
        test_json = '{"version": 1, "device_id": 99, "data": {"temperature": {"value": 25.0}}}'
        result = dp.unpack_json(test_json)
        assert result is not None
        assert result["device_id"] == 99

        result_none = dp.unpack_json("invalid json")
        assert result_none is None

    def test_alarm_packet(self):
        """告警报文组包。"""
        from src.comms.data_packet import DataPacket

        dp = DataPacket(device_id=1)
        alarm_dict = {
            "level": 3,
            "alarm_type": "PITTING_RISK",
            "sensor_id": "er",
            "message": "点蚀风险: η = 3.5",
        }

        binary = dp.pack_alarm(alarm_dict)
        assert len(binary) > 0

        json_str = dp.pack_alarm_json(alarm_dict)
        assert "PITTING_RISK" in json_str
        parsed = json.loads(json_str)
        assert parsed["message_type"] == "alarm"

    def test_loRa_fragmentation(self):
        """LoRa 分包与重组。"""
        from src.comms.data_packet import DataPacket

        dp = DataPacket()
        test_data = b"x" * 100
        fragments = dp.split_for_lora(test_data)

        if len(fragments) > 1:
            reassembled = DataPacket.reassemble_fragments(fragments)
            assert reassembled == test_data
        else:
            assert fragments[0] == test_data

    def test_status_packet(self):
        """状态报文。"""
        from src.comms.data_packet import DataPacket

        dp = DataPacket()
        status = dp.pack_status_json({"cpu_temp": 45.0, "uptime": 3600})
        parsed = json.loads(status)
        assert parsed["message_type"] == "status"
        assert parsed["status"]["cpu_temp"] == 45.0

    def test_sequence_number_increment(self):
        """序列号递增。"""
        from src.comms.data_packet import DataPacket

        dp = DataPacket()
        seq1 = dp.sequence_number
        dp.pack_sensor_json(
            {"T": 25.0, "RH": 80.0, "Cl_deposition": 5.0},
            {"delta_d_ER": 10.0, "delta_d_Inductive": 10.0,
             "CR_out": 0.15, "eta": 1.0, "valid_flag": True, "alarm_bitmask": 0},
        )
        seq2 = dp.sequence_number
        assert seq2 == (seq1 + 1) % 65536


# ============================================================================
# TestConfigManager
# ============================================================================


class TestConfigManager:
    """配置管理器测试。"""

    def test_config_loads_defaults(self, config_manager):
        """配置加载默认值正确。"""
        assert config_manager._loaded

    def test_config_get_set(self, config_manager):
        """配置 get/set 操作。"""
        config_manager.set("sensor.d0.value", 150.0)
        result = config_manager.get("sensor.d0.value")
        assert result == 150.0

        config_manager.set("sensor.d0.value", 100.0)

    def test_config_get_nonexistent(self, config_manager):
        """不存在的路径返回默认值。"""
        result = config_manager.get("nonexistent.path", "fallback")
        assert result == "fallback"

    def test_config_get_version(self, config_manager):
        """版本号可获取。"""
        version = config_manager.get_version()
        assert isinstance(version, str)
        assert len(version) > 0

    def test_config_get_all(self, config_manager):
        """获取全部配置。"""
        all_config = config_manager.get_all()
        assert isinstance(all_config, dict)
        assert len(all_config) > 0

    def test_config_reset_to_defaults(self, config_manager):
        """重置到默认值。"""
        config_manager.set("sensor.d0.value", 999.0)
        config_manager.reset_to_defaults()
        after = config_manager.get("sensor.d0.value")
        dflt = config_manager.get_default("sensor.d0.value")
        assert after == dflt


# ============================================================================
# TestSensorDataSerialization
# ============================================================================


class TestSensorDataSerialization:
    """数据模型序列化测试。"""

    def test_sensor_data_to_from_dict(self, sample_sensor_data):
        """SensorData 往返序列化。"""
        d = sample_sensor_data.to_dict()
        restored = SensorData.from_dict(d)
        assert restored.T == sample_sensor_data.T
        assert restored.RH == sample_sensor_data.RH
        assert restored.delta_d_ER == sample_sensor_data.delta_d_ER

    def test_corrosion_record_to_dict(self, sample_corrosion_record):
        """CorrosionRecord 序列化。"""
        d = sample_corrosion_record.to_dict()
        assert d["CR_ER"] == sample_corrosion_record.CR_ER
        assert d["CR_out"] == sample_corrosion_record.CR_out

    def test_alarm_record_to_dict(self, sample_alarm_record):
        """AlarmRecord 序列化。"""
        d = sample_alarm_record.to_dict()
        assert d["level"] == sample_alarm_record.level.value
        assert d["alarm_type"] == sample_alarm_record.alarm_type.value
        assert d["status"] == sample_alarm_record.status.value
        assert "alarm_id" in d
        assert isinstance(d["alarm_id"], str)

    def test_audit_log_entry_to_dict(self):
        """AuditLogEntry 序列化。"""
        entry = AuditLogEntry(
            operator="admin",
            operation_type=OperationType.SYSTEM_START,
            details={"version": "1.0"},
            result="success",
        )
        d = entry.to_dict()
        assert d["operator"] == "admin"
        assert d["result"] == "success"

    def test_sensor_data_timestamp_isoformat(self, sample_sensor_data):
        """时间戳以 ISO 格式序列化。"""
        d = sample_sensor_data.to_dict()
        ts = d["timestamp"]
        assert isinstance(ts, str)
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None

    def test_sensor_data_from_dict_string_timestamp(self):
        """从字符串时间戳还原 SensorData。"""
        d = {"timestamp": "2025-06-15T12:00:00+00:00", "T": 28.5, "RH": 85.0}
        sd = SensorData.from_dict(d)
        assert sd.T == 28.5
        assert sd.RH == 85.0
        assert sd.timestamp.year == 2025

    def test_sensor_data_from_dict_invalid_timestamp(self):
        """无效时间戳使用备用值。"""
        try:
            d = {"timestamp": "invalid_timestamp", "T": 25.0}
            sd = SensorData.from_dict(d)
            assert sd.T == 25.0
            assert isinstance(sd.timestamp, datetime)
        except (ValueError, TypeError):
            d = {"T": 25.0}
            sd = SensorData.from_dict(d)
            assert sd.T == 25.0


# ============================================================================
# TestAppLifecycle
# ============================================================================


class TestAppLifecycle:
    """应用生命周期测试。"""

    def test_app_singleton(self):
        """App 是单例的。"""
        from src.core.app import App

        App.reset_instance()
        app1 = App()
        app2 = App()
        assert app1 is app2
        App.reset_instance()

    def test_app_initialize_stop(self, app):
        """App 初始化和停止成功。"""
        assert app._initialized
        try:
            app.start()
        except Exception:
            pass

        ok = app.stop()
        assert ok

    def test_app_signal_connect_emit(self, app):
        """信号连接和发射。"""
        received = []

        def slot(*args, **kwargs):
            received.append((args, kwargs))

        app.connect("sensor_data_received", slot)
        app.emit("sensor_data_received", "test_data")

        assert len(received) == 1
        assert received[0][0][0] == "test_data"

        app.disconnect("sensor_data_received", slot)
        app.emit("sensor_data_received", "no_receiver")
        assert len(received) == 1

    def test_app_states(self, app):
        """App 状态机转换。"""
        from src.core.app import AppState

        assert app.state == AppState.INITIALIZED

        app.start()
        assert app.state == AppState.RUNNING
        assert app.is_running

        app.stop()
        assert app.state == AppState.STOPPED

    def test_app_config_manager(self, app):
        """App 持有 ConfigManager。"""
        cm = app.config_manager
        assert cm is not None
        version = cm.get_version()
        assert len(version) > 0

    def test_app_logger(self, app):
        """App 持有 Logger。"""
        log = app.logger
        assert log is not None
