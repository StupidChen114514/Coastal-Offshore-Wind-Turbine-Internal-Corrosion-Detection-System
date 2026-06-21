# 沿海海上风力发电设备内部腐蚀度检测系统

## 项目总览与技术文档

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 技术栈选型](#2-技术栈选型)
- [3. 系统架构](#3-系统架构)
- [4. 功能模块详细说明](#4-功能模块详细说明)
- [5. 数据流与核心算法](#5-数据流与核心算法)
- [6. 项目部署流程](#6-项目部署流程)
- [7. 开发规范](#7-开发规范)
- [8. 未来迭代计划](#8-未来迭代计划)
- [附录：项目文件清单](#附录项目文件清单)

---

## 1. 项目概述

### 1.1 项目名称

**沿海海上风力发电设备内部腐蚀度检测系统**（Coastal Offshore Wind Turbine Internal Corrosion Detection System）

### 1.2 开发背景

海上风力发电设备长期服役于**高温、高湿、高盐雾**三重叠加的海洋大气腐蚀环境。南海某海上风电项目全年连续监测数据显示：项目地全年平均气温 **23.3°C**，平均相对湿度高达 **84%**。机舱、控制柜等电气设备若内部湿度无法控制在 60% 以下，电气元件凝露腐蚀将不可避免。

传统巡检方式存在四大致命缺陷：

| 缺陷类型 | 具体表现 | 后果 |
|:---|:---|:---|
| **时效性不足** | 年度巡检无法捕捉腐蚀动态变化 | 发现时可能已严重减薄 |
| **分辨率不足** | 超声波测厚精度通常仅 0.1mm 级 | 无法检测早期腐蚀（μm 级） |
| **温度干扰严重** | 电阻探针受温度波动影响，10°C 温差可产生约 3.9% 电阻伪信号 | 虚假腐蚀报警或漏报 |
| **点蚀无法识别** | 均匀腐蚀假设下严重低估局部穿孔风险 | 突发性结构失效 |

**经济损失量化**：单台风机全生命周期（25 年）腐蚀监测总成本约 30~60 万元，仅相当于一次重大事故维修成本的 5%~10%。

### 1.3 核心价值

本系统将传统"被动记录腐蚀量"升级为**"主动预测 + 智能诊断 + 误差免疫"**的在线监测系统，从根本上防止因误报或漏报造成的重大经济损失。

### 1.4 目标用户

| 用户角色 | 职责 | 系统权限 |
|:---|:---|:---|
| **观察者（Viewer）** | 运维工程师日常巡检 | 查看实时数据、历史趋势 |
| **操作员（Operator）** | 现场运维主管 | 以上 + 告警确认/解决 + 数据导出 |
| **管理员（Admin）** | 系统管理员/技术专家 | 以上 + 系统配置 + 标定曲线导入 + 固件升级 |

### 1.5 遵循的国际标准

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

## 2. 技术栈选型

### 2.1 总体技术方案

系统采用**分层架构**设计，核心业务逻辑使用 **Python 3.9+** 实现，桌面 UI 使用 **PySide6 (Qt 6)** 框架，嵌入式端通过 **UART/RS-485** 串行总线与边缘计算设备通信。

### 2.2 开发语言与框架

| 层级 | 技术选型 | 选型理由 |
|:---|:---|:---|
| **编程语言** | Python 3.9+ | 科学计算生态丰富，跨平台支持好，开发效率高 |
| **UI 框架** | PySide6 6.5+ | Qt 6 官方 Python 绑定，工业级桌面应用首选 |
| **科学计算** | NumPy 1.21+ / SciPy 1.7+ | 矩阵运算、滤波算法、多项式拟合 |
| **实时图表** | pyqtgraph 0.13+ | 专为实时数据流设计，渲染性能优于 Matplotlib |
| **串口通信** | PySerial 3.5+ | 成熟稳定的跨平台串口库 |
| **MQTT 通信** | paho-mqtt 1.6+ | IoT 领域标准 MQTT 客户端 |
| **加密安全** | cryptography 39.0+ | AES-128-GCM、PBKDF2-HMAC-SHA256 |
| **配置验证** | jsonschema 4.17+ | JSON 配置文件 Schema 校验 |
| **数据库** | SQLite 3（内置） | 嵌入式数据库，无需独立服务，零配置 |

### 2.3 完整依赖清单

```
PySide6>=6.5.0        # Qt 6 桌面 UI 框架
numpy>=1.21.0         # 数值计算与矩阵运算
scipy>=1.7.0          # 科学计算（卡尔曼滤波、插值）
pyserial>=3.5         # 串行通信
pyqtgraph>=0.13.0     # 实时高性能图表
paho-mqtt>=1.6.0      # MQTT IoT 协议客户端
cryptography>=39.0.0  # AES、PBKDF2 等加密算法
jsonschema>=4.17.0    # 配置文件 Schema 验证
```

### 2.4 硬件平台

| 部署环境 | 硬件平台 | 操作系统 |
|:---|:---|:---|
| **嵌入式 MCU** | MSP430FR 系列 | 裸机 / FreeRTOS（固件 < 128KB） |
| **边缘网关/工控机** | ARM Cortex-A / x86 | Linux Ubuntu 20.04+ / Debian 11+ / Windows 10+ |
| **云端平台** | 阿里云 IoT / 华为云 IoT / AWS IoT Core | — |

---

## 3. 系统架构

### 3.1 架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                        云端平台 (Cloud)                           │
│  阿里云 IoT / 华为云 IoT / AWS IoT Core / SCADA                   │
│  MQTT │ HTTP REST API │ Modbus TCP                               │
└───────────────┬──────────────────────────────────────────────────┘
                │  NB-IoT / LoRaWAN / Ethernet
┌───────────────▼──────────────────────────────────────────────────┐
│                    边缘计算层 (Edge Gateway)                       │
│                                                                   │
│  ┌─────────┐  ┌──────────────┐  ┌──────────┐  ┌──────────────┐  │
│  │   UI    │  │  Algorithms  │  │  Comms   │  │   Storage    │  │
│  │PySide6  │→│  4-Level     │→│ LoRa/NB  │→│  Ring Buffer │  │
│  │7-Tab    │  │  Pipeline    │  │ Modbus   │  │  SQLite      │  │
│  │Dashboard│  │  KF+CrossVal │  │ MQTT     │  │  Cloud Sync  │  │
│  └─────────┘  └──────────────┘  └──────────┘  └──────────────┘  │
│                          ▲                                        │
│  ┌───────────────────────┴────────────────────────────────────┐  │
│  │                    Core Framework                           │  │
│  │  App (Singleton) │ Config │ Logger │ Alarm │ Auth │ Diag  │  │
│  └────────────────────────────────────────────────────────────┘  │
│                          ▲                                        │
│         UART / RS-485 Serial Bus                                  │
└──────────┬───────────────────────────────────────────────────────┘
           │
┌──────────▼───────────────────────────────────────────────────────┐
│                    传感器层 (MCU MSP430FR)                         │
│                                                                   │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌──────────┐  ┌─────────┐ │
│  │ Pt1000 │  │ SHT35  │  │  QCM   │  │ ER Probe │  │LDC1614  │ │
│  │ 温度T  │  │ 湿度RH │  │盐沉积Δm│  │ Δd_ER    │  │Δd_Induc │ │
│  │±0.15°C│  │±1.5%RH│  │  ng级  │  │ 双环差分 │  │28bit    │ │
│  └────────┘  └────────┘  └────────┘  └──────────┘  └─────────┘ │
│                                                                   │
│  工作模式：休眠(<2µA) → RTC唤醒 → 采集(100ms) → 发送(<50ms)       │
│  平均功耗 < 50µW，19Ah 电池续航 > 5 年                             │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 模块依赖关系

```
                         ┌──────────────┐
                         │   main.py    │ (入口)
                         └──────┬───────┘
                                │
                    ┌───────────▼───────────┐
                    │      App (核心)        │
                    │  单例 · 生命周期 · 信号  │
                    └───┬───┬───┬───┬───┬───┘
                        │   │   │   │   │
        ┌───────────────┘   │   │   │   └──────────────┐
        ▼                   │   │   │                  ▼
  ┌───────────┐             │   │   │          ┌──────────────┐
  │  Sensors  │◄───UART─────┘   │   │          │   Storage    │
  │ 传感器驱动  │                 │   │          │  三级存储     │
  └─────┬─────┘                 │   │          └──────┬───────┘
        │                       │   │                 │
        ▼                       │   │                 │
  ┌───────────┐    ┌────────────▼───▼──┐    ┌───────▼───────┐
  │Algorithms │    │      Core         │    │    Comms      │
  │四级补偿    │    │ 配置·日志·告警·安全 │    │  通信管理     │
  │卡尔曼滤波  │    │ 诊断·认证·审计     │    │  LoRa/NB/MQTT │
  │双模验证    │    └──────────────────┘    └───────┬───────┘
  │ISO评估     │                                    │
  └─────┬─────┘                                    │
        │                                          │
        └──────────────┬───────────────────────────┘
                       │
                       ▼
                ┌──────────────┐
                │      UI      │
                │  PySide6 界面 │
                │  7-Tab + 图表 │
                └──────────────┘
```

### 3.3 目录结构

```
sensor_project/
├── main.py                          # 应用程序入口
├── setup.py                         # Python 包安装配置
├── requirements.txt                 # 依赖清单
├── run_tests.py                     # 测试运行器
├── PROJECT_OVERVIEW.md              # 本文档
│
├── config/
│   └── default_config.json          # 完整默认配置（292行）
│
├── src/
│   ├── __init__.py
│   │
│   ├── core/                        # 核心框架层（~2500行）
│   │   ├── app.py                   # 主应用类（单例/生命周期/信号槽）
│   │   ├── config_manager.py        # JSON 配置管理+范围验证
│   │   ├── logger.py                # 线程安全日志（双输出+轮转）
│   │   ├── data_models.py           # 6 个 dataclass + 4 个枚举
│   │   ├── alarm_manager.py         # 告警生命周期管理
│   │   ├── alarm_definitions.py     # 15 种告警类型定义
│   │   ├── notification_service.py  # 多渠道通知推送
│   │   ├── auth_manager.py          # RBAC 三级权限+登录锁定
│   │   ├── audit_logger.py          # 审计日志（不可删除）
│   │   ├── crypto_utils.py          # CRC-16/SHA-256/AES-128/PBKDF2
│   │   ├── data_integrity.py        # 数据完整性签名/验签
│   │   ├── diagnostics.py           # POST+30天自诊断+看门狗
│   │   ├── watchdog.py              # 30秒超时看门狗定时器
│   │   └── health_monitor.py        # 系统健康持续监控
│   │
│   ├── sensors/                     # 传感器采集层（~2000行）
│   │   ├── sensor_manager.py        # 传感器总控（串口/模拟双模式）
│   │   ├── pt1000_driver.py         # Pt1000 CVD 方程温度解算
│   │   ├── sht35_driver.py          # SHT35 湿度+CRC-8 校验
│   │   ├── qcm_driver.py            # QCM Sauerbrey 方程盐度计算
│   │   ├── er_probe_driver.py       # ER 双环差分电阻探针
│   │   ├── inductive_driver.py      # LDC1614 涡流电感探针
│   │   ├── acquisition_scheduler.py # 10min/1min 双模式采集调度
│   │   └── sensor_simulator.py      # 传感器模拟器（昼夜周期模型）
│   │
│   ├── algorithms/                  # 算法引擎层（~2500行）
│   │   ├── algorithm_engine.py      # 四级误差补偿主引擎
│   │   ├── kalman_filter.py         # 2状态自适应卡尔曼滤波器
│   │   ├── dose_response.py         # ISO 9224 剂量-响应函数
│   │   ├── tow_calculator.py        # ISO 9223 TOW 湿润时间统计
│   │   ├── iso_9223.py              # ISO 9223 腐蚀性等级评估器
│   │   ├── iso_assessment.py        # ISO 评估编排引擎
│   │   ├── dual_mode_validator.py   # 双模交叉验证+三场景判定
│   │   ├── calibration_curve.py     # η = f(δ) 标定曲线管理
│   │   └── cross_validation.py      # 交叉验证全流程引擎
│   │
│   ├── storage/                     # 数据存储层（~800行）
│   │   └── storage_manager.py       # 三级存储+CRUD+CSV/JSON导出
│   │
│   ├── comms/                       # 通信层（~1800行）
│   │   ├── comm_manager.py          # 通信总控管理器
│   │   ├── data_packet.py           # 28字节紧凑二进制/JSON双格式
│   │   ├── lorawan_channel.py       # LoRaWAN 通道（AES-128-GCM）
│   │   ├── nbiot_channel.py         # NB-IoT MQTT 通道
│   │   ├── modbus_server.py         # Modbus TCP 从站服务器
│   │   ├── mqtt_client.py           # 三平台 MQTT 客户端
│   │   └── backlog_manager.py       # 断网补传管理（1000条缓存）
│   │
│   └── ui/                          # 用户界面层（~2500行）
│       ├── main_window.py           # 7-Tab 主窗口（1686行）
│       ├── styles.py                # QSS 暗色工业监控主题
│       └── widgets/                 # 自定义控件库
│           ├── sensor_display_widget.py  # 传感器数值卡片
│           ├── alarm_badge.py            # 告警彩色徽章
│           ├── eta_gauge_widget.py       # η 因子半圆仪表盘
│           ├── status_indicator.py       # 连接状态灯
│           └── trend_arrow.py            # 趋势箭头 ▲▼─
│
└── tests/                           # 测试层（~2000行）
    ├── test_integration.py          # 82 项集成测试（8 个测试类）
    ├── test_performance.py          # 15 项性能基准测试
    └── test_spec_scenarios.py       # 35 项规格场景验证
```

---

## 4. 功能模块详细说明

### 4.1 核心框架层（Core）

#### 4.1.1 App 主应用类

**文件位置**：[src/core/app.py](file:///e:/Trae CN Projects/sensor_project/src/core/app.py)

**功能描述**：系统总控中心，负责管理完整的应用生命周期（初始化 → 运行 → 停止 → 重启），并提供模块间通信的发布-订阅信号机制。

**实现方式**：
- 采用**线程安全双重检查锁定单例模式**（Double-Checked Locking Singleton）
- 内建 **Signal/Slot 发布-订阅系统**，支持 7 个系统级信号
- 状态机管理 6 个运行状态：UNINITIALIZED → INITIALIZED → RUNNING → STOPPING → STOPPED → ERROR

**核心代码结构**：
```python
class App:
    _instance: Optional["App"] = None      # 单例
    _lock: threading.Lock = threading.Lock()
    _state: AppState                       # 生命周期状态
    _signals: Dict[str, Signal]            # 7 个系统信号

    def initialize(self) -> bool:          # POST自检 → 加载配置 → 初始化模块
    def start(self) -> bool:               # 启动看门狗 → 周期诊断
    def stop(self) -> bool:                # 清空信号 → 清理模块 → 关闭日志
    def run(self) -> None:                 # 主循环（500ms喂狗）
    def connect(signal_name, slot):        # 模块间松耦合通信
```

**7 个系统信号**：

| 信号名 | 触发时机 | 数据载荷 |
|:---|:---|:---|
| `sensor_data_received` | 传感器数据到达 | SensorData 对象 |
| `corrosion_record_computed` | 算法处理完成 | CorrosionRecord 对象 |
| `alarm_raised` | 告警触发 | AlarmRecord 对象 |
| `alarm_resolved` | 告警解除 | AlarmRecord 对象 |
| `config_changed` | 配置修改 | (key, old_value, new_value) |
| `system_error` | 系统错误 | (error_type, message) |
| `state_changed` | 状态变更 | AppState 枚举值 |

---

#### 4.1.2 数据模型

**文件位置**：[src/core/data_models.py](file:///e:/Trae CN Projects/sensor_project/src/core/data_models.py)

**功能描述**：定义系统中所有核心数据结构的 Python dataclass 和枚举类型。

**6 个核心 dataclass**：

| 数据类 | 核心字段 | 用途 |
|:---|:---|:---|
| `SensorData` | timestamp, T, RH, Cl_deposition, delta_d_ER, delta_d_Inductive, V_mid, V_diff, L_eq, delta_f, valid_flag | 原始传感器读数 |
| `CorrosionRecord` | delta_d_raw, delta_d_corrected, delta_d_filtered, CR_ER, CR_Inductive, CR_out, eta, status | 处理后腐蚀数据 |
| `AlarmRecord` | alarm_id(UUID), level(1-4), alarm_type, details, sensor_id, status, operator, resolved_time | 告警记录 |
| `DualModeResult` | cr_out, eta, delta_d_actual, status, alarm_level, verdict, diff | 双模验证结果 |
| `CrossValidationResult` | corrosion_record, dual_mode_result, alarms_to_trigger, final_cr, final_delta_d | 交叉验证结果 |
| `AuditLogEntry` | operator, operation_type, details, result | 审计日志 |

**4 个枚举类型**：`AlarmLevel`(1-4)、`AlarmStatus`(ACTIVE/ACKNOWLEDGED/RESOLVED/AUTO_RESOLVED)、`AlarmType`(19种告警)、`OperationType`(9种操作)。

---

#### 4.1.3 配置管理

**文件位置**：[src/core/config_manager.py](file:///e:/Trae CN Projects/sensor_project/src/core/config_manager.py)

**功能描述**：JSON 配置文件读写 + 参数范围验证 + 默认值回退 + 版本追踪。

**默认配置**：[config/default_config.json](file:///e:/Trae CN Projects/sensor_project/config/default_config.json)（292行，7大配置区块）

| 配置区块 | 关键参数 | 默认值 |
|:---|:---|:---|
| **sensor** | d₀ 初始厚度、电极面积 A、基频 f₀ | 100μm / 1cm² / 10MHz |
| **sampling** | normal_period、emergency_period/duration | 600s / 60s / 1800s |
| **algorithm** | RH_crit、α_res/β_res、k_S、TOW_ref、CR权重 | 76% / 0/0 / 0.01 / 4000h |
| **alarm** | 四级阈值 (mm/yr) | 0.01 / 0.05 / 0.10 / 0.20 |
| **comms** | LoRa频点/NB-IoT APN/云端地址 | 433MHz / ctnet |
| **storage** | 数据库路径、保留天数 | data/sensor_data.db / 365天 |
| **logging** | 级别、目录、最大文件 | INFO / logs / 10MB |

---

#### 4.1.4 告警管理系统

**文件位置**：[src/core/alarm_manager.py](file:///e:/Trae CN Projects/sensor_project/src/core/alarm_manager.py)

**功能描述**：四级告警全生命周期管理，支持触发、去重、确认、解决、自动恢复、多渠道推送。

**告警状态机**：
```
           raise_alarm()         acknowledge()
              │                      │
         ┌────▼─────┐          ┌─────▼──────────┐
         │  ACTIVE   │─────────→│  ACKNOWLEDGED   │
         └────┬─────┘          └─────┬───────────┘
              │                      │
              │  check_auto_resolve() │ resolve()
              │         │            │
         ┌────▼─────────▼──┐  ┌─────▼──────┐
         │  AUTO_RESOLVED   │  │  RESOLVED  │
         └──────────────────┘  └────────────┘
```

**四级告警体系**（15种告警类型）：

| 等级 | 名称 | 示例告警类型 |
|:---|:---|:---|
| **Level 1** | 信息通知 | 环境剧烈变化、应急模式切换 |
| **Level 2** | 一般告警 | 传感器通信故障、恒流源异常、温度冲击 |
| **Level 3** | 高级告警 | 腐蚀异常加速(r_meas/r_pred>2.0)、点蚀风险(η>3.0)、参考环漂移 |
| **Level 4** | 紧急告警 | 严重点蚀穿孔(η>5.0)、双传感器同时故障、腐蚀超80%阈值 |

**关键技术点**：
- 10 分钟内同类型同传感器告警自动去重
- Level ≥ 2 自动推送至 LoRa/MQTT/Modbus 等多通道
- Level 4 紧急告警享有最高发送优先级
- 异步通知线程不阻塞主流程

---

#### 4.1.5 安全与认证

**文件位置**：[src/core/auth_manager.py](file:///e:/Trae CN Projects/sensor_project/src/core/auth_manager.py)、[src/core/crypto_utils.py](file:///e:/Trae CN Projects/sensor_project/src/core/crypto_utils.py)

**功能描述**：三级 RBAC 权限控制 + 密码安全 + 数据完整性 + 审计日志。

**安全机制一览**：

| 机制 | 实现方式 | 算法/标准 |
|:---|:---|:---|
| **密码哈希** | PBKDF2-HMAC-SHA256，100,000 次迭代 | 密码**绝不**明文存储 |
| **账户锁定** | 5 次失败 → 30 分钟 IP/用户名锁定 | 防暴力破解 |
| **三级权限** | Viewer / Operator / Admin RBAC | 10 种权限细粒度控制 |
| **数据校验** | CRC-16-CCITT（多项式 0x1021） | 传感器数据完整性 |
| **配置保护** | SHA-256 哈希 | 配置防篡改 |
| **LoRa 加密** | AES-128-GCM（认证加密） | nonce+密文+认证标签 |
| **传输加密** | TLS 1.2 | NB-IoT / 以太网上行 |
| **审计日志** | 追加写入，不可删除 | 全操作可追溯 |

---

#### 4.1.6 系统自诊断

**文件位置**：[src/core/diagnostics.py](file:///e:/Trae CN Projects/sensor_project/src/core/diagnostics.py)

**功能描述**：开机自检(POST)、30天定期诊断、采集周期检测、看门狗自动恢复。

**POST 五步自检流程**：

```
1. RAM自检 ──→ 写入0xAA/0x55棋盘模式 → 回读验证
2. 存储检测 ──→ 数据库可读写 + 磁盘剩余 > 100MB
3. 总线扫描 ──→ I²C/SPI 通信链路检测
4. RTC验证  ──→ 系统时钟非1970年默认值
5. 恒流源   ──→ V_ref 在标称 2.5V ±5% 范围内
```

关键自检项失败 → 阻止进入 RUNNING 状态 → 触发 Level 3 告警。

---

### 4.2 传感器采集层（Sensors）

#### 4.2.1 Pt1000 温度传感器驱动

**文件位置**：[src/sensors/pt1000_driver.py](file:///e:/Trae CN Projects/sensor_project/src/sensors/pt1000_driver.py)

**功能描述**：基于 Callendar-Van Dusen 方程的 Pt1000 铂电阻温度传感器驱动。

**核心算法——CVD 方程**：
```
R_T = R₀ × (1 + α × T + β × T²)

其中：R₀ = 1000Ω, α = 3.9083×10⁻³ /℃, β = -5.775×10⁻⁷ /℃²

正向：T → R_T（给定温度计算电阻值）
反向：R_T → T（二次求根公式 + Newton-Raphson 迭代）
```

**关键代码片段**：
```python
class Pt1000Driver:
    R_0: float = 1000.0
    alpha: float = 3.9083e-3    # 线性温度系数
    beta: float = -5.775e-7     # 二次项温度系数（负值=曲线微弯）

    @classmethod
    def temperature_from_resistance(cls, R_T: float) -> float:
        # 对于 T ≥ 0°C：解二次方程 a·T² + b·T + c = 0
        # 其中 a=β, b=α, c=1 - R_T/R₀
        # T = [-α + sqrt(α² - 4β(1-R_T/R₀))] / (2β)
```

**精度**：±0.15°C（Class A），长期漂移 < 0.04%/年。

**物理原理**：环境温度 T↑ → 铂晶格振动加剧 → 自由电子散射概率增大 → 电阻率 ρ↑ → 电阻值 R_T↑。

---

#### 4.2.2 SHT35 湿度传感器驱动

**文件位置**：[src/sensors/sht35_driver.py](file:///e:/Trae CN Projects/sensor_project/src/sensors/sht35_driver.py)

**核心算法——CRC-8 数据校验**：
```
多项式：0x31 (x⁸ + x⁵ + x⁴ + 1)
初始值：0xFF
校验范围：6 字节 I²C 数据包
```

**物理原理**：感湿膜（聚酰亚胺高分子）吸水后介电常数 εᵣ 增大（水的 εᵣ≈80 >> 干膜 εᵣ≈3~4）→ 电容 C 近似线性增大 → 内部振荡频率变化 → 数字输出 RH 值。

**精度**：±1.5% RH（20%~80% RH 范围），典型功耗仅 2µA @1Hz。

---

#### 4.2.3 QCM 盐度传感器驱动

**文件位置**：[src/sensors/qcm_driver.py](file:///e:/Trae CN Projects/sensor_project/src/sensors/qcm_driver.py)

**核心算法——Sauerbrey 方程**：
```
Δf = -(2 × f₀²) / (A × √(ρ_q × μ_q)) × Δm

代入 10MHz 晶振参数：
Δf ≈ -2.26×10⁸ × Δm/A

灵敏度：电极面积 1cm² 时，每沉积 1ng 盐质量，频率下降约 2.26Hz
```

**物理原理**：盐颗粒沉积↑ → 晶体表面质量 Δm↑ → 谐振频率 f↓ → 频率计读数 Δf → 代入 Sauerbrey 方程 → 求 Δm → 对时间求导得氯离子沉积率 [Cl⁻]。

---

#### 4.2.4 电阻探针(ER)驱动——叠加式双环差分结构

**文件位置**：[src/sensors/er_probe_driver.py](file:///e:/Trae CN Projects/sensor_project/src/sensors/er_probe_driver.py)

**核心算法——硬件差分补偿**：
```
目标：消除电阻率 ρ(T) 的温度依赖性

传感环 R_s(T) = ρ(T) × L / [w × (d₀ - Δd)]
参考环 R_r(T) = ρ(T) × L / [w × d₀]     ← Parylene C 涂层隔离

R_s/R_r = d₀ / (d₀ - Δd)                 ← ρ(T)、L、w 全部消去！

Δd = d₀ × (1 - R_r/R_s)
```

**比值法自校准——消除恒流源 I 漂移**：
```
V_mid = I × R_r               → V_ref = V_mid
V_diff = I × (R_s - R_r)

V_diff / V_ref = (R_s - R_r) / R_r = R_s/R_r - 1    ← I 被消去！
```

**最终工作公式**：`Δd = d₀ × [1 - 1/(1 + V_diff/V_ref)]`

**与其它模块交互**：输出 Δd_ER 至 [AlgorithmEngine](file:///e:/Trae CN Projects/sensor_project/src/algorithms/algorithm_engine.py) 进行四级补偿处理。

---

#### 4.2.5 电感探针(LDC1614)驱动——涡流法非接触测厚

**文件位置**：[src/sensors/inductive_driver.py](file:///e:/Trae CN Projects/sensor_project/src/sensors/inductive_driver.py)

**物理量改变链**：
```
试片腐蚀减薄 d↓ → 涡流截面积 A_eddy↓ → 涡流等效电阻 R₂↑ → 反射去磁效应减弱 → 等效电感 L_eq↑
```

**与 ER 探针的关系**：电感探针**本征地几乎不受温度波动影响**（涡流法对电导率变化的灵敏度远低于电阻法的 1:1 直接映射），是验证 ER 探针信号真伪的"黄金判据"。

**技术参数**：28 位分辨率，亚纳米级位移/厚度变化检测。

---

#### 4.2.6 采集调度器

**文件位置**：[src/sensors/acquisition_scheduler.py](file:///e:/Trae CN Projects/sensor_project/src/sensors/acquisition_scheduler.py)

**功能描述**：双模式定时采集调度 + 故障检测 + 传感器模拟器。

**双模式**：

| 模式 | 周期 | 触发条件 |
|:---|:---|:---|
| **Normal** | 10 分钟 | 默认运行 |
| **Emergency** | 1 分钟 × 30 分钟 | \|d(CR)/dt\| > 阈值 或远程指令 |

**采集顺序**：Pt1000 → SHT35 → QCM → ER → Inductive（确保温度数据先到，供后续算法使用）

**故障处理**：每传感器最多重试 3 次 → 标记失败 → 降级运行（其余正常传感器继续）

---

### 4.3 算法引擎层（Algorithms）

#### 4.3.1 四级误差补偿引擎

**文件位置**：[src/algorithms/algorithm_engine.py](file:///e:/Trae CN Projects/sensor_project/src/algorithms/algorithm_engine.py)

**功能描述**：实现完整的四级误差补偿处理管道，这是系统的核心算法模块。

**处理管道**：

```
SensorData 输入
      │
      ▼
┌─────────────────────────────────────────────┐
│ Level 1: 硬件差分补偿                        │
│ Δd_raw = d₀ × (1 - R_r/R_s)               │
│ 验证：0.5 < R_s/R_r < 2.0                   │
├─────────────────────────────────────────────┤
│ Level 2: 比值法自校准                        │
│ 监测 V_ref 短期波动（10ms 窗口）              │
│ 波动率 > 0.1% → 标记恒流源异常               │
├─────────────────────────────────────────────┤
│ Level 3A: 残余温度系数多项式修正              │
│ Δd_corr = Δd_raw / [1 + α_res×(T-T₀)       │
│           + β_res×(T-T₀)²]                  │
│ α_res=β_res=0 → 自动跳过                     │
├─────────────────────────────────────────────┤
│ Level 3B: 湿度门控过滤器                      │
│ ε_noise = 3σ_n (初始24h统计)                │
│ if RH<76% AND Δd≥ε_noise: ValidFlag=0      │
│ 连续10次无效 → 触发探头异常告警               │
├─────────────────────────────────────────────┤
│ Level 3C: 环境因子修正                       │
│ CR_norm = CR_raw × (TOW_ref/TOW_actual)    │
│          × 1/(1 + k_S × S_Cl⁻)             │
├─────────────────────────────────────────────┤
│ Level 3D: 剂量-响应函数预测                   │
│ r_pred = 0.102 × [Cl⁻]^0.62               │
│         × e^(0.033×RH + 0.040×T)           │
│ r_meas/r_pred 交叉验证三区间判定             │
├─────────────────────────────────────────────┤
│ Level 4: 自适应卡尔曼滤波                     │
│ 2状态(Δd, CR) 自适应 Q 协方差               │
│ 约瑟夫形式协方差更新（数值稳定）              │
└─────────────────────────────────────────────┘
      │
      ▼
CorrosionRecord 输出
```

**与其它模块交互**：
- 输入来自 **Sensors 层**的 SensorData
- 输出至 **DualModeValidator** 进行双模交叉验证
- 输出至 **StorageManager** 持久化存储
- 告警条件触发时调用 **AlarmManager**

---

#### 4.3.2 自适应卡尔曼滤波器

**文件位置**：[src/algorithms/kalman_filter.py](file:///e:/Trae CN Projects/sensor_project/src/algorithms/kalman_filter.py)

**核心算法**：

```
状态向量：x = [Δd, CR]^T   （腐蚀深度, 腐蚀速率）
状态转移：F = [[1, dt], [0, 1]]   dt = 采样间隔（年）
测量矩阵：H = [[1, 0]]       直接测量 Δd

自适应 Q：Q = Q_base × (1 + |dT/dt|/10 + |dRH/dt|/50)

需求最少预热样本：36 个（6 小时 × 10min 采样）
使用约瑟夫形式协方差更新保证数值稳定性
```

**关键代码结构**：
```python
class KalmanFilter:
    def __init__(self, measurement_noise_var, base_process_noise):
        self._R = np.array([[measurement_noise_var]])  # 基于 24h σ_n²
        self._Q_base = np.array([[0,0],[0,base_process_noise]])

    def predict(self, dt_years, dT_dt=0, dRH_dt=0):
        # F = [[1,dt],[0,1]]
        # Q = Q_base * (1 + |dT/dt|/10 + |dRH/dt|/50)
        # P = F·P·F^T + Q

    def update(self, measurement):
        # 约瑟夫形式：P = (I-KH)·P·(I-KH)^T + K·R·K^T
```

---

#### 4.3.3 双模冗余交叉验证引擎

**文件位置**：[src/algorithms/dual_mode_validator.py](file:///e:/Trae CN Projects/sensor_project/src/algorithms/dual_mode_validator.py)、[src/algorithms/cross_validation.py](file:///e:/Trae CN Projects/sensor_project/src/algorithms/cross_validation.py)

**核心决策逻辑**：

```
输入：Δd_ER, Δd_Inductive, dT/dt

计算 diff = |CR_ER - CR_Inductive| / [(CR_ER + CR_Inductive)/2]

┌──────────────────────────────────────────────────┐
│ diff < 15%                                        │
│ → "双模一致"                                      │
│ → CR_out = 0.6×CR_ER + 0.4×CR_Inductive          │
│ → η ≈ 1.0（均匀腐蚀）                             │
├──────────────────────────────────────────────────┤
│ diff ≥ 15% AND dT/dt > 2°C/10min                 │
│ → "温度冲击"                                      │
│ → CR_out = 0.2×CR_ER + 0.8×CR_Inductive          │
│ → Level 1 信息通知                                │
├──────────────────────────────────────────────────┤
│ diff ≥ 15% AND dT/dt ≤ 2°C/10min                 │
│ → 可能点蚀                                        │
│ → δ = |Δd_ER - Δd_Inductive| / Δd_ER              │
│ → η = f(δ) 从标定曲线插值                         │
│ → Δd_actual = η × Δd_ER                          │
│ → η>3.0: Level 3 告警                            │
│ → η>5.0: Level 4 紧急告警                        │
└──────────────────────────────────────────────────┘
```

**点蚀因子标定曲线**：[src/algorithms/calibration_curve.py](file:///e:/Trae CN Projects/sensor_project/src/algorithms/calibration_curve.py)

- 内置 10 组 (δ, η) 默认经验数据
- 支持导入实验室标定数据
- 支持分段线性插值和多项式拟合两种模式
- 可追溯版本和标定日期

---

#### 4.3.4 ISO 9223/9224 腐蚀性评估

**文件位置**：[src/algorithms/iso_9223.py](file:///e:/Trae CN Projects/sensor_project/src/algorithms/iso_9223.py)、[src/algorithms/iso_assessment.py](file:///e:/Trae CN Projects/sensor_project/src/algorithms/iso_assessment.py)

**ISO 9223 TOW（年湿润时间）分级**：

| 等级 | TOW 范围 | 描述 |
|:---|:---|:---|
| τ1 | ≤ 10 h/年 | 极短 |
| τ2 | 10~250 h/年 | 短 |
| τ3 | 250~2500 h/年 | 中等 |
| τ4 | 2500~5500 h/年 | 长 |
| τ5 | > 5500 h/年 | 极长 |

**ISO 9223 碳钢腐蚀性分类**：

| 类别 | 第一年腐蚀速率 | 描述 |
|:---|:---|:---|
| C1 | ≤ 1.3 μm/年 | 很低 |
| C2 | 1.3~25 μm/年 | 低 |
| C3 | 25~50 μm/年 | 中 |
| C4 | 50~80 μm/年 | 高 |
| C5 | 80~200 μm/年 | 很高 |
| CX | > 200 μm/年 | 极端 |

**ISO 9224 长期预测**：`D(t) = r_corr_year1 × t^0.523`（碳钢幂函数模型），预测 1/5/10/25 年累计腐蚀深度。

**实测 vs 估计交叉验证**：若实测等级比环境估计高 2 级以上 → 触发"腐蚀加速异常"告警。

---

### 4.4 数据存储层（Storage）

**文件位置**：[src/storage/storage_manager.py](file:///e:/Trae CN Projects/sensor_project/src/storage/storage_manager.py)

**功能描述**：三级存储架构，覆盖从实时缓存到云端持久化的完整数据链路。

**三级存储架构**：

| 层级 | 存储介质 | 分辨率 | 保留期 | 用途 |
|:---|:---|:---|:---|:---|
| **L1** | 内存环形缓冲区 | 100ms（10Hz） | 按容量（10万条） | 实时算法访问 |
| **L2** | SQLite 本地数据库 | 10 分钟 | 1 年（自动清理） | 历史查询与分析 |
| **L3** | 云端同步队列 | 小时级聚合 | 永久 | 远程监控与大数据分析 |

**L2 SQL 数据库表设计**（5 张核心表 + 12 个索引）：

| 表名 | 主要字段 | 用途 |
|:---|:---|:---|
| `sensor_readings` | 时间戳、T、RH、Cl⁻、Δd_ER、Δd_Inductive、电压/电感/频率 | 传感器原始读数 |
| `corrosion_records` | Δd_raw/corrected/filtered、CR_ER/CR_Inductive/CR_out、η | 处理后腐蚀数据 |
| `alarm_records` | UUID、等级、类型、详情(JSON)、状态、操作员 | 告警全生命周期 |
| `audit_log` | 时间、操作员、操作类型、详情、结果 | 不可删除审计日志 |
| `config_history` | 版本号、配置JSON、修改人、修改时间 | 配置变更追溯 |

**数据导出**：
- **CSV**：UTF-8 BOM（Excel 兼容），完整中文表头
- **JSON**：含 metadata（device_id、software_version、export_time）

**与其它模块交互**：
- 接收来自 **AlgorithmEngine** 的 CorrosionRecord
- 接收来自 **AlarmManager** 的 AlarmRecord
- 接收来自 **AuditLogger** 的审计条目
- 为 **UI** 提供分页查询接口
- 为 **Comms** 提供云端同步队列

---

### 4.5 通信层（Comms）

**文件位置**：[src/comms/comm_manager.py](file:///e:/Trae CN Projects/sensor_project/src/comms/comm_manager.py)

**功能描述**：统一管理 LoRaWAN、NB-IoT MQTT、Modbus TCP、MQTT 云平台四类通信通道。

**28 字节紧凑二进制数据包格式**（LoRa 下行）：

```
Byte 0:     版本号 (0x01)
Byte 1:     消息类型 (0x01=data/0x02=alarm/0x03=status)
Byte 2-5:   设备 ID (uint32)
Byte 6-9:   时间戳 (uint32, Unix epoch)
Byte 10-11: 温度 (int16, ×100 °C)
Byte 12-13: 湿度 (uint16, ×10 %)
Byte 14-15: Cl⁻ 沉积率 (uint16, ×10 mg/m²/day)
Byte 16-17: Δd_ER (uint16, ×1000 μm)
Byte 18-19: Δd_Inductive (uint16, ×1000 μm)
Byte 20-21: CR_filtered (uint16, ×1000 μm/year)
Byte 22-23: η (uint16, ×100)
Byte 24:    ValidFlag + AlarmStatus 位标志
Byte 25:    告警位掩码
Byte 26-27: CRC-16-CCITT 校验
总计：28 字节（< 100 字节需求，< 51 字节 LoRa 载荷限制）
```

**Modbus TCP 寄存器映射**：

| 寄存器地址 | 内容 | 数据类型 |
|:---|:---|:---|
| 40001 | T (×10) | 16-bit 有符号 |
| 40002 | RH (×10) | 16-bit 无符号 |
| 40003 | Δd (×1000 μm) | 16-bit 无符号 |
| 40004 | CR (×1000 μm/yr) | 16-bit 无符号 |
| 40005 | η (×100) | 16-bit 无符号 |
| 40006 | 状态字（位标志） | 16-bit |
| 30001-30008 | 传感器原始值 + 诊断信息 | 输入寄存器 |
| 00001-00016 | 告警标志位 + 远程命令确认 | 线圈 |

**MQTT 云平台支持**：阿里云 IoT、华为云 IoT、AWS IoT Core（QoS=1，TLS 1.2，LWT 离线检测）。

**断网补传策略**：离线数据缓存至 L3 同步队列（最多 1000 条）→ 恢复后告警优先 → 新数据优先 → 历史回填。

---

### 4.6 用户界面层（UI）

**文件位置**：[src/ui/main_window.py](file:///e:/Trae CN Projects/sensor_project/src/ui/main_window.py)

**功能描述**：基于 PySide6 的 7-Tab 工业级暗色主题桌面监控界面。

**主界面布局**：

```
┌────────────────────────────────────────────────────┐
│  顶部状态栏：设备ID │ 运行状态 ● │ 系统时间         │
├──────────┬──────────────────────────┬──────────────┤
│ 传感器面板 │    中央图表区（7个Tab）  │   告警面板    │
│          │                          │              │
│ 🌡 23.3▲│ Tab1 实时监测（趋势图）     │ ⚠ 活跃告警   │
│ 💧 84%▼ │ Tab2 腐蚀详情（三曲线）     │  L3 点蚀风险  │
│ 🧂 120▲ │ Tab3 环境关联（双Y轴）     │  L2 通信故障  │
│ 📏 2.5▲ │ Tab4 风险评估（η仪表盘）    │              │
│          │ Tab5 告警管理             │ ✓ 最近解决   │
│          │ Tab6 数据查询             │              │
│          │ Tab7 系统设置（admin）     │ 📊 告警统计   │
└──────────┴──────────────────────────┴──────────────┘
```

**7 个功能 Tab 页**：

| Tab | 名称 | 核心功能 |
|:---|:---|:---|
| **Tab 1** | 实时监测 | Δd_ER(蓝)/Δd_Inductive(橙) 实时趋势图，1h~1y 时间切换 |
| **Tab 2** | 腐蚀详情 | Δd_raw/Δd_corrected/Δd_filtered 三曲线叠加，ValidFlag 过滤 |
| **Tab 3** | 环境关联 | 双Y轴(T+RH vs Δd)，76% RH 临界线，湿度门控标记区，[Cl⁻] 柱状图 |
| **Tab 4** | 风险评估 | C1~CX 等级卡片，η 半圆仪表盘（红/黄/绿区），25年进度条 |
| **Tab 5** | 告警管理 | 全告警列表（等级/状态/时间过滤），确认/解决/详情操作 |
| **Tab 6** | 数据查询 | 时间范围+类型过滤，分页表格，CSV/JSON 导出 |
| **Tab 7** | 系统设置 | 传感器/采样/算法/告警/通信全参数配置（仅 Admin） |

**5 个自定义控件**：

| 控件 | 说明 |
|:---|:---|
| `SensorDisplayWidget` | 传感器读数卡片（图标+数值+趋势箭头+更新时间） |
| `AlarmBadge` | 彩色圆型告警徽章（红=4/橙=3/黄=2/蓝=1） |
| `EtaGaugeWidget` | η 因子半圆仪表盘（QPainter 自绘，0.5~10.0） |
| `StatusIndicator` | 连接状态灯（绿/黄/红） |
| `TrendArrow` | 趋势方向指示（▲=上升/▼=下降/─=平稳） |

**线程安全**：后台数据通过 `QMetaObject.invokeMethod` 推送到 UI 线程，防止跨线程崩溃。

---

## 5. 数据流与核心算法

### 5.1 完整数据处理管道

```
  ┌──────────────────────┐
  │   MCU 传感器采集      │      10min / 1min(应急)
  │ Pt1000│SHT35│QCM│ER│Ind │
  └──────────┬───────────┘
             │ UART/RS-485 串行总线
             ▼
  ┌──────────────────────┐
  │   SensorManager      │      串口解析 + 模拟模式
  │   生成 SensorData     │
  └──────────┬───────────┘
             │ App 信号: sensor_data_received
             ▼
  ┌──────────────────────┐
  │   AlgorithmEngine    │      四级误差补偿管道
  │   生成 CorrosionRecord│      L1→L2→L3A→L3B→L3C→L3D→L4
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │  CrossValidationEngine│    双模交叉验证 + 点蚀诊断
  │   生成 CrossValidResult│     三场景判定 → η 因子
  └──────────┬───────────┘
             │
     ┌───────┼───────┐
     ▼       ▼       ▼
  ┌──────┐┌──────┐┌──────┐
  │Store ││Alarm ││ Comms│
  │SQLite││Manager││ MQTT │
  └──┬───┘└──┬───┘└──┬───┘
     │       │       │
     ▼       ▼       ▼
  ┌──────────────────────────┐
  │          UI              │
  │  实时更新 Tables + Charts │
  └──────────────────────────┘
```

### 5.2 核心公式索引

| 公式编号 | 名称 | 数学表达式 |
|:---|:---|:---|
| **CVD** | Pt1000 温度解算 | `R_T = R₀(1 + αT + βT²)`，`R₀=1000Ω` |
| **Sauerbrey** | QCM 质量检测 | `Δf ≈ -2.26×10⁸ × Δm/A` |
| **式(8)** | 双环差分腐蚀深度 | `Δd = d₀(1 - R_r/R_s)` |
| **式(13)** | 比值法工作公式 | `Δd = d₀[1 - 1/(1 + V_diff/V_ref)]` |
| **式(19)** | 最大点蚀深度 | `Δd_actual = η × Δd_ER` |
| **式(20)** | 双模差异度 | `δ = |Δd_ER - Δd_Inductive| / Δd_ER` |
| **式(21)** | 残余温度修正 | `Δd_corr = Δd_raw / [1 + α_res×(T-T₀) + β_res×(T-T₀)²]` |
| **式(22)** | 湿度门控 | `ValidFlag = 1 if (RH≥76% OR Δd_raw<ε_noise) else 0` |
| **式(23)** | 环境归一化 | `CR_norm = CR_raw × (TOW_ref/TOW_actual) × 1/(1+k_S×S_Cl⁻)` |
| **式(25)** | 剂量-响应预测 | `r_pred = 0.102 × [Cl⁻]^0.62 × e^(0.033×RH+0.040×T)` |
| **ISO 9224** | 长期预测 | `D(t) = r_corr_year1 × t^0.523` |

---

## 6. 项目部署流程

### 6.1 环境要求

| 项目 | 最低要求 |
|:---|:---|
| **Python** | 3.9 或更高版本 |
| **操作系统** | Windows 10+ / Ubuntu 20.04+ / Debian 11+ |
| **内存** | ≥ 512 MB（嵌入式）/ ≥ 2 GB（桌面） |
| **磁盘** | ≥ 500 MB（1 年数据存储） |
| **串口** | ≥ 1 个可用 UART/RS-485 端口 |

### 6.2 快速安装

```bash
# 1. 克隆或解压项目
cd sensor_project

# 2. 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate    # Linux/Mac
venv\Scripts\activate       # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装项目包（可选）
pip install -e .
```

### 6.3 配置

```bash
# 编辑默认配置文件
vim config/default_config.json

# 或通过 UI 界面：系统设置 Tab（需 Admin 权限）
```

### 6.4 启动

```bash
# 桌面模式（含 UI）
python main.py

# 自定义配置目录
python main.py --config-dir ./my_config

# 调试模式
python main.py --log-level DEBUG

# 查看版本
python main.py --version
```

### 6.5 运行测试

```bash
# 运行所有测试
python run_tests.py

# 仅运行集成测试
python run_tests.py integration

# 仅运行性能测试
python run_tests.py performance

# 仅运行规格场景测试
python run_tests.py spec

# 或直接用 pytest
pytest tests/ -v
```

### 6.6 生产部署建议

1. 使用 `systemd`（Linux）或 Windows 服务管理器将 `main.py` 注册为开机自启服务
2. 配置 `default_config.json` 中的 `storage.data_retention_days` 为 365
3. 配置 `comms.cloud` 连接实际云端 MQTT 服务器
4. 确保日志目录 `logs/` 和数据库目录 `data/` 有写入权限
5. 建议配置系统级看门狗（硬件看门狗 + systemd WatchdogSec）

---

## 7. 开发规范

### 7.1 代码风格

- 遵循 **PEP 8** Python 编码规范
- 所有公开方法必须包含 **Google 风格 docstring**
- 使用 **Python 3.9+ 类型提示**（Type Hints）
- 类名使用 **PascalCase**，函数/变量使用 **snake_case**
- 常量使用 **UPPER_SNAKE_CASE**
- 最大行宽：120 字符

### 7.2 线程安全规范

- **核心模块单例**（App、ConfigManager、Logger）使用双重检查锁
- **告警管理器**使用 `threading.RLock()` 保护状态变更
- **环形缓冲区**使用 `threading.Lock` 保护读写
- **UI 更新**必须通过 `QMetaObject.invokeMethod` 从后台线程切换到主线程
- 禁止在非主线程中直接操作 Qt Widget

### 7.3 错误处理规范

- 所有 I/O 操作（数据库、串口、网络）必须包含 `try/except` 并记录日志
- 传感器故障允许**降级运行**，关键系统故障阻止进入 RUNNING 状态
- 告警自动去重（10 分钟内同类告警不重复触发）
- 看门狗复位前保存最后状态到非易失性存储

### 7.4 测试规范

- 单元测试使用 **pytest** 框架
- 数据驱动测试使用**参数化**（`@pytest.mark.parametrize`）
- 集成测试使用**内存数据库**（`:memory:`），不依赖文件系统
- 使用 **SensorSimulator** 替代真实硬件进行测试
- 性能测试每项至少运行 **100 次迭代**，报告 min/avg/max
- 目标覆盖率：核心算法 100%，UI 60%+

### 7.5 命名规范

- 模块文件：`snake_case.py`
- 测试文件：`test_模块名.py`
- 配置字段：`snake_case` 嵌套 JSON
- SQL 表名：`snake_case`
- 环境变量：`UPPER_SNAKE_CASE`

### 7.6 日志规范

| 级别 | 用途 | 示例 |
|:---|:---|:---|
| **DEBUG** | 算法中间步骤、补偿值 | `Level 3B: ValidFlag=0, RH=72.3% < 76%` |
| **INFO** | 系统生命周期、正常操作 | `System initialization completed` |
| **WARNING** | 传感器降级、配置异常 | `Sensor SHT35 malfunction, running degraded` |
| **ERROR** | 操作失败、通信超时 | `Database write failed after 3 retries` |
| **CRITICAL** | 系统级故障 | `POST failed – blocking normal operation` |

---

## 8. 未来迭代计划

### 8.1 v1.1 — 增强分析（预计 +3 个月）

- [ ] **机器学习腐蚀预测模型**：利用积累的历史数据训练 LSTM/GRU 时序预测模型，替代简化的 ISO 9224 幂函数模型
- [ ] **多风机对比分析**：同风场多台风机腐蚀数据横向对比，识别异常风机
- [ ] **腐蚀热力图**：在 3D 风机模型中叠加腐蚀深度热力图，直观展示腐蚀分布
- [ ] **报告自动生成**：周报/月报/季报自动生成并邮件推送

### 8.2 v1.2 — 扩展生态（预计 +6 个月）

- [ ] **Web Dashboard**：基于 Vue.js + ECharts 的云端 Web 管理面板，支持多风场集中管控
- [ ] **移动端 APP**：iOS/Android 移动端告警推送与数据查看
- [ ] **第三方 SCADA 深度集成**：OPC-UA 协议支持，与主流 SCADA 系统（WinCC、Ignition）无缝对接
- [ ] **API 网关**：RESTful API 供第三方系统调用腐蚀数据

### 8.3 v1.3 — 智能化升级（预计 +12 个月）

- [ ] **自动决策支持**：基于腐蚀速率和剩余壁厚的检修建议自动生成（维修优先级排序）
- [ ] **数字孪生**：风机腐蚀状态的实时数字孪生模型，支持"what-if"推演
- [ ] **自适应报警阈值**：基于历史数据和腐蚀阶段自动调整告警阈值，减少误报
- [ ] **边缘 AI 推理**：在工控机端部署轻量级 TensorFlow Lite 模型，实现实时腐蚀模式识别

### 8.4 v2.0 — 平台化（预计 +18 个月）

- [ ] **多场景适配**：扩展到海上石油平台、跨海大桥、海底管线等海洋工程腐蚀监测
- [ ] **SaaS 化运营**：腐蚀监测即服务（CMaaS），支持多租户隔离
- [ ] **区块链数据存证**：关键腐蚀数据和告警记录上链，提供不可篡改的合规证据
- [ ] **国际认证**：通过 DNV-GL、BV 等船级社软件认证

---

## 附录：项目文件清单

| 文件路径 | 功能说明 |
|:---|:---|
| `main.py` | 应用入口，参数解析，信号处理 |
| `setup.py` | 包安装配置，CLI 命令 `corrosion-detector` |
| `requirements.txt` | 8 个 Python 依赖库 |
| `run_tests.py` | 测试运行器（支持分类运行） |
| `config/default_config.json` | 完整默认配置（292行，7 大区块） |
| `src/core/app.py` | 主应用类（单例/生命周期/信号槽） |
| `src/core/config_manager.py` | JSON 配置管理（加载/保存/范围验证） |
| `src/core/logger.py` | 线程安全日志（控制台+文件轮转） |
| `src/core/data_models.py` | 6 个 dataclass + 4 个枚举 |
| `src/core/alarm_manager.py` | 四级告警全生命周期管理 |
| `src/core/alarm_definitions.py` | 15 种告警类型元数据定义 |
| `src/core/notification_service.py` | 多通道异步通知推送 |
| `src/core/auth_manager.py` | RBAC 三级权限 + 登录锁定 |
| `src/core/audit_logger.py` | 审计日志（不可删除） |
| `src/core/crypto_utils.py` | CRC-16/SHA-256/AES-128-GCM/PBKDF2 |
| `src/core/data_integrity.py` | 数据签名/验签/安全擦除 |
| `src/core/diagnostics.py` | POST 自检 + 30天诊断 + 看门狗 |
| `src/core/watchdog.py` | 30秒超时看门狗定时器 |
| `src/core/health_monitor.py` | 系统健康持续监控 |
| `src/sensors/sensor_manager.py` | 传感器总控（串口/模拟双模式） |
| `src/sensors/pt1000_driver.py` | Pt1000 CVD 方程温度解算 |
| `src/sensors/sht35_driver.py` | SHT35 湿度+CRC-8 校验 |
| `src/sensors/qcm_driver.py` | QCM Sauerbrey 盐度计算 |
| `src/sensors/er_probe_driver.py` | ER 双环差分电阻探针 |
| `src/sensors/inductive_driver.py` | LDC1614 涡流电感探针 |
| `src/sensors/acquisition_scheduler.py` | 10min/1min 双模式采集调度 |
| `src/sensors/sensor_simulator.py` | 昼夜周期传感器模拟器 |
| `src/algorithms/algorithm_engine.py` | 四级误差补偿主引擎 |
| `src/algorithms/kalman_filter.py` | 2状态自适应卡尔曼滤波器 |
| `src/algorithms/dose_response.py` | ISO 9224 剂量-响应函数 |
| `src/algorithms/tow_calculator.py` | ISO 9223 TOW 湿润时间统计 |
| `src/algorithms/iso_9223.py` | ISO 9223 腐蚀性等级评估器 |
| `src/algorithms/iso_assessment.py` | ISO 评估编排引擎 |
| `src/algorithms/dual_mode_validator.py` | 双模交叉验证+三场景判定 |
| `src/algorithms/calibration_curve.py` | η=f(δ) 标定曲线管理 |
| `src/algorithms/cross_validation.py` | 交叉验证全流程引擎 |
| `src/storage/storage_manager.py` | 三级存储+CRUD+CSV/JSON导出 |
| `src/comms/comm_manager.py` | 通信总控管理器 |
| `src/comms/data_packet.py` | 28字节二进制/JSON双格式数据包 |
| `src/comms/lorawan_channel.py` | LoRaWAN 通道（AES-128-GCM加密） |
| `src/comms/nbiot_channel.py` | NB-IoT MQTT 通道 |
| `src/comms/modbus_server.py` | Modbus TCP 从站服务器 |
| `src/comms/mqtt_client.py` | 三平台 MQTT 客户端 |
| `src/comms/backlog_manager.py` | 断网补传管理（1000条缓存） |
| `src/ui/main_window.py` | 7-Tab PySide6 主窗口（1686行） |
| `src/ui/styles.py` | QSS 暗色工业监控主题 |
| `src/ui/widgets/sensor_display_widget.py` | 传感器数值卡片控件 |
| `src/ui/widgets/alarm_badge.py` | 告警彩色徽章控件 |
| `src/ui/widgets/eta_gauge_widget.py` | η 因子半圆仪表盘控件 |
| `src/ui/widgets/status_indicator.py` | 连接状态灯控件 |
| `src/ui/widgets/trend_arrow.py` | 趋势箭头控件 |
| `tests/test_integration.py` | 82 项集成测试（8 个测试类） |
| `tests/test_performance.py` | 15 项性能基准测试 |
| `tests/test_spec_scenarios.py` | 35 项规格场景验证 |

---

> **文档版本**：v1.0.0  
> **最后更新**：2026-05-26  
> **作者**：Sensor Project Team  
> **许可证**：专有软件（Proprietary）
