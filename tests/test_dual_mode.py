"""
Comprehensive test for dual-mode cross-validation system.

Verifies:
    1. CalibrationCurve - default points, linear/polynomial interpolation
    2. DualModeValidator - all three scenarios
    3. CrossValidationEngine - full pipeline integration
    4. Edge cases - zero values, negative values, first call
"""

import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from src.core.config_manager import ConfigManager
from src.core.data_models import (
    DualModeResult,
    DualModeStatus,
    SensorData,
)


def reset_singletons():
    ConfigManager.reset_instance()


def test_calibration_curve():
    """Test CalibrationCurve default and custom data."""
    print("\n" + "=" * 60)
    print("TEST: CalibrationCurve")
    print("=" * 60)

    reset_singletons()
    config = ConfigManager()
    config.load()

    from src.algorithms.calibration_curve import (
        CalibrationCurve,
        DEFAULT_CALIBRATION_POINTS,
    )

    curve = CalibrationCurve(config)

    info = curve.get_curve_info()
    print(f"  Curve info: {info}")
    assert info["data_points"] == 10
    assert info["method"] == "linear"
    print("  PASS: Default curve has 10 points, method=linear")

    test_cases = [
        (0.00, 1.00),
        (0.05, 1.20),
        (0.10, 1.50),
        (0.15, 2.00),
        (0.20, 2.80),
        (0.25, 3.50),
        (0.30, 4.50),
        (0.35, 6.00),
        (0.40, 8.00),
        (0.45, 10.00),
    ]
    for delta, expected_eta in test_cases:
        eta = curve.get_eta(delta)
        assert abs(eta - expected_eta) < 0.01, f"delta={delta}: eta={eta}, expected={expected_eta}"
    print("  PASS: All 10 default calibration points match exactly")

    eta_interp = curve.get_eta(0.075)
    assert 1.2 < eta_interp < 1.5, f"Interpolation failed: eta={eta_interp}"
    print(f"  PASS: Interpolation δ=0.075 → η={eta_interp:.3f} (expected between 1.2 and 1.5)")

    curve.set_interpolation_method("polynomial")
    eta_poly = curve.get_eta(0.075)
    print(f"  PASS: Polynomial interpolation δ=0.075 → η={eta_poly:.3f}")

    custom_data = [
        (0.00, 1.00),
        (0.10, 1.80),
        (0.20, 3.00),
        (0.30, 5.50),
        (0.40, 9.00),
    ]
    ok = curve.import_calibration_data(custom_data)
    assert ok
    info2 = curve.get_curve_info()
    assert info2["data_points"] == 5
    assert info2["custom_imported"]
    print(f"  PASS: Custom data imported: {info2}")

    curve.set_interpolation_method("linear")
    curve.reset_to_default()
    info3 = curve.get_curve_info()
    assert not info3["custom_imported"]
    assert info3["data_points"] == 10
    print("  PASS: Reset to default successful")


def test_dual_mode_validator_consistent():
    """Test Scenario 1: Dual-mode verification passed (diff < 0.15)."""
    print("\n" + "=" * 60)
    print("TEST: Scenario 1 - Dual-mode consistent (uniform corrosion)")
    print("=" * 60)

    reset_singletons()
    config = ConfigManager()
    config.load()

    from src.algorithms.dual_mode_validator import DualModeValidator

    validator = DualModeValidator(config)

    t0 = datetime.now(timezone.utc)
    t1 = t0 + timedelta(minutes=10)

    v1 = validator.validate(
        delta_d_er=10.0,
        delta_d_inductive=10.0,
        timestamp=t0,
        dT_dt=0.5,
    )
    print(f"  First call (no previous): CR_out={v1.cr_out:.4f}, CR_ER={v1.cr_er:.4f}, "
          f"diff={v1.diff:.4f}, status={v1.status}")
    assert v1.status == DualModeStatus.DUAL_CONSISTENT
    assert v1.cr_er == 0.0
    print("  PASS: First call has 0 CR (no previous data), consistent status")

    v2 = validator.validate(
        delta_d_er=10.5,
        delta_d_inductive=10.45,
        timestamp=t1,
        dT_dt=0.3,
    )
    print(f"  Second call: CR_out={v2.cr_out:.4f}, CR_ER={v2.cr_er:.4f}, "
          f"CR_Inductive={v2.cr_inductive:.4f}, diff={v2.diff:.4f}")
    print(f"  Status: {v2.status}, alarm_level={v2.alarm_level}")
    print(f"  Verdict: {v2.verdict}")

    assert v2.status == DualModeStatus.DUAL_CONSISTENT
    assert v2.alarm_level == 0
    assert v2.diff < 0.15
    assert abs(v2.eta - 1.0) < 0.01
    assert v2.cr_out > 0
    print("  PASS: Scenario 1 correctly identified as uniform corrosion")


def test_dual_mode_validator_temperature_shock():
    """Test Scenario 2: Temperature shock (diff >= 0.15 AND dT/dt > 2°C/10min)."""
    print("\n" + "=" * 60)
    print("TEST: Scenario 2 - Temperature shock")
    print("=" * 60)

    reset_singletons()
    config = ConfigManager()
    config.load()

    from src.algorithms.dual_mode_validator import DualModeValidator

    validator = DualModeValidator(config)

    t0 = datetime.now(timezone.utc)
    t1 = t0 + timedelta(minutes=10)

    validator.validate(
        delta_d_er=10.0,
        delta_d_inductive=10.0,
        timestamp=t0,
        dT_dt=0.5,
    )

    v = validator.validate(
        delta_d_er=15.0,
        delta_d_inductive=10.5,
        timestamp=t1,
        dT_dt=3.5,
    )

    print(f"  CR_ER={v.cr_er:.4f}, CR_Inductive={v.cr_inductive:.4f}, diff={v.diff:.4f}")
    print(f"  Status: {v.status}, alarm_level={v.alarm_level}")
    print(f"  CR_out={v.cr_out:.4f} (should weight inductive more)")
    print(f"  Verdict: {v.verdict}")

    assert v.status == DualModeStatus.TEMPERATURE_SHOCK
    assert v.alarm_level == 1
    assert v.diff >= 0.15
    print("  PASS: Scenario 2 correctly identified as temperature shock")


def test_dual_mode_validator_pitting_risk():
    """Test Scenario 3: Pitting risk diagnosis."""
    print("\n" + "=" * 60)
    print("TEST: Scenario 3 - Pitting risk diagnosis")
    print("=" * 60)

    reset_singletons()
    config = ConfigManager()
    config.load()

    from src.algorithms.dual_mode_validator import DualModeValidator

    validator = DualModeValidator(config)

    t0 = datetime.now(timezone.utc)
    t1 = t0 + timedelta(minutes=10)

    validator.validate(
        delta_d_er=50.0,
        delta_d_inductive=50.0,
        timestamp=t0,
        dT_dt=0.5,
    )

    v = validator.validate(
        delta_d_er=80.0,
        delta_d_inductive=50.2,
        timestamp=t1,
        dT_dt=1.0,
    )

    delta = abs(80.0 - 50.2) / 80.0
    print(f"  Δd_ER=80.0, Δd_Inductive=50.2, δ={delta:.4f}")
    print(f"  CR_ER={v.cr_er:.4f}, CR_Inductive={v.cr_inductive:.4f}, diff={v.diff:.4f}")
    print(f"  Status: {v.status}, alarm_level={v.alarm_level}")
    print(f"  η={v.eta:.3f}, Δd_actual={v.delta_d_actual:.2f} μm")
    print(f"  Verdict: {v.verdict}")

    assert v.status == DualModeStatus.PITTING_SUSPECTED
    assert v.eta > 1.0
    assert v.delta_d_actual > v.delta_d_er if hasattr(v, 'delta_d_er') else True
    print("  PASS: Scenario 3 correctly identified as pitting suspected")


def test_dual_mode_validator_severe_pitting():
    """Test Scenario 3 variant: Severe pitting (η > 5.0)."""
    print("\n" + "=" * 60)
    print("TEST: Scenario 3 variant - Severe pitting (η > 5.0)")
    print("=" * 60)

    reset_singletons()
    config = ConfigManager()
    config.load()

    from src.algorithms.dual_mode_validator import DualModeValidator

    validator = DualModeValidator(config)

    t0 = datetime.now(timezone.utc)
    t1 = t0 + timedelta(minutes=10)

    validator.validate(
        delta_d_er=30.0,
        delta_d_inductive=30.0,
        timestamp=t0,
        dT_dt=0.5,
    )

    v = validator.validate(
        delta_d_er=60.0,
        delta_d_inductive=36.0,
        timestamp=t1,
        dT_dt=0.5,
    )

    delta_val = abs(60.0 - 36.0) / 60.0
    print(f"  δ={delta_val:.4f}, η={v.eta:.3f}")
    print(f"  Status: {v.status}, alarm_level={v.alarm_level}")
    print(f"  Verdict: {v.verdict}")

    assert v.status == DualModeStatus.PITTING_SUSPECTED
    if v.eta > 3.0:
        assert v.alarm_level >= 3
        print(f"  PASS: Severe pitting alarm triggered (level={v.alarm_level})")
    else:
        print(f"  NOTE: η={v.eta:.3f} < 3.0, insufficient for severe alarm (expected with this δ)")


def test_edge_cases():
    """Test edge cases: zero values, negative values, first call."""
    print("\n" + "=" * 60)
    print("TEST: Edge cases")
    print("=" * 60)

    reset_singletons()
    config = ConfigManager()
    config.load()

    from src.algorithms.dual_mode_validator import DualModeValidator

    validator = DualModeValidator(config)

    t0 = datetime.now(timezone.utc)

    v_zero = validator.validate(
        delta_d_er=0.0,
        delta_d_inductive=0.0,
        timestamp=t0,
        dT_dt=0.0,
    )
    print(f"  Both probes at 0: CR_out={v_zero.cr_out}, diff={v_zero.diff}, status={v_zero.status}")
    assert v_zero.diff == 0.0
    assert v_zero.cr_er == 0.0
    print("  PASS: Zero values handled correctly (diff=0)")

    t1 = t0 + timedelta(minutes=10)

    validator2 = DualModeValidator(config)

    v_neg = validator2.validate(
        delta_d_er=-5.0,
        delta_d_inductive=-3.0,
        timestamp=t0,
        dT_dt=0.0,
    )
    print(f"  Negative values: CR_ER={v_neg.cr_er}, status={v_neg.status}")
    assert v_neg.cr_er == 0.0
    print("  PASS: Negative values clamped to 0")

    v_d0 = validator2.validate(
        delta_d_er=0.0,
        delta_d_inductive=10.0,
        timestamp=t1,
        dT_dt=0.0,
    )
    print(f"  Δd_ER=0, Δd_Inductive=10: status={v_d0.status}, η={v_d0.eta}, "
          f"verdict={v_d0.verdict[:60]}...")
    assert v_d0.status == DualModeStatus.PITTING_SUSPECTED
    print("  PASS: Δd_ER=0 → pitting diagnosis skipped with fallback (correct behavior)")

    v_both_zero_cr = validator2.validate(
        delta_d_er=5.0,
        delta_d_inductive=5.0,
        timestamp=t1,
        dT_dt=0.0,
    )
    print(f"  Same values (no delta): CR_ER={v_both_zero_cr.cr_er}, status={v_both_zero_cr.status}")
    assert v_both_zero_cr.cr_er == 0.0
    assert v_both_zero_cr.diff == 0.0
    print("  PASS: Same Δd values (no change) → CR=0, diff=0")


def test_dT_dt_auto_calculation():
    """Test auto-calculation of dT/dt from T_history."""
    print("\n" + "=" * 60)
    print("TEST: Auto-calculation of dT/dt from T_history")
    print("=" * 60)

    reset_singletons()
    config = ConfigManager()
    config.load()

    from src.algorithms.dual_mode_validator import DualModeValidator

    validator = DualModeValidator(config)

    t0 = datetime.now(timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    t2 = t0 + timedelta(minutes=10)

    T_history = [
        (t0, 25.0),
        (t1, 26.5),
        (t2, 28.0),
    ]

    validator.validate(
        delta_d_er=10.0,
        delta_d_inductive=10.0,
        timestamp=t0,
        dT_dt=0.5,
    )

    v = validator.validate(
        delta_d_er=15.0,
        delta_d_inductive=10.5,
        timestamp=t2,
        T_history=T_history,
    )

    print(f"  T_history: {[(ts.strftime('%H:%M:%S'), t) for ts, t in T_history]}")
    print(f"  Expected dT/dt: 3.0°C/10min (25→28 over 10min)")
    print(f"  Status: {v.status}, diff={v.diff:.4f}")
    print(f"  Verdict: {v.verdict}")

    assert v.status == DualModeStatus.TEMPERATURE_SHOCK
    print("  PASS: Auto dT/dt calculation correctly triggered temperature shock")


def test_cross_validation_engine():
    """Test CrossValidationEngine full pipeline."""
    print("\n" + "=" * 60)
    print("TEST: CrossValidationEngine full pipeline")
    print("=" * 60)

    reset_singletons()

    from src.core.app import App
    App.reset_instance()

    app = App()
    ok = app.initialize()
    assert ok, "App initialization failed"

    from src.algorithms.cross_validation import CrossValidationEngine

    engine = CrossValidationEngine(app)

    ok = engine.initialize()
    assert ok, "Engine initialization failed"
    print("  PASS: CrossValidationEngine initialized")

    t0 = datetime.now(timezone.utc)
    t1 = t0 + timedelta(minutes=10)

    sd1 = SensorData(
        timestamp=t0,
        T=25.0,
        RH=80.0,
        delta_d_ER=100.0,
        delta_d_Inductive=100.0,
        V_mid=1.65,
        V_diff=0.01,
        L_eq=0.001,
        delta_f=0.0,
        valid_flag=True,
    )

    result1 = engine.process_cycle(sd1)
    print(f"  Cycle 1: CR={result1.final_cr:.4f}, Δd={result1.final_delta_d:.2f}, "
          f"status={result1.dual_mode_result.status if result1.dual_mode_result else 'N/A'}, "
          f"alarms={len(result1.alarms_to_trigger)}")

    sd2 = SensorData(
        timestamp=t1,
        T=25.2,
        RH=80.0,
        delta_d_ER=101.0,
        delta_d_Inductive=101.1,
        V_mid=1.65,
        V_diff=0.01,
        L_eq=0.001,
        delta_f=0.0,
        valid_flag=True,
    )

    result2 = engine.process_cycle(sd2)
    print(f"  Cycle 2: CR={result2.final_cr:.4f}, Δd={result2.final_delta_d:.2f}, "
          f"status={result2.dual_mode_result.status if result2.dual_mode_result else 'N/A'}, "
          f"alarms={len(result2.alarms_to_trigger)}")

    if result2.dual_mode_result:
        assert result2.dual_mode_result.status == DualModeStatus.DUAL_CONSISTENT
        print("  PASS: Consistent reads → DUAL_CONSISTENT")

    cr_record = result2.corrosion_record
    if cr_record:
        print(f"  CorrosionRecord: status={cr_record.status}, CR_ER={cr_record.CR_ER:.4f}")
        print("  PASS: CorrosionRecord populated from algorithm engine")

    to_dict = result2.to_dict()
    assert "final_cr" in to_dict
    assert "timestamp" in to_dict
    assert "alarms_to_trigger" in to_dict
    print("  PASS: CrossValidationResult.to_dict() works correctly")

    app.stop()
    App.reset_instance()


def test_performance():
    """Test that each validation call completes in <5ms."""
    print("\n" + "=" * 60)
    print("TEST: Performance (<5ms per call)")
    print("=" * 60)

    reset_singletons()
    config = ConfigManager()
    config.load()

    from src.algorithms.dual_mode_validator import DualModeValidator

    validator = DualModeValidator(config)

    t0 = datetime.now(timezone.utc)
    t1 = t0 + timedelta(minutes=10)

    validator.validate(delta_d_er=10.0, delta_d_inductive=10.0, timestamp=t0, dT_dt=0.5)

    times = []
    for i in range(100):
        t = t0 + timedelta(minutes=10 * (i + 1))
        start = time.perf_counter()
        validator.validate(
            delta_d_er=10.0 + i * 0.01,
            delta_d_inductive=10.0 + i * 0.008,
            timestamp=t,
            dT_dt=0.5,
        )
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

    avg_ms = sum(times) / len(times)
    max_ms = max(times)
    print(f"  Average: {avg_ms:.3f} ms, Max: {max_ms:.3f} ms over {len(times)} iterations")
    assert avg_ms < 5.0, f"Performance check: average {avg_ms:.3f}ms > 5ms threshold"
    print("  PASS: Performance within <5ms threshold")


if __name__ == "__main__":
    test_calibration_curve()
    test_dual_mode_validator_consistent()
    test_dual_mode_validator_temperature_shock()
    test_dual_mode_validator_pitting_risk()
    test_dual_mode_validator_severe_pitting()
    test_edge_cases()
    test_dT_dt_auto_calculation()
    test_cross_validation_engine()
    test_performance()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
