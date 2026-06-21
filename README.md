# 沿海海上风力发电设备内部腐蚀度检测系统

Coastal Offshore Wind Turbine Internal Corrosion Detection System

---

## 项目概述

海上风力发电设备长期服役于**高温、高湿、高盐雾**三重叠加的海洋大气腐蚀环境。本系统是一套基于双模冗余传感器阵列（电阻探针 + 电感探针）的**在线腐蚀监测与智能诊断平台**，通过四级误差补偿体系、双模交叉验证引擎与 ISO 9223/9224 国际标准评估，将传统"被动记录腐蚀量"升级为**"主动预测 + 智能诊断 + 误差免疫"**的在线监测系统。

系统涵盖传感器驱动、数据采集调度、腐蚀算法引擎、四级误差补偿、卡尔曼滤波降噪、双模点蚀诊断、多通道通信（LoRaWAN / NB-IoT / Modbus / MQTT）、三级存储架构、四级告警管理、RBAC 权限控制以及 PySide6 工业级桌面监控界面等完整功能栈。

---

## 核心功能亮点

### 1. 三维环境感知
- **温度**（Pt1000，±0.15°C）· **湿度**（SHT35，±1.5% RH）· **盐度**（QCM 石英晶体微天平，ng 级灵敏度）

### 2. 双模冗余腐蚀传感
- **叠加式双环差分电阻探针（ER）**——硬件层面消除温度共模误差，$\rho(T)$ 在比值运算中完全消去
- **涡流电感探针（LDC1614）**——28 位分辨率，本征地几乎不受温度影响，作为 ER 信号的"黄金判据"

### 3. 四级误差补偿体系
| 级别 | 方法 | 消除误差源 |
|:---|:---|:---|
| L1 | 硬件差分抵消 | 电阻率温度系数 $\rho(T)$ |
| L2 | 比值法自校准 | 恒流源 $I$ 漂移 |
| L3A | 残余温度系数多项式修正 | 制造公差 |
| L3B | 湿度门控过滤器（76% RH 临界阈值） | 虚假腐蚀伪信号 |
| L3C | 环境因子归一化 | 环境波动调制 |
| L3D | 剂量-响应函数预测 | 理论校验基准 |
| L4 | 自适应卡尔曼滤波 | 测量噪声与过程噪声 |

### 4. 双模点蚀诊断
- 通过 ER 与电感探针差异度 $\delta$ 计算点蚀因子 $\eta$，诊断非均匀腐蚀风险
- 三场景判定：双模一致 / 温度冲击 / 点蚀风险

### 5. ISO 国际标准评估
- ISO 9223 大气腐蚀性等级分类（C1~CX）
- ISO 9224 长期腐蚀预测（1/5/10/25 年）
- 实测 vs 理论交叉验证告警

### 6. 多通道通信
- **LoRaWAN**（AES-128-GCM 加密，28 字节紧凑二进制包）
- **NB-IoT MQTT**（阿里云 / 华为云 / AWS IoT，TLS 1.2）
- **Modbus TCP**（寄存器映射 + 线圈告警标志）
- 断网补传（1000 条离线缓存，恢复后告警优先）

### 7. 工业级桌面 UI
- PySide6 暗色主题，7 个功能 Tab 页
- 实时趋势图、腐蚀三曲线叠加、环境关联双Y轴、η 半圆仪表盘
- 5 个自定义控件（传感器卡片、告警徽章、仪表盘、状态灯、趋势箭头）

### 8. 四级告警管理
- 15 种告警类型，自动去重，多渠道推送
- 三级 RBAC 权限控制（Viewer / Operator / Admin）

---

## 环境要求

| 项目 | 最低要求 |
|:---|:---|
| **Python** | 3.9 或更高版本 |
| **操作系统** | Windows 10+ / Ubuntu 20.04+ / Debian 11+ |
| **内存** | ≥ 512 MB（嵌入式）/ ≥ 2 GB（桌面） |
| **磁盘** | ≥ 500 MB（1 年数据存储） |
| **串口** | ≥ 1 个可用 UART/RS-485 端口（硬件部署） |

---

## 技术栈

| 层级 | 技术选型 | 用途 |
|:---|:---|:---|
| **编程语言** | Python 3.9+ | 核心业务逻辑 |
| **UI 框架** | PySide6 6.5+ | 工业级桌面应用界面 |
| **科学计算** | NumPy / SciPy | 矩阵运算、滤波算法、多项式拟合 |
| **实时图表** | pyqtgraph | 高性能实时数据流渲染 |
| **串口通信** | PySerial | 传感器硬件通信 |
| **MQTT 通信** | paho-mqtt | IoT 云平台消息协议 |
| **加密安全** | cryptography | AES-128-GCM、PBKDF2-SHA256 |
| **配置验证** | jsonschema | JSON Schema 校验 |
| **数据库** | SQLite 3（内置） | 嵌入式零配置存储 |
| **测试框架** | pytest | 单元/集成/性能测试 |

---

## 安装指南

### 1. 克隆项目

```bash
git clone https://github.com/StupidChen114514/Coastal-Offshore-Wind-Turbine-Internal-Corrosion-Detection-System.git
cd Coastal-Offshore-Wind-Turbine-Internal-Corrosion-Detection-System
```

### 2. 创建虚拟环境（推荐）

```bash
python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 安装项目包（可选）

```bash
pip install -e .
```

安装后可通过 CLI 命令启动：

```bash
corrosion-detector
```

---

## 使用说明

### 基础启动

```bash
# 桌面模式（含完整 UI）
python main.py

# 指定配置目录
python main.py --config-dir ./my_config

# 调试模式
python main.py --log-level DEBUG

# 查看版本
python main.py --version
```

### 运行测试

```bash
# 运行所有测试
python run_tests.py

# 分类运行
python run_tests.py integration    # 集成测试（82 项）
python run_tests.py performance    # 性能基准测试（15 项）
python run_tests.py spec           # 规格场景验证（35 项）

# 或直接使用 pytest
pytest tests/ -v
```

### UI 界面导航

| Tab | 名称 | 功能 |
|:---|:---|:---|
| Tab 1 | 实时监测 | Δd_ER/Δd_Inductive 趋势图，1h~1y 时间切换 |
| Tab 2 | 腐蚀详情 | Δd_raw/corrected/filtered 三曲线叠加 |
| Tab 3 | 环境关联 | T+RH 双Y轴，76% 临界线，Cl⁻ 柱状图 |
| Tab 4 | 风险评估 | C1~CX 等级卡片，η 半圆仪表盘 |
| Tab 5 | 告警管理 | 告警全生命周期（确认/解决/详情） |
| Tab 6 | 数据查询 | 时间范围过滤、分页表格、CSV/JSON 导出 |
| Tab 7 | 系统设置 | 全参数配置（仅 Admin 权限） |

### 配置文件

编辑 `config/default_config.json` 可调整 7 大配置区块：

- **sensor** — 初始厚度 d₀、电极面积、基频 f₀
- **sampling** — 常规采样周期（默认 10min）、应急采样周期（默认 1min）
- **algorithm** — RH 临界阈值（76%）、温度/盐度补偿系数、卡尔曼滤波参数
- **alarm** — 四级腐蚀速率告警阈值
- **comms** — LoRa 频点、NB-IoT APN、云端 MQTT 地址
- **storage** — 数据库路径、数据保留天数
- **logging** — 日志级别、目录、文件轮转大小

---

## 项目结构

```
Coastal-Offshore-Wind-Turbine-Internal-Corrosion-Detection-System/
├── main.py                    # 应用程序入口
├── setup.py                   # Python 包安装配置
├── requirements.txt           # 依赖清单
├── run_tests.py               # 测试运行器
│
├── config/
│   ├── default_config.json    # 完整默认配置（7 大区块）
│   └── users.json             # 用户与权限配置
│
├── docs/
│   ├── 项目技术汇报文档.md     # 技术汇报文档
│   └── 项目技术汇报发言稿.md   # 技术汇报发言稿
│
├── portable/
│   └── index.html             # 便携式 Web 监控页面
│
├── src/
│   ├── core/                  # 核心框架层
│   │   ├── app.py             #   主应用类（单例/生命周期/信号槽）
│   │   ├── config_manager.py  #   JSON 配置管理+范围验证
│   │   ├── logger.py          #   线程安全日志（双输出+轮转）
│   │   ├── data_models.py     #   6 个核心 dataclass + 4 个枚举
│   │   ├── alarm_manager.py   #   四级告警全生命周期管理
│   │   ├── alarm_definitions.py  # 15 种告警类型定义
│   │   ├── notification_service.py  # 多渠道通知推送
│   │   ├── auth_manager.py    #   RBAC 三级权限+登录锁定
│   │   ├── audit_logger.py    #   审计日志（不可删除）
│   │   ├── crypto_utils.py    #   CRC-16/SHA-256/AES-128/PBKDF2
│   │   ├── data_integrity.py  #   数据完整性签名/验签
│   │   ├── diagnostics.py     #   POST+30天自诊断+看门狗
│   │   ├── watchdog.py        #   30秒超时看门狗定时器
│   │   └── health_monitor.py  #   系统健康持续监控
│   │
│   ├── sensors/               # 传感器采集层
│   │   ├── sensor_manager.py  #   总控（串口/模拟双模式）
│   │   ├── pt1000_driver.py   #   Pt1000 CVD 方程温度解算
│   │   ├── sht35_driver.py    #   SHT35 湿度+CRC-8 校验
│   │   ├── qcm_driver.py      #   QCM Sauerbrey 盐度计算
│   │   ├── er_probe_driver.py #   ER 双环差分电阻探针
│   │   ├── inductive_driver.py  # LDC1614 涡流电感探针
│   │   ├── acquisition_scheduler.py  # 10min/1min 双模式采集调度
│   │   └── sensor_simulator.py  # 昼夜周期传感器模拟器
│   │
│   ├── algorithms/            # 算法引擎层
│   │   ├── algorithm_engine.py  # 四级误差补偿主引擎
│   │   ├── kalman_filter.py   #   2状态自适应卡尔曼滤波器
│   │   ├── dose_response.py   #   ISO 9224 剂量-响应函数
│   │   ├── tow_calculator.py  #   ISO 9223 TOW 湿润时间统计
│   │   ├── iso_9223.py        #   ISO 9223 腐蚀性等级评估
│   │   ├── iso_assessment.py  #   ISO 评估编排引擎
│   │   ├── dual_mode_validator.py  # 双模交叉验证+三场景判定
│   │   ├── calibration_curve.py  # η=f(δ) 标定曲线管理
│   │   └── cross_validation.py  # 交叉验证全流程引擎
│   │
│   ├── storage/               # 数据存储层
│   │   └── storage_manager.py #   三级存储+CRUD+CSV/JSON导出
│   │
│   ├── comms/                 # 通信层
│   │   ├── comm_manager.py    #   通信总控管理器
│   │   ├── data_packet.py     #   28字节紧凑二进制/JSON双格式
│   │   ├── lorawan_channel.py #   LoRaWAN 通道（AES-128-GCM）
│   │   ├── nbiot_channel.py   #   NB-IoT MQTT 通道
│   │   ├── modbus_server.py   #   Modbus TCP 从站服务器
│   │   ├── mqtt_client.py     #   三平台 MQTT 客户端
│   │   └── backlog_manager.py #   断网补传管理（1000条缓存）
│   │
│   └── ui/                    # 用户界面层
│       ├── main_window.py     #   7-Tab PySide6 主窗口
│       ├── styles.py          #   QSS 暗色工业监控主题
│       └── widgets/           #   自定义控件库
│           ├── sensor_display_widget.py  # 传感器数值卡片
│           ├── alarm_badge.py            # 告警彩色徽章
│           ├── eta_gauge_widget.py       # η 半圆仪表盘
│           ├── status_indicator.py       # 连接状态灯
│           └── trend_arrow.py            # 趋势箭头
│
└── tests/                     # 测试层
    ├── conftest.py            #   pytest fixtures
    ├── test_integration.py    #   82 项集成测试
    ├── test_performance.py    #   15 项性能基准测试
    ├── test_spec_scenarios.py #   35 项规格场景验证
    └── test_dual_mode.py      #   双模验证专项测试
```

---

## 架构概览

```
┌──────────────────────────────────────────────────────┐
│                    云端平台 (Cloud)                    │
│  阿里云 IoT / 华为云 IoT / AWS IoT Core / SCADA       │
│  MQTT │ HTTP REST API │ Modbus TCP                   │
└───────────────────┬──────────────────────────────────┘
                    │  NB-IoT / LoRaWAN / Ethernet
┌───────────────────▼──────────────────────────────────┐
│                边缘计算层 (Edge Gateway)               │
│                                                       │
│  ┌─────────┐  ┌──────────────┐  ┌──────────┐        │
│  │   UI    │  │  Algorithms  │  │  Comms   │        │
│  │ PySide6 │→│  4-Level     │→│ LoRa/NB  │        │
│  │ 7-Tab   │  │  Pipeline    │  │ Modbus   │        │
│  │Dashboard│  │  KF+CrossVal │  │ MQTT     │        │
│  └─────────┘  └──────────────┘  └──────────┘        │
│                          ▲                            │
│  ┌───────────────────────┴────────────────────────┐  │
│  │              Core Framework                     │  │
│  │  App │ Config │ Logger │ Alarm │ Auth │ Diag  │  │
│  └────────────────────────────────────────────────┘  │
│                          ▲                            │
│         UART / RS-485 Serial Bus                      │
└──────────┬───────────────────────────────────────────┘
           │
┌──────────▼───────────────────────────────────────────┐
│               传感器层 (MCU MSP430FR)                  │
│                                                       │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────────┐ │
│  │ Pt1000 │  │ SHT35  │  │  QCM   │  │ ER+Induc   │ │
│  │  温度T │  │ 湿度RH │  │盐沉积Δm│  │Δd双模冗余  │ │
│  └────────┘  └────────┘  └────────┘  └────────────┘ │
└──────────────────────────────────────────────────────┘
```

---

## 生产部署建议

1. 使用 `systemd`（Linux）或 Windows 服务管理器将 `main.py` 注册为开机自启服务
2. 配置 `default_config.json` 的 `storage.data_retention_days` 为 365
3. 配置 `comms.cloud` 连接实际云端 MQTT 服务器
4. 确保日志目录 `logs/` 和数据库目录 `data/` 有写入权限
5. 建议配置系统级看门狗（硬件看门狗 + systemd WatchdogSec）

---

## 遵循的国际标准

| 标准 | 说明 |
|:---|:---|
| **ISO 9223:2012** | 大气环境腐蚀性分类、判定与估算 |
| **ISO 9224:2012** | 大气腐蚀性等级指导值（长期预测） |
| **ISO 9225:2012** | 影响大气腐蚀性的环境参数测量 |
| **ISO 12944** | 防护涂料系统腐蚀防护 |
| **NACE SP0775-2023** | 腐蚀试样的制备、安装、分析和解释 |
| **IEC 61400-1/3** | 风力发电机组设计与测试 |
| **GB/T 33630** | 海上风机防腐技术规范 |
| **GB/T 20319** | 海上风力发电机组 |

---

> **版本**：v1.0.0 | **许可证**：Proprietary
