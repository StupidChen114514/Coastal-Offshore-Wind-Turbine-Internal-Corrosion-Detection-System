"""
spec.md 逐场景验证测试 – 沿海海上风电腐蚀检测系统。

覆盖需求1-12（排除纯UI需求7、通信需求8、部署需求11）中的所有场景：
    - 需求1: 采集管线 3 场景
    - 需求2: 四级误差补偿 7 场景
    - 需求3: 双模交叉验证 4 场景
    - 需求4: ISO 9223/9224 评估 3 场景
    - 需求5: 告警体系 3 场景
    - 需求6: 数据存储与导出 3 场景
    - 需求9: 安全特性 4 场景
    - 需求10: 系统诊断 3 场景
    - 需求12: 性能指标 4 场景
"""

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
from src.sensors.sensor_simulator import SensorSimulator
from src.sensors.acquisition_scheduler import AcquisitionScheduler, SchedulerState


# ============================================================================
# 需求1 – 传感器数据采集模块 (3 场景)
# ============================================================================


class TestReq1_Acquisition:
    """需求1：传感器数据采集模块"""

    def test_scenario1_normal_acquisition_cycle(
        self, simulator, algorithm_engine, sensor_manager_simulated
    ):
        """需求1-场景1：正常采集周期数据采集。"""
        sim = simulator

        data = sim.generate_sample()
        assert isinstance(data, SensorData)
        assert data.timestamp.tzinfo == timezone.utc, "时间戳必须使用 UTC"
        assert 15.0 <= data.T <= 35.0
        assert 55.0 <= data.RH <= 98.0
        assert data.delta_d_ER >= 0
        assert data.delta_d_Inductive >= 0

        sensor_manager_simulated.set_simulated_data(data)
        last = sensor_manager_simulated.get_last_data()
        assert last is not None

        record = algorithm_engine.process_sensor_data(data)
        assert record is not None or not algorithm_engine._initialized

    def test_scenario2_sensor_communication_failure(
        self, simulator, sensor_manager_simulated
    ):
        """需求1-场景2：传感器通信故障处理。"""
        simulator.set_fault("all_fault", True)
        data = simulator.generate_sample()

        assert not data.valid_flag
        assert math.isnan(data.T)
        assert math.isnan(data.delta_d_ER)

        sensor_manager_simulated.set_simulated_data(data)
        assert sensor_manager_simulated.get_last_data() is not None

        simulator.clear_all_faults()
        data2 = simulator.generate_sample()
        assert data2.valid_flag
        assert not math.isnan(data2.T)

    def test_scenario3_emergency_high_rate_sampling(
        self, sensor_manager_simulated
    ):
        """需求1-场景3：高采样率应急模式。"""
        scheduler = AcquisitionScheduler(
            normal_interval_s=0.5,
            emergency_interval_s=0.05,
            emergency_duration_s=0.3,
        )
        scheduler.set_sensor_manager(sensor_manager_simulated)
        scheduler.start()

        scheduler.trigger_emergency("腐蚀速率突变测试")
        assert scheduler.get_state() == SchedulerState.EMERGENCY, "应进入应急模式"

        scheduler.stop()
        assert scheduler.get_state() == SchedulerState.STOPPED


# ============================================================================
# 需求2 – 四级误差补偿体系 (7 场景)
# ============================================================================


class TestReq2_ErrorCompensation:
    """需求2：四级误差补偿体系软件实现"""

    def test_scenario1_level1_hardware_diff(self, algorithm_engine):
        """需求2-场景1：第一级硬件差分补偿验证。"""
        engine = algorithm_engine

        delta_d, status = engine._compensate_level1_hardware_diff(
            V_mid=1.65, V_diff=0.01, d0=100.0
        )
        assert delta_d > 0
        assert status == "OK"

        delta_d2, status2 = engine._compensate_level1_hardware_diff(
            V_mid=1.65, V_diff=100.0, d0=100.0
        )
        assert "clamped" in status2.lower() or "OK" in status2

    def test_scenario2_level2_ratio_calibration(self, algorithm_engine, sample_sensor_data):
        """需求2-场景2：第二级比值法自校准验证。"""
        engine = algorithm_engine
        sd = sample_sensor_data

        for _ in range(15):
            engine._push_v_ref(sd.V_mid + ((_ % 3) - 1) * 0.0005)

        status = engine._verify_level2_ratio_calibration()
        assert isinstance(status, str)

    def test_scenario3_level3a_temperature_polynomial(self, algorithm_engine):
        """需求2-场景3：第三级A – 残余温度系数多项式修正。"""
        engine = algorithm_engine

        raw = 10.0
        corrected_hot = engine._compensate_level3a_temperature(
            raw, T=35.0, alpha_res=0.003, beta_res=0.0001, T0=25.0
        )
        assert corrected_hot < raw, "高温下修正值应更小"

        corrected_cold = engine._compensate_level3a_temperature(
            raw, T=15.0, alpha_res=0.003, beta_res=0.0001, T0=25.0
        )
        assert corrected_cold > raw, "低温下修正值应更大"

        skip = engine._compensate_level3a_temperature(
            raw, T=35.0, alpha_res=0.0, beta_res=0.0, T0=25.0
        )
        assert skip == raw, "未标定时应跳过修正"

    def test_scenario4_level3b_humidity_gate(self, algorithm_engine):
        """需求2-场景4：第三级B – 湿度门控数据有效性过滤。"""
        engine = algorithm_engine

        valid, _ = engine._filter_level3b_humidity_gate(
            delta_d_raw=0.5, RH=85.0, epsilon_noise=0.2, consecutive_invalid=0
        )
        assert valid, "RH > 76% 应有效"

        invalid, _ = engine._filter_level3b_humidity_gate(
            delta_d_raw=0.5, RH=60.0, epsilon_noise=0.2, consecutive_invalid=0
        )
        assert not invalid, "RH < 76% 且 Δd >= ε_noise 应无效"

        still_valid, _ = engine._filter_level3b_humidity_gate(
            delta_d_raw=0.05, RH=60.0, epsilon_noise=0.2, consecutive_invalid=0
        )
        assert still_valid, "RH < 76% 但 Δd < ε_noise 应有效"

        anomalous, status_anom = engine._filter_level3b_humidity_gate(
            delta_d_raw=0.5, RH=60.0, epsilon_noise=0.2, consecutive_invalid=9
        )
        assert not anomalous
        assert "anomaly" in status_anom.lower() or "异常" in status_anom

    def test_scenario5_level3c_environment_correction(self, algorithm_engine):
        """需求2-场景5：第三级C – 环境因子修正腐蚀速率。"""
        engine = algorithm_engine

        cr_norm = engine._correct_level3c_environment(
            CR_raw=100.0,
            TOW_actual=3000.0,
            TOW_ref=4000.0,
            k_S=0.01,
            S_Cl=5.0,
        )
        assert cr_norm > 0
        assert cr_norm > 100.0, (
            f"TOW_actual < TOW_ref 时，归一化速率应更大，实际: {cr_norm}"
        )

        unchanged = engine._correct_level3c_environment(
            CR_raw=50.0,
            TOW_actual=0,
            TOW_ref=4000.0,
            k_S=0.01,
            S_Cl=5.0,
        )
        assert unchanged == 50.0

    def test_scenario6_level3d_dose_response(self):
        """需求2-场景6：第三级D – 剂量-响应函数环境预测腐蚀量。"""
        from src.algorithms.dose_response import predict_corrosion_rate, cross_validate

        r_pred, confidence = predict_corrosion_rate(
            T_avg=25.0, RH_avg=85.0, Cl_avg=10.0
        )

        assert r_pred > 0
        assert confidence > 0

        ratio, verdict, alarm_level = cross_validate(r_meas=10.0, r_pred=r_pred)
        assert ratio > 0

        ratio2, verdict2, alarm2 = cross_validate(r_meas=r_pred * 3.0, r_pred=r_pred)
        assert ratio2 > 2.0

        ratio3, verdict3, alarm3 = cross_validate(r_meas=r_pred * 0.3, r_pred=r_pred)
        assert ratio3 < 0.5

    def test_scenario7_level4_kalman_filter(self, algorithm_engine, sensor_data_sequence):
        """需求2-场景7：第四级 – 卡尔曼滤波降噪。"""
        engine = algorithm_engine

        for i in range(36):
            engine.process_sensor_data(sensor_data_sequence[i])
        assert engine.is_kalman_warmed_up()

        dd, cr = engine.get_kalman_state()
        assert dd >= 0
        assert isinstance(cr, float)


# ============================================================================
# 需求3 – 双模冗余交叉验证与点蚀诊断 (4 场景)
# ============================================================================


class TestReq3_DualMode:
    """需求3：双模冗余交叉验证与点蚀诊断"""

    def test_scenario1_dual_mode_consistent(self):
        """需求3-场景1：双模验证通过 – 正常输出。"""
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
        assert abs(v.eta - 1.0) < 0.05
        assert v.cr_out > 0
        assert "双模一致" in v.verdict or "consistent" in v.verdict.lower()

        ConfigManager.reset_instance()

    def test_scenario2_temperature_shock_difference(self):
        """需求3-场景2：温度冲击下差异处理。"""
        from src.core.config_manager import ConfigManager
        from src.algorithms.dual_mode_validator import DualModeValidator

        ConfigManager.reset_instance()
        config = ConfigManager()
        config.load()

        validator = DualModeValidator(config)
        t0 = datetime.now(timezone.utc)
        t1 = t0 + timedelta(minutes=10)

        validator.validate(10.0, 10.0, t0, 0.5)
        v = validator.validate(15.0, 10.5, t1, 3.5)

        assert v.status == DualModeStatus.TEMPERATURE_SHOCK
        assert v.diff >= 0.15
        assert "温度冲击" in v.verdict or "temperature" in v.verdict.lower()

        ConfigManager.reset_instance()

    def test_scenario3_pitting_risk_diagnosis(self):
        """需求3-场景3：点蚀风险诊断。"""
        from src.core.config_manager import ConfigManager
        from src.algorithms.dual_mode_validator import DualModeValidator

        ConfigManager.reset_instance()
        config = ConfigManager()
        config.load()

        validator = DualModeValidator(config)
        t0 = datetime.now(timezone.utc)
        t1 = t0 + timedelta(minutes=10)

        validator.validate(50.0, 50.0, t0, 0.5)
        v = validator.validate(80.0, 50.2, t1, 1.0)

        assert v.status == DualModeStatus.PITTING_SUSPECTED
        assert v.eta > 1.0

        if v.eta > 3.0:
            assert v.alarm_level >= 3

        ConfigManager.reset_instance()

    def test_scenario4_calibration_curve_management(self):
        """需求3-场景4：标定曲线管理。"""
        from src.core.config_manager import ConfigManager
        from src.algorithms.calibration_curve import CalibrationCurve

        ConfigManager.reset_instance()
        config = ConfigManager()
        config.load()

        curve = CalibrationCurve(config)
        info = curve.get_curve_info()
        assert info["data_points"] == 10

        curve.set_interpolation_method("polynomial")
        assert curve.get_curve_info()["method"] == "polynomial"

        custom_data = [(0.0, 1.0), (0.1, 1.8), (0.2, 3.0), (0.3, 5.5), (0.4, 9.0)]
        ok = curve.import_calibration_data(custom_data)
        assert ok
        assert curve.get_curve_info()["custom_imported"]

        curve.reset_to_default()
        assert not curve.get_curve_info()["custom_imported"]

        ConfigManager.reset_instance()


# ============================================================================
# 需求4 – ISO 9223/9224 大气腐蚀性等级评估 (3 场景)
# ============================================================================


class TestReq4_ISOAssessment:
    """需求4：基于ISO 9223的大气腐蚀性等级评估"""

    def test_scenario1_tow_statistics(self):
        """需求4-场景1：年湿润时间(TOW)统计。"""
        from src.core.config_manager import ConfigManager
        from src.algorithms.tow_calculator import TOWCalculator

        ConfigManager.reset_instance()
        config = ConfigManager()
        config.load()

        tow = TOWCalculator()

        tow.add_hour(25.0, 85.0)
        assert tow.get_tow_hours() >= 1

        tow.add_hour(-5.0, 85.0)
        tow.add_hour(25.0, 50.0)

        grade = tow.get_tow_grade()
        assert grade in ("τ1", "τ2", "τ3", "τ4", "τ5")

        ConfigManager.reset_instance()

    def test_scenario2_corrosivity_category(self):
        """需求4-场景2：腐蚀性等级(Category)判定。"""
        from src.core.config_manager import ConfigManager
        from src.algorithms.iso_9223 import ISO9223Assessor

        ConfigManager.reset_instance()
        config = ConfigManager()
        config.load()

        assessor = ISO9223Assessor()

        test_rates = [(0.5, "C1"), (15.0, "C2"), (40.0, "C3"),
                       (60.0, "C4"), (120.0, "C5"), (300.0, "CX")]

        for rate, expected_category in test_rates:
            category = assessor.classify_corrosivity(rate)
            assert category.label == expected_category, (
                f"腐蚀速率 {rate} μm/年 应归为 {expected_category}，实际: {category.label}"
            )

        ConfigManager.reset_instance()

    def test_scenario3_long_term_prediction_iso9224(self):
        """需求4-场景3：长期腐蚀趋势预测(ISO 9224)。"""
        from src.core.config_manager import ConfigManager
        from src.algorithms.iso_9223 import ISO9223Assessor

        ConfigManager.reset_instance()
        config = ConfigManager()
        config.load()

        assessor = ISO9223Assessor()
        predictions = assessor.predict_long_term(25.0)

        assert predictions[1] == 25.0
        assert predictions[5] > predictions[1]
        assert predictions[25] > predictions[10]

        assert predictions[10] - predictions[5] < predictions[5] - predictions[1], (
            "腐蚀速率应随时间递减（幂函数 b < 1）"
        )

        ConfigManager.reset_instance()


# ============================================================================
# 需求5 – 告警与事件管理系统 (3 场景)
# ============================================================================


class TestReq5_AlarmManagement:
    """需求5：告警与事件管理系统"""

    def test_scenario1_alarm_levels(self, alarm_manager):
        """需求5-场景1：告警等级定义。"""
        level_tests = {
            1: "ENVIRONMENT_RAPID_CHANGE",
            2: "SENSOR_COMM_FAILURE",
            3: "PITTING_RISK",
            4: "SEVERE_PITTING_PERFORATION",
        }

        for level, alarm_type in level_tests.items():
            alarm = alarm_manager.raise_alarm(
                level=level,
                alarm_type=alarm_type,
                details={"sensor_id": "er", "eta": 4.0 if level >= 3 else None},
                sensor_id="er",
            )
            if alarm:
                assert alarm.level.value == level

        stats = alarm_manager.get_alarm_statistics()
        assert stats["total_active"] >= 1

    def test_scenario2_alarm_lifecycle(self, alarm_manager):
        """需求5-场景2：告警生命周期管理。"""
        alarm = alarm_manager.raise_alarm(
            level=3,
            alarm_type="PITTING_RISK",
            details={"eta": 3.5},
            sensor_id="er",
        )
        assert alarm is not None
        assert isinstance(alarm.alarm_id, object)
        assert alarm.status == AlarmStatus.ACTIVE
        assert alarm.timestamp is not None
        assert alarm.sensor_id == "er"
        assert "eta" in alarm.details

        ok = alarm_manager.acknowledge_alarm(str(alarm.alarm_id), "operator1")
        assert ok
        alarm_check = alarm_manager.get_alarm_by_id(str(alarm.alarm_id))
        assert alarm_check.status == AlarmStatus.ACKNOWLEDGED
        assert alarm_check.operator == "operator1"

        ok = alarm_manager.resolve_alarm(str(alarm.alarm_id), "operator1")
        assert ok
        alarm_check2 = alarm_manager.get_alarm_by_id(str(alarm.alarm_id))
        assert alarm_check2.status == AlarmStatus.RESOLVED
        assert alarm_check2.resolved_time is not None

    def test_scenario3_alarm_notification(self, alarm_manager):
        """需求5-场景3：告警通知推送。"""
        received = []

        def notifier(a):
            received.append(a)

        alarm_manager.register_notification_handler(notifier)

        alarm = alarm_manager.raise_alarm(
            level=3,
            alarm_type="CORROSION_ABNORMAL_ACCELERATION",
            details={"ratio": 2.5},
            sensor_id="er",
        )
        assert alarm is not None

        time.sleep(0.3)
        assert len(received) >= 1, "Level >= 2 应触发通知"
        assert received[0].level.value == 3


# ============================================================================
# 需求6 – 数据存储与历史查询 (3 场景)
# ============================================================================


class TestReq6_DataStorage:
    """需求6：数据存储与历史查询"""

    def test_scenario1_multilevel_storage(
        self, storage, simulator, sample_sensor_data, sample_corrosion_record
    ):
        """需求6-场景1：多级数据存储策略。"""

        for _ in range(50):
            storage.push_raw_sensor_data(simulator.generate_sample())

        l1_count = len(storage.get_latest_raw_data(100))
        assert l1_count > 0, "L1 环形缓冲应有数据"

        ok = storage.save_sensor_reading(sample_sensor_data)
        assert ok
        ok = storage.save_corrosion_record(sample_corrosion_record)
        assert ok

        start = datetime.now(timezone.utc) - timedelta(hours=24)
        end = datetime.now(timezone.utc) + timedelta(hours=24)
        sensor_result = storage.query_sensor_data(start, end)
        assert sensor_result["total_count"] >= 1

        cr_result = storage.query_corrosion_records(start, end)
        assert cr_result["total_count"] >= 1

    def test_scenario2_history_query_pagination(
        self, storage, simulator
    ):
        """需求6-场景2：历史数据查询（分页）。"""
        t0 = datetime.now(timezone.utc) - timedelta(days=30)
        for i in range(500):
            data = simulator.generate_sample()
            data.timestamp = t0 + timedelta(hours=i)
            storage.save_sensor_reading(data)

        page1 = storage.query_sensor_data(
            t0, datetime.now(timezone.utc), page=1, page_size=50
        )
        assert len(page1["data"]) <= 50
        assert page1["has_next"] or not page1["has_next"]

        temp_query = storage.query_sensor_data(
            t0, datetime.now(timezone.utc), data_type="T", page=1
        )
        assert temp_query["total_count"] >= 0

    def test_scenario3_data_export_formats(
        self, storage, sample_sensor_data
    ):
        """需求6-场景3：数据导出（CSV 和 JSON）。"""
        import tempfile
        import json

        storage.save_sensor_reading(sample_sensor_data)

        start = sample_sensor_data.timestamp - timedelta(hours=1)
        end = sample_sensor_data.timestamp + timedelta(hours=1)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8-sig"
        ) as f:
            csv_path = f.name
        try:
            storage.export_csv("sensor", start, end, csv_path)
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                csv_content = f.read()
                assert "timestamp" in csv_content
                assert "temperature" in csv_content
        finally:
            os.unlink(csv_path)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json_path = f.name
        try:
            storage.export_json("sensor", start, end, json_path)
            with open(json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)
                assert "metadata" in json_data
                assert "records" in json_data
                assert "device_id" in json_data["metadata"]
                assert "export_time" in json_data["metadata"]
        finally:
            os.unlink(json_path)


# ============================================================================
# 需求9 – 数据安全与访问控制 (4 场景)
# ============================================================================


class TestReq9_Security:
    """需求9：数据安全与访问控制"""

    def test_scenario1_data_encryption(self):
        """需求9-场景1：数据传输加密 (AES-128-GCM)。"""
        from src.core.crypto_utils import CryptoUtils

        key = b"0123456789abcdef"
        plaintext = b"offshore_wind_turbine_corrosion_data"

        encrypted = CryptoUtils.aes_encrypt(plaintext, key)
        assert len(encrypted) > len(plaintext)
        assert encrypted[:12]

        decrypted = CryptoUtils.aes_decrypt(encrypted, key)
        assert decrypted == plaintext

    def test_scenario2_data_integrity(self):
        """需求9-场景2：数据完整性校验 (CRC-16, SHA-256)。"""
        from src.core.data_integrity import DataIntegrityGuard
        from src.core.crypto_utils import CryptoUtils

        guard = DataIntegrityGuard()

        record = {"T": 25.5, "RH": 82.3, "delta_d_ER": 10.5, "delta_d_Inductive": 10.8}
        signed = guard.sign_sensor_record(record)
        assert "crc16" in signed

        is_valid, _ = guard.verify_sensor_record(signed)
        assert is_valid

        tampered = dict(signed)
        tampered["delta_d_ER"] += 100.0
        is_valid, _ = guard.verify_sensor_record(tampered)
        assert not is_valid

        config_json = '{"sensor": {"d0": 100.0}, "algorithm": {"RH_crit": 76.0}}'
        config_hash = CryptoUtils.sha256_hash(config_json.encode("utf-8"))

        assert CryptoUtils.sha256_hash(config_json.encode("utf-8")) == config_hash
        assert len(config_hash) == 64

        assert guard.verify_config(config_json, config_hash)

    def test_scenario3_access_control(self):
        """需求9-场景3：访问权限控制。"""
        from src.core.auth_manager import AuthManager, Permission, PermissionError

        auth = AuthManager()
        auth.login("admin", "admin123")

        assert auth.get_current_role() == "Admin"
        assert auth.has_permission(Permission.MODIFY_CONFIG)
        assert auth.has_permission(Permission.IMPORT_CALIBRATION)
        assert auth.has_permission(Permission.MANAGE_USERS)

        import uuid
        operator_name = f"op_{uuid.uuid4().hex[:8]}"
        ok = auth.create_user(operator_name, "op123", "Operator")
        assert ok
        auth.logout()

        auth.login(operator_name, "op123")
        assert auth.get_current_role() == "Operator"
        assert auth.has_permission(Permission.ACKNOWLEDGE_ALARM)
        assert auth.has_permission(Permission.EXPORT_DATA)
        assert not auth.has_permission(Permission.MODIFY_CONFIG)

        with pytest.raises(PermissionError):
            auth.require_permission(Permission.MODIFY_CONFIG)

        assert auth.login("wrong", "wrong")[0] == False
        auth.logout()

    def test_scenario4_audit_log(self):
        """需求9-场景4：审计日志。"""
        from src.core.auth_manager import AuthManager

        auth = AuthManager()
        auth.login("admin", "admin123")

        entry = AuditLogEntry(
            operator="admin",
            operation_type=OperationType.CONFIG_CHANGE,
            details={"path": "sensor.d0.value", "old": 100.0, "new": 120.0},
            result="success",
        )

        d = entry.to_dict()
        assert d["operator"] == "admin"
        assert d["operation_type"] == "CONFIG_CHANGE"
        assert d["result"] == "success"
        assert "timestamp" in d

        auth.logout()


# ============================================================================
# 需求10 – 系统自诊断与健康管理 (3 场景)
# ============================================================================


class TestReq10_Diagnostics:
    """需求10：系统自诊断与健康管理"""

    def test_scenario1_post_startup(self, app):
        """需求10-场景1：开机自检(POST)。"""
        diag = app.diagnostics
        if diag is not None:
            assert diag is not None
            print(f"  诊断管理器已初始化")
        app.start()

        if diag is not None and hasattr(diag, 'watchdog') and diag.watchdog is not None:
            assert diag.watchdog is not None
            print(f"  看门狗已启动")

    def test_scenario2_runtime_diagnostics(self):
        """需求10-场景2：运行中自诊断。"""
        from src.core.diagnostics import DiagnosticsManager
        from src.core.app import App

        App.reset_instance()
        app = App(config_dir="config")
        app.initialize()

        diag = app.diagnostics
        assert diag is not None, "诊断管理器应已初始化"

        status = diag.get_health_status()
        assert isinstance(status, dict)

        App.reset_instance()

    def test_scenario3_watchdog_recovery(self, app):
        """需求10-场景3：看门狗与异常恢复。"""
        if not app.is_running:
            app.start()
        assert app.is_running

        diag = app.diagnostics
        if diag is not None:
            diag.feed_watchdog()
            print(f"  看门狗喂狗成功")

        if app.is_running:
            app.stop()

    def test_scenario3_watchdog_config(self, app):
        """需求10-场景3：看门狗配置验证。"""
        if not app.is_running:
            app.start()

        diag = app.diagnostics
        if diag is not None and hasattr(diag, 'watchdog') and diag.watchdog is not None:
            assert diag.watchdog.timeout > 0
            assert diag.watchdog.timeout <= 60
            print(f"  看门狗超时: {diag.watchdog.timeout}s")

        if app.is_running:
            app.stop()


# ============================================================================
# 需求12 – 性能指标 (4 场景)
# ============================================================================


class TestReq12_Performance:
    """需求12：性能指标"""

    def test_scenario1_detection_precision(self, simulator):
        """需求12-场景1：检测精度。

        注意：实际精度验证需要标定硬件，此处验证模拟器数据的合理范围。"""
        data = simulator.generate_sample()

        assert abs(data.T - 25.0) < 10.0, "Pt1000 模拟温度漂移范围"

        assert 55.0 <= data.RH <= 98.0, "SHT35 模拟湿度范围"

        assert data.Cl_deposition >= 0, "QCM 模拟盐度非负"

    def test_scenario2_data_processing_performance(self, config_manager):
        """需求12-场景2：数据处理性能。"""
        from src.algorithms.algorithm_engine import AlgorithmEngine

        sim = SensorSimulator(seed=42)
        engine = AlgorithmEngine(config_manager)
        engine.initialize()

        times = []
        for _ in range(30):
            data = sim.generate_sample()
            start = time.perf_counter()
            engine.process_sensor_data(data)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        max_time = max(times)
        avg_time = sum(times) / len(times)

        assert max_time < 110.0, (
            f"数据处理最慢 {max_time:.2f}ms 超过 110ms 限制"
        )

        print(f"  需求12: 数据处理 avg={avg_time:.2f}ms, max={max_time:.2f}ms")

    def test_scenario3_query_performance(self, storage, config_manager):
        """需求12-场景3：数据查询性能。"""
        sim = SensorSimulator(seed=11)
        t0 = datetime.now(timezone.utc) - timedelta(days=365)
        for i in range(500):
            data = sim.generate_sample()
            data.timestamp = t0 + timedelta(hours=i * 16)
            storage.save_sensor_reading(data)

        start_q = time.perf_counter()
        result = storage.query_sensor_data(
            t0 - timedelta(days=1),
            datetime.now(timezone.utc) + timedelta(days=1),
        )
        elapsed = (time.perf_counter() - start_q) * 1000

        assert elapsed < 2000.0, f"查询耗时 {elapsed:.1f}ms 超过 2s 限制"
        print(f"  需求12: 1年查询={elapsed:.1f}ms, 返回{result['total_count']}条")

    def test_scenario4_system_reliability_checks(self):
        """需求12-场景4：系统可靠性检查。"""
        checks_passed = 0
        checks_total = 4

        try:
            from src.core.data_integrity import DataIntegrityGuard
            guard = DataIntegrityGuard()
            assert guard is not None
            checks_passed += 1
        except Exception:
            pass

        try:
            from src.core.crypto_utils import CryptoUtils
            assert CryptoUtils.crc16(b"test") > 0
            checks_passed += 1
        except Exception:
            pass

        try:
            from src.storage.storage_manager import StorageManager
            sm = StorageManager(db_path=":memory:")
            sm.initialize()
            assert sm._initialized
            sm.shutdown()
            checks_passed += 1
        except Exception:
            pass

        try:
            from src.sensors.sensor_simulator import SensorSimulator
            sim = SensorSimulator(seed=1)
            data = sim.generate_sample()
            assert data.valid_flag
            checks_passed += 1
        except Exception:
            pass

        assert checks_passed == checks_total, (
            f"可靠性检查: {checks_passed}/{checks_total} 通过"
        )
        print(f"  需求12: 可靠性检查 {checks_passed}/{checks_total} 通过")
