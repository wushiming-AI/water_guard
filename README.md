# 水域溺水防控AI预警系统 (WaterGuard) v3.0

> 基于 YOLO 目标检测 + FastAPI + 微信小程序的全栈溺水预警系统
> 支持多摄像头监控大屏、用户管理、实时数据推送

---

## 系统架构

```
┌──────────────┐    HTTP/WS     ┌──────────────┐    推帧/报警/心跳    ┌──────────────┐
│  微信小程序   │ ◄──────────► │  FastAPI 后端  │ ◄─────────────────► │  YOLO 检测端  │
│  (5个页面)    │               │  backend.py   │                     │ drowning_yolo │
│  多摄像头大屏  │               │  v3.0 多路流  │                     │  v3.0 多摄像头 │
└──────────────┘               └──────┬───────┘                     └──────────────┘
                                      │
┌──────────────┐               ┌──────▼───────┐
│  Web 前端     │ ◄──────────► │    MySQL      │
│  (6个HTML)   │               │ drowning_alarm│
│  监控大屏     │               └──────────────┘
│  用户管理     │
└──────────────┘
```

## v3.0 新功能

- **多摄像头监控大屏**：总屏网格 + 分屏全屏切换，1-9宫格自适应
- **真实摄像头检测**：自动扫描本地可用摄像头，按实际显示
- **用户管理系统**：后台创建账号、分发、改密，角色权限控制
- **多路视频流**：每个摄像头独立 MJPEG 流和快照接口
- **摄像头心跳**：检测脚本定期上报心跳，超时自动标记离线
- **实时数据推送**：WebSocket 广播设备/摄像头/用户/统计变更事件

## 快速启动

### 1. 环境要求

- Python 3.9+
- MySQL 5.7+
- Windows / Linux

### 2. 安装依赖

```bash
pip install fastapi uvicorn aiomysql pydantic requests opencv-python numpy

# 如需 YOLO 检测功能
pip install ultralytics torch
```

### 3. 初始化数据库

```bash
mysql -u root -p123456 < init.sql
```

或启动后端后自动创建表和默认数据。

### 4. 启动后端

```bash
cd C:\Users\AA\Desktop\water_guard
python backend.py
```

后端运行在 `http://0.0.0.0:8000`

### 5. 启动检测脚本

```bash
# 使用默认摄像头
python drowning_yolo.py

# 使用 test.mp4 测试
python drowning_yolo.py --source test.mp4

# 指定摄像头ID
python drowning_yolo.py --camera-id CAM-002 --source 1
```

### 6. 访问前端

- 登录页：`index.html`
- 监控大屏：`dashboard.html`
- 用户管理：`users.html`
- API 文档：`http://127.0.0.1:8000/docs`

### 7. 微信小程序

1. 打开微信开发者工具
2. 导入 `miniprogram` 目录
3. 勾选「不校验合法域名」
4. 服务器地址填写 `http://127.0.0.1:8000`（本机）或 `http://192.168.5.3:8000`（局域网）

## API 端点一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/api/login` | 用户登录 |
| POST | `/api/change-password` | 修改密码 |
| GET | `/api/users` | 用户列表 |
| POST | `/api/users` | 创建用户 |
| DELETE | `/api/users/{id}` | 删除用户 |
| GET | `/api/cameras` | 摄像头列表 |
| GET | `/api/cameras/detect` | 检测本地摄像头 |
| GET | `/api/cameras/{id}/snapshot` | 摄像头快照 |
| GET | `/api/cameras/{id}/feed` | 摄像头 MJPEG 流 |
| POST | `/api/cameras/{id}/frame` | 接收帧推送 |
| POST | `/api/cameras/{id}/heartbeat` | 摄像头心跳 |
| GET | `/api/devices` | 设备列表 |
| POST | `/api/devices` | 添加设备 |
| DELETE | `/api/devices/{id}` | 删除设备 |
| GET | `/api/stats` | 统计数据 |
| GET | `/api/settings` | 系统设置 |
| POST | `/api/settings` | 更新设置 |
| POST | `/alarm` | 推送报警 |
| GET | `/alarms` | 报警列表 |
| GET | `/video_feed` | 默认视频流 |
| GET | `/latest_frame` | 默认最新帧 |
| WS | `/ws` | WebSocket 实时推送 |

## 默认账号

| 手机号 | 密码 | 角色 |
|--------|------|------|
| 13800138000 | 123456 | admin |

管理员可在「用户管理」页面创建新账号并分发。

## 项目结构

```
water_guard/
├── backend.py            # FastAPI 后端 v3.0
├── drowning_yolo.py      # YOLO 检测脚本 v3.0
├── init.sql              # 数据库初始化
├── index.html            # 登录页
├── dashboard.html        # 监控大屏（多摄像头网格）
├── alarms.html           # 预警记录
├── devices.html          # 设备管理
├── users.html            # 用户管理（v3.0 新增）
├── settings.html         # 系统设置
├── miniprogram/          # 微信小程序
│   ├── app.js
│   ├── app.json
│   ├── app.wxss
│   ├── utils/
│   │   └── api.js
│   ├── custom-tab-bar/
│   ├── pages/
│   │   ├── dashboard/   # 多摄像头监控大屏
│   │   ├── login/
│   │   ├── alarms/
│   │   ├── devices/
│   │   └── settings/
│   └── ...
└── README.md
```

## 环境变量

### backend.py
| 变量 | 默认值 | 说明 |
|------|--------|------|
| DB_HOST | 127.0.0.1 | MySQL 地址 |
| DB_PORT | 3306 | MySQL 端口 |
| DB_USER | root | MySQL 用户 |
| DB_PASSWORD | 123456 | MySQL 密码 |
| DB_NAME | drowning_alarm | 数据库名 |

### drowning_yolo.py
| 参数 | 默认值 | 说明 |
|------|--------|------|
| --camera-id | CAM-001 | 摄像头ID |
| --source | 0 | 视频源 |
| --model | best.pt | YOLO 模型路径 |
| --backend | http://127.0.0.1:8000 | 后端地址 |
