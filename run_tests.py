"""
综合测试运行器 – 沿海海上风电腐蚀检测系统。

运行所有测试并输出彩色概要报告。
使用方法:
    python run_tests.py              # 运行所有测试
    python run_tests.py integration   # 仅运行集成测试
    python run_tests.py performance   # 仅运行性能测试
    python run_tests.py spec          # 仅运行规格场景测试
    python run_tests.py all           # 运行所有测试（含性能）
"""

import os
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent

TEST_MODULES = {
    "integration": "tests/test_integration.py",
    "performance": "tests/test_performance.py",
    "spec": "tests/test_spec_scenarios.py",
    "dual_mode": "tests/test_dual_mode.py",
}


def run_pytest(test_path: str, extra_args: list = None) -> tuple:
    """Run pytest and return (success, output_lines)."""
    args = [
        sys.executable,
        "-m",
        "pytest",
        test_path,
        "-v",
        "--tb=short",
        "--color=yes",
        "--no-header",
        "-p",
        "no:warnings",
    ]
    if extra_args:
        args.extend(extra_args)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        args,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode == 0, result.stdout.splitlines(), result.stderr.splitlines()


def main():
    print("=" * 70)
    print("  沿海海上风电腐蚀检测系统 – 综合测试运行器")
    print("=" * 70)
    print()

    target = sys.argv[1] if len(sys.argv) > 1 else "all"

    if target == "all":
        modules_to_run = list(TEST_MODULES.values())
    elif target in TEST_MODULES:
        modules_to_run = [TEST_MODULES[target]]
    else:
        print(f"未知目标 '{target}'。可用目标: all, {', '.join(TEST_MODULES.keys())}")
        sys.exit(1)

    all_passed = 0
    all_failed = 0
    all_error = 0
    total_start = time.time()
    failures = []
    module_results = []

    for module_path in modules_to_run:
        module_name = Path(module_path).stem
        print(f"\n{'─' * 60}")
        print(f"  运行: {module_name}")
        print(f"{'─' * 60}")

        module_start = time.time()
        success, stdout_lines, stderr_lines = run_pytest(module_path)
        module_elapsed = time.time() - module_start

        passed = 0
        failed = 0
        errors = 0

        for line in stdout_lines:
            if " passed" in line and "=" in line:
                try:
                    parts = line.split(",")
                    for part in parts:
                        part = part.strip()
                        if "passed" in part:
                            passed = int(part.split()[0])
                        elif "failed" in part:
                            failed = int(part.split()[0])
                        elif "error" in part.lower():
                            errors = int(part.split()[0])
                except (ValueError, IndexError):
                    pass

        if not success and passed == 0 and failed == 0:
            errors = 1

        status = "✓ 通过" if success else "✗ 失败"
        print(f"\n  [{status}] {module_name} ({module_elapsed:.1f}s)")
        print(f"  通过: {passed}, 失败: {failed}, 错误: {errors}")

        all_passed += passed
        all_failed += failed
        all_error += errors

        module_results.append({
            "name": module_name,
            "success": success,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "elapsed": module_elapsed,
        })

        if not success:
            failures.append(module_name)
            failed_lines = [l for l in stdout_lines if "FAILED" in l or "ERROR" in l][:5]
            if failed_lines:
                print("  失败详情:")
                for fl in failed_lines:
                    if "FAILED" in fl or "ERROR" in fl:
                        print(f"    {fl.strip()}")

    total_elapsed = time.time() - total_start
    total_tests = all_passed + all_failed + all_error
    total_success = all_passed == total_tests

    print("\n" + "=" * 70)
    print("  测试概要报告")
    print("=" * 70)
    print(f"  总耗时:        {total_elapsed:.1f}s")
    print(f"  测试模块:      {len(module_results)}")
    print(f"  总测试项:      {total_tests}")
    print(f"  ✓ 通过:       {all_passed}")
    print(f"  ✗ 失败:       {all_failed}")
    print(f"  ⚠ 错误:       {all_error}")
    print("=" * 70)

    for mr in module_results:
        symbol = "✓" if mr["success"] else "✗"
        print(f"  {symbol} {mr['name']:<30s} "
              f"通过={mr['passed']:>3d}, 失败={mr['failed']:>2d}, "
              f"错误={mr['errors']:>2d}, {mr['elapsed']:.1f}s")

    print("=" * 70)

    if total_success:
        print("  结论: 所有测试通过 ✓")
        print("=" * 70)
        return 0
    else:
        print(f"  结论: {all_failed + all_error} 项测试未通过 ✗")
        if failures:
            print(f"  失败模块: {', '.join(failures)}")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
