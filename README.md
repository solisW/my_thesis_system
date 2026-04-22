# 智能燃气设备监测与工单调度平台

本项目是一个完整的后台管理系统，面向物联网智能燃气表场景，覆盖设备监测、异常检测、地图告警、设备管理、工程师管理、工单调度、历史数据查询和统计报表。

## 当前功能

- 登录 / 注册
- 菜单式后台主页
- 主页显示在线设备数、离线设备数、异常设备数
- 地图面板显示异常设备位置
- 单个设备管理：新增、编辑、删除、连通性测试
- 工程师管理
- 紧急工单调度与分配
- 告警中心
- 历史数据查询
- 统计报表
- 50 台模拟设备持续上报
- 真实物理设备上传接口保留
- WebSocket 实时推送

## 页面结构

- `/login` 登录页
- `/dashboard` 系统主页
- `/devices` 设备管理
- `/engineers` 工程师管理
- `/work-orders` 工单调度
- `/alerts` 告警中心
- `/reports` 统计报表
- `/history` 历史数据
- `/settings` 系统设置

## 默认账号

- 用户名：`admin`
- 密码：`admin123`

## 模拟设备

系统默认创建 `50` 台模拟设备，并由后台模拟器持续生成数据，再交给后端处理后通过 WebSocket 推送到前端。

如果需要修改模拟数量，可设置环境变量：

```powershell
$env:SIMULATION_DEVICE_COUNT="50"
```

## 真实设备接口

系统保留真实物理设备接口：

```text
POST /api/device/upload
```

请求头：

```text
X-API-Key: 设备密钥
Content-Type: application/json
```

请求体示例：

```json
{
  "timestamp": "2026-04-22T10:00:00",
  "instant_flow": 0.326,
  "cumulative_usage": 180.52,
  "battery_voltage": 3.21,
  "signal_strength": 74.8,
  "valve_state": 1,
  "temperature": 19.2,
  "pressure": 2.06
}
```

## 启动方式

如果本机没有 MySQL，建议先使用 SQLite 启动：

```powershell
cd "C:\Users\W1503\Documents\New project"
$env:DB_BACKEND="sqlite"
python -m src.app
```

浏览器访问：

```text
http://127.0.0.1:5000
```

## 论文初稿

论文初稿已经生成：

- `docs/论文初稿.md`

## 主要目录

- `src` 后端源码
- `templates` 页面模板
- `static` 前端脚本与样式
- `docs` 文档与论文初稿
