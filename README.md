# 基于深度学习的物联网智能燃气表数据异常检测系统

本项目以论文初稿《基于深度学习的物联网智能燃气表数据异常检测系统的设计与实现》为准，是一个面向智慧燃气运维场景的 Web 系统。系统围绕智能燃气表数据接入与预处理、LSTM AutoEncoder 时序异常检测、业务规则联合研判、实时监控看板、告警与工单闭环、模型持续训练和模型版本管理展开。

当前仓库已整理为系统工程目录。答辩相关材料保留在 `docs/`：

- `docs/2022005052-王晨阳-答辩稿.docx`
- `docs/2022005052-王晨阳-毕业答辩PPT codex版本.pptx`
- `docs/答辩-系统总结与代码讲解.md`
- `docs/答辩-论文初稿总结与讲解.md`

## 论文对应能力

- 数据接入与预处理：支持设备注册、密钥校验、HTTP 上报、MQTT 网关、运营商 Webhook 和虚拟设备模拟器；统一接收设备编号、时间戳、瞬时流量、累计用气量、电池电压、信号强度、阀门状态、环境温度、管网压力等字段。
- 深度学习异常检测引擎：按设备构造 24 点滑动窗口，提取 7 类模型特征，调用 LSTM AutoEncoder 计算重构误差、异常得分、阈值和预测标签。
- 业务规则融合：结合低电压、弱信号、流量突变、长时间静止、压力异常等规则，对模型结果进行二次研判并输出异常类型和等级。
- 告警与工单闭环：异常数据落库后生成告警，支持管理员派单、工程师接单、处理结果回写和人工反馈样本沉淀。
- 实时监控与可视化：提供仪表盘、设备管理、历史数据、告警列表、工单管理、工程师管理、报表和系统设置页面。
- 持续训练流水线：支持训练数据生成、清洗、候选模型训练、模型评估、版本注册和 active model 切换，使模型适应燃气表运行特征变化。

## 目录结构

```text
src/                 Flask 后端、分层业务代码、检测服务、训练模块与网关
src/application/     应用编排层，管理后台服务生命周期和实时广播
src/domain/          业务域门面，提供设备、身份、监控、工单等稳定入口
frontend/index.html  独立 Vue 前端入口
frontend/src/        Vue 页面逻辑、ECharts/Leaflet 可视化和现代化样式
scripts/             本地检查和实验评估脚本
docs/                系统说明文档、答辩稿、答辩 PPT 和答辩总结
data/                本地训练/预测数据目录，CSV 生成物不入库
models/              模型文件、标准化器、模型注册表，生成物不入库
instance/            本地数据库实例，生成物不入库
```

## 快速启动

先安装依赖：

```powershell
pip install -r requirements.txt
```

启动系统：

```powershell
.\start_system.bat
```

`start_system.bat` 会同时启动后端和独立前端。如果只需要单独托管前端，可另开终端运行：

```powershell
.\start_frontend.bat
```

默认访问地址：

```text
前端：http://127.0.0.1:5173
后端：http://127.0.0.1:5000
```

虚拟燃气表模拟器、持续训练流水线、数据漂移监控和 MQTT 网关已集成到系统设置页，通过页面开关统一启停，不再单独提供启动脚本。

## 默认配置

系统默认使用 MySQL：

```text
DB_BACKEND=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=gas_monitor
MYSQL_USER=root
MYSQL_PASSWORD=<本机 MySQL 密码>
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
```

本地临时测试可切换 SQLite：

```powershell
$env:DB_BACKEND="sqlite"
.\start_system.bat
```

更多配置见 `docs/配置说明.md`。

## 常用脚本

| 脚本 | 用途 |
| --- | --- |
| `start_system.bat` | 启动完整系统，前端页面、后端 API 和模块控制入口统一加载 |
| `start_frontend.bat` | 单独启动独立前端静态服务 |
| `validate_project_health.bat` | 执行本地健康检查 |
| `system_health_check.bat` | 在系统运行后执行前端资源、后端接口和登录看板诊断 |
| `export_lstm_autoencoder_experiment_results.bat` | 导出 LSTM AutoEncoder 实验评估结果 |

脚本详情见 `docs/脚本说明.md`。

辅助脚本位于 `scripts/`：

- `validate_project_health.py`：批处理健康检查调用的后端验证脚本。
- `evaluate_lstm_autoencoder_experiment_results.py`：导出论文第 6 章可用的模型评估数据与 SVG 图表，默认输出到 `data/experiment_results/`。

## 主要接口

- `POST /api/device/register`：设备注册。
- `POST /api/device/upload`：设备上报读数，需携带 `X-API-Key`。
- `POST /api/carrier/webhook/<provider>`：运营商平台数据转发。
- `GET /api/dashboard`：仪表盘数据。
- `GET /api/reconstruction`：最近窗口的原始曲线、重构曲线和误差数据。
- `GET|POST /api/training`：持续训练状态与控制。
- `GET|POST /api/drift`：数据漂移监控状态与控制。

完整接口见 `docs/接口文档.md`。

## 后端分层

当前后端按入口、应用编排、业务域、基础设施四层维护：

- `src/app.py`：HTTP API、页面重定向、认证权限和 WebSocket 入口。
- `src/application/`：后台服务运行态、实时广播等跨业务用例编排。
- `src/domain/`：设备、身份、监控、工单和初始化等业务域门面。
- `src/database.py`、`src/device_integration.py`、`src/model_registry.py`、`src/*_gateway.py`：数据库、设备接入、模型注册和外部协议适配。

## 生成物管理

以下内容是运行时或本地生成物，不作为系统文档保留：

- `__pycache__/`
- `.npm-cache/`
- `data/**/*.csv`
- `models/*.pt`
- `models/*.pkl`
- `models/registry/`
- `instance/*.db`
- 论文图片、PPT 工作区、Mermaid 渲染图、实验报告图片

系统说明文档位于 `docs/`；答辩稿、答辩 PPT 和两份答辩总结文档也纳入该目录统一维护。
