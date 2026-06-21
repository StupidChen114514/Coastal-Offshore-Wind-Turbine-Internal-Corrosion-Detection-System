"""
综合测试套件 – 沿海海上风电腐蚀检测系统。

包含以下测试模块：
    - test_integration.py   : 端到端集成测试（采集管线、算法流程、持久化、告警、安全、通信）
    - test_performance.py   : 性能基准测试（采集+计算、卡尔曼滤波、查询、缓冲区吞吐量）
    - test_spec_scenarios.py: spec.md 逐场景验证（需求1-12）
    - test_dual_mode.py     : 双模交叉验证专项测试
    - conftest.py           : 共享 fixtures（app、simulator、storage、engine 等）

运行方式：
    pytest tests/                       # 运行全部测试
    pytest tests/ -v                    # 详细输出
    pytest tests/test_integration.py    # 运行集成测试
    python run_tests.py                 # 使用运行器
    python run_tests.py integration     # 仅运行集成测试
"""
