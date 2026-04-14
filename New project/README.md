# 智能燃气表异常检测系统

当前项目已经实现以下能力：

- 登录 / 注册
- 管理员密码对称加密存储
- WebSocket 实时推送
- 实时仪表盘
- 设备新增 / 编辑 / 删除
- 模拟器手动启动 / 停止
- 告警中心
- 历史数据查询
- 真实设备上传 API
- LSTM AutoEncoder 异常检测
- MySQL 优先数据库配置

## 启动前说明

系统默认按 MySQL 启动，默认连接参数来自环境变量或以下默认值：

- `MYSQL_USER=root`
- `MYSQL_PASSWORD=123456`
- `MYSQL_HOST=127.0.0.1`
- `MYSQL_PORT=3306`
- `MYSQL_DATABASE=gas_monitor`

如果你已经有 MySQL，只需要先创建数据库：

```sql
CREATE DATABASE gas_monitor CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

然后运行：

```powershell
cd "C:\Users\W1503\Documents\New project"
python -m src.app
```

如果你暂时没有 MySQL，只想先看功能，可以临时切回 SQLite：

```powershell
$env:DB_BACKEND="sqlite"
python -m src.app
```

## 默认账号

- 用户名：`admin`
- 密码：`admin123`

管理员密码在数据库中以对称加密密文保存，密钥来自：

- `APP_CREDENTIAL_SECRET`

如果不设置，系统使用默认密钥。

## 页面

- `/dashboard` 实时仪表盘
- `/devices` 设备管理
- `/alerts` 告警中心
- `/history` 历史数据
- `/settings` 系统设置和模拟器控制

## 设备上传接口

地址：

```text
POST /api/device/upload
```

请求头：

```text
X-API-Key: key-gm001
Content-Type: application/json
```

请求体示例：

```json
{
  "timestamp": "2026-04-13T15:07:11",
  "instant_flow": 0.328,
  "cumulative_usage": 188.4,
  "battery_voltage": 3.21,
  "signal_strength": 73.5,
  "valve_state": 1,
  "temperature": 19.2,
  "pressure": 2.08
}
```

## 关键目录

- `src` 后端源码
- `templates` 页面模板
- `static` 前端样式和脚本
- `instance` SQLite 文件目录

## 关键点

- 页面实时更新已经从轮询改为 WebSocket
- 模拟器与真实设备共用同一套后端处理链路
- 设备管理页支持新增、编辑、删除
- 系统设置页支持模拟器启停
