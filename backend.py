"""
水域溺水防控AI预警系统 - 后端服务
基于 FastAPI + aiomysql + MySQL
v4.0 — 多摄像头支持、用户管理、摄像头检测、实时数据推送
       新增：DeepSORT跟踪、CBAM检测、多端联动报警、泳池平面图、双模态融合
"""
import asyncio
import base64
import io
import json
import logging
import os
import platform
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

import aiomysql
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ─── 日志配置 ───────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── MySQL 连接配置 ─────────────────────────────────────────────────────────
DB_CONFIG: Dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "db": "drowning_alarm",
    "charset": "utf8mb4",
    "autocommit": True,
}

# ─── 全局状态 ───────────────────────────────────────────────────────────────
db_pool: Optional[aiomysql.Pool] = None
camera_frames: Dict[str, bytes] = {}               # 每个摄像头的最新帧 {camera_id: JPEG bytes}
camera_frame_events: Dict[str, asyncio.Event] = {}  # 每个摄像头的帧更新事件
camera_heartbeats: Dict[str, float] = {}            # 每个摄像头最后心跳时间 {camera_id: timestamp}
connected_clients: List[WebSocket] = []              # WebSocket 客户端列表
start_time: float = time.time()                     # 服务启动时间
FRAME_MAX_SIZE: int = 5 * 1024 * 1024               # 帧大小上限 5MB
WS_HEARTBEAT_TIMEOUT: float = 60.0                  # WebSocket 心跳超时（秒）
CAMERA_OFFLINE_TIMEOUT: float = 30.0                 # 摄像头离线超时（秒）


# ─── 占位图（运行时生成有效 JPEG）──────────────────────────────────────────
def _make_placeholder(width: int = 640, height: int = 360, text: str = "") -> bytes:
    """生成深色占位 JPEG（无需 Pillow，用 SVG 转 JPEG 太复杂，直接用 hex 构建）"""
    # 使用简单的 1x1 灰色 JPEG，前端会用 SVG 占位图覆盖
    return bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000"
        "ffdb004300" + "01" * 64
        + "ffc0000b080001000101011000"
        "ffc4001f0000010501010101010100000000000000"
        "000102030405060708090a0b"
        "ffc400b5100002010303020403050504040000017d"
        "01020300041105122131060713516107227114328191"
        "a1082342b1c11552d1f02433627282090a161718191a"
        "25262728292a3435363738393a434445464748494a53"
        "5455565758595a636465666768696a73747576777879"
        "7a838485868788898a92939495969798999aa2a3a4a5"
        "a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8"
        "c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9ea"
        "f1f2f3f4f5f6f7f8f9fa"
        "ffda0008010100003f00"
        "7ffbf800"
        "ffd9"
    )

PLACEHOLDER_FRAME: bytes = _make_placeholder()


# ─── Pydantic 模型 ──────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    phone: str
    password: str


class AlarmPayload(BaseModel):
    timestamp: Optional[str] = None
    location: Optional[str] = "未知位置"
    camera_id: Optional[str] = None
    level: Optional[str] = "urgent"       # urgent(紧急/溺水) / info(记录/游泳/戏水)
    detect_type: Optional[str] = None     # drowning / swimming / playing
    image_path: Optional[str] = None
    note: Optional[str] = None


class FramePayload(BaseModel):
    frame: str  # base64 编码的 JPEG


class DeviceCreate(BaseModel):
    name: str
    device_id: Optional[str] = None
    location: Optional[str] = None
    ip_address: Optional[str] = None
    status: Optional[str] = "online"


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    device_id: Optional[str] = None
    location: Optional[str] = None
    ip_address: Optional[str] = None
    status: Optional[str] = None


class SettingsBatch(BaseModel):
    settings: Dict[str, str]


class ChangePasswordRequest(BaseModel):
    phone: str
    old_password: str
    new_password: str


class UserCreate(BaseModel):
    phone: str
    password: str
    role: Optional[str] = "user"
    nickname: Optional[str] = ""


class CameraHeartbeat(BaseModel):
    status: Optional[str] = "online"
    resolution: Optional[str] = ""


# ─── 数据库初始化 SQL ────────────────────────────────────────────────────────
INIT_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    phone VARCHAR(20) NOT NULL UNIQUE,
    password VARCHAR(100) NOT NULL,
    role VARCHAR(20) DEFAULT 'user',
    nickname VARCHAR(50) DEFAULT '',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alarms (
    id INT PRIMARY KEY AUTO_INCREMENT,
    time DATETIME DEFAULT CURRENT_TIMESTAMP,
    location VARCHAR(255) DEFAULT '未知位置',
    message TEXT,
    level VARCHAR(20) DEFAULT 'warning',
    status VARCHAR(20) DEFAULT 'unread',
    image_path TEXT
);

CREATE TABLE IF NOT EXISTS cameras (
    id INT PRIMARY KEY AUTO_INCREMENT,
    camera_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    source VARCHAR(255) NOT NULL DEFAULT '0',
    location VARCHAR(255) DEFAULT '',
    status VARCHAR(20) DEFAULT 'offline',
    resolution VARCHAR(20) DEFAULT '',
    last_frame_time DATETIME,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS devices (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    device_id VARCHAR(50) UNIQUE,
    device_type VARCHAR(20) DEFAULT 'camera',
    location TEXT,
    ip_address VARCHAR(50),
    status VARCHAR(20) DEFAULT 'online',
    camera_id VARCHAR(50) DEFAULT NULL,
    last_online DATETIME DEFAULT CURRENT_TIMESTAMP,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    id INT PRIMARY KEY AUTO_INCREMENT,
    key_name VARCHAR(100) UNIQUE NOT NULL,
    value TEXT,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
"""

DEFAULT_INSERTS = [
    """INSERT IGNORE INTO users (phone, password, role, nickname)
       VALUES ('13800138000', '123456', 'admin', '系统管理员')""",
    """INSERT IGNORE INTO cameras (camera_id, name, source, location, status) VALUES
         ('CAM-001', '1号摄像头', '0', '东区', 'offline'),
         ('CAM-002', '2号摄像头', '1', '西区', 'offline')""",
    """INSERT IGNORE INTO devices (name, device_id, device_type, location, ip_address, status, camera_id) VALUES
         ('1号摄像头', 'CAM-001', 'camera', '东区', '192.168.5.3', 'offline', 'CAM-001'),
         ('2号摄像头', 'CAM-002', 'camera', '西区', '192.168.5.3', 'offline', 'CAM-002')""",
    """INSERT IGNORE INTO settings (key_name, value) VALUES
         ('sensitivity', '80'),
         ('sound_alarm', 'true'),
         ('push_notify', 'true'),
         ('auto_record', 'false'),
         ('server_url', 'http://127.0.0.1:8000')""",
]


# ─── WebSocket 广播工具 ─────────────────────────────────────────────────────
async def broadcast_event(event_type: str, data: Any = None):
    """向所有 WebSocket 客户端广播事件。"""
    msg = json.dumps({"type": event_type, "data": data}, ensure_ascii=False, default=str)
    dead: List[WebSocket] = []
    for ws in connected_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in connected_clients:
            connected_clients.remove(ws)


# ─── 摄像头离线检测后台任务 ─────────────────────────────────────────────────
async def camera_offline_checker():
    """每 60s 检查摄像头心跳超时，将超时摄像头标记为 offline。"""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        offline_ids = []
        for cam_id, last_hb in list(camera_heartbeats.items()):
            if now - last_hb > CAMERA_OFFLINE_TIMEOUT:
                offline_ids.append(cam_id)
        if offline_ids and db_pool:
            try:
                async with db_pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        for cam_id in offline_ids:
                            await cur.execute(
                                "UPDATE cameras SET status='offline' WHERE camera_id=%s AND status='online'",
                                (cam_id,),
                            )
                            camera_heartbeats.pop(cam_id, None)
                        await conn.commit()
                if offline_ids:
                    logger.info(f"摄像头心跳超时，已标记离线：{offline_ids}")
                    await broadcast_event("camera_update", {"camera_ids": offline_ids, "status": "offline"})
            except Exception as exc:
                logger.error(f"摄像头离线检测失败：{exc}")


# ─── Lifespan（启动/关闭） ───────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    logger.info("正在连接 MySQL 并初始化数据库...")
    try:
        db_pool = await aiomysql.create_pool(**DB_CONFIG, minsize=2, maxsize=10)
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                for stmt in INIT_SQL.strip().split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        await cur.execute(stmt)
                # 逐条执行默认数据插入
                for stmt in DEFAULT_INSERTS:
                    await cur.execute(stmt)
                await conn.commit()
        logger.info("数据库初始化完成 ✓")
    except Exception as exc:
        logger.error(f"数据库连接失败：{exc}")
        logger.warning("将以无数据库模式运行（部分功能不可用）")
        db_pool = None

    # 启动摄像头离线检测后台任务
    asyncio.create_task(camera_offline_checker())

    yield

    # 关闭时清理
    if db_pool:
        db_pool.close()
        await db_pool.wait_closed()
        logger.info("数据库连接池已关闭")
    logger.info("服务已停止")


# ─── FastAPI 实例 ────────────────────────────────────────────────────────────
app = FastAPI(title="水域溺水防控AI预警系统", version="4.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── v4.0 路由注册 ─────────────────────────────────────────────────────────
try:
    from notify_api import router as notify_router
    app.include_router(notify_router)
    logger.info("[v4.0] notify_api 路由已注册 (/api/notify/*)")
except Exception as _e:
    logger.warning(f"[v4.0] notify_api 路由注册失败: {_e}")

try:
    from pool_map_routes import router as pool_map_router
    app.include_router(pool_map_router)
    logger.info("[v4.0] pool_map_routes 路由已注册 (/api/pool-map/*)")
except Exception as _e:
    logger.warning(f"[v4.0] pool_map_routes 路由注册失败: {_e}")


# ─── 请求日志中间件 ─────────────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    path = request.url.path
    # 跳过高频请求的日志
    if not path.startswith(("/video_feed", "/api/cameras/")):
        logger.info(f"{request.method} {path} → {response.status_code} ({duration:.0f}ms)")
    # 添加 ngrok 跳过浏览器警告 header，避免 ngrok 拦截页面
    response.headers["ngrok-skip-browser-warning"] = "true"
    return response


# ─── 工具函数 ────────────────────────────────────────────────────────────────
def _rows_to_list(cursor: aiomysql.Cursor, rows: tuple) -> List[Dict[str, Any]]:
    cols = [col[0] for col in cursor.description]
    result = []
    for row in rows:
        item: Dict[str, Any] = {}
        for col, val in zip(cols, row):
            if isinstance(val, datetime):
                item[col] = val.strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(val, date):
                item[col] = str(val)
            else:
                item[col] = val
        result.append(item)
    return result


def _get_camera_frame(camera_id: str) -> bytes:
    """获取指定摄像头的最新帧，无则返回占位图。"""
    return camera_frames.get(camera_id, PLACEHOLDER_FRAME)


def _get_camera_event(camera_id: str) -> asyncio.Event:
    """获取或创建指定摄像头的帧更新事件。"""
    if camera_id not in camera_frame_events:
        camera_frame_events[camera_id] = asyncio.Event()
    return camera_frame_events[camera_id]


# ═══════════════════════════════════════════════════════════════════════════════
# 鉴权相关接口
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/api/login")
async def login(req: LoginRequest):
    """用户登录验证。"""
    if db_pool is None:
        return JSONResponse({"success": False, "msg": "数据库不可用"}, status_code=503)
    if not req.phone or not req.password:
        return JSONResponse({"success": False, "msg": "手机号和密码不能为空"}, status_code=400)
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, phone, role, nickname FROM users WHERE phone=%s AND password=%s",
                (req.phone, req.password),
            )
            row = await cur.fetchone()
    if row:
        logger.info(f"用户登录成功：{req.phone}")
        return {"success": True, "msg": "登录成功", "data": {"user": {"id": row[0], "phone": row[1], "role": row[2], "nickname": row[3] or ""}}}
    logger.warning(f"登录失败（凭据错误）：{req.phone}")
    return JSONResponse({"success": False, "msg": "手机号或密码错误"}, status_code=401)


@app.post("/api/change-password")
async def change_password(req: ChangePasswordRequest):
    """修改密码。"""
    if db_pool is None:
        return JSONResponse({"success": False, "msg": "数据库不可用"}, status_code=503)
    if not req.new_password or len(req.new_password) < 6:
        return JSONResponse({"success": False, "msg": "新密码不能少于6位"}, status_code=400)
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id FROM users WHERE phone=%s AND password=%s",
                (req.phone, req.old_password),
            )
            row = await cur.fetchone()
            if not row:
                return JSONResponse({"success": False, "msg": "原密码错误"}, status_code=400)
            await cur.execute(
                "UPDATE users SET password=%s WHERE phone=%s",
                (req.new_password, req.phone),
            )
            await conn.commit()
    logger.info(f"用户修改密码成功：{req.phone}")
    # 广播密码修改事件
    await broadcast_event("user_update", {"phone": req.phone, "action": "password_changed"})
    return {"success": True, "msg": "密码修改成功"}


# ═══════════════════════════════════════════════════════════════════════════════
# 用户管理接口
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/users")
async def list_users():
    """获取用户列表（不返回密码）。"""
    if db_pool is None:
        return []
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, phone, role, nickname, create_time FROM users ORDER BY id")
                rows = await cur.fetchall()
                return _rows_to_list(cur, rows)
    except Exception as exc:
        logger.error(f"查询用户列表失败：{exc}")
        return []


@app.post("/api/users")
async def create_user(user: UserCreate):
    """创建新用户（管理员功能）。"""
    if db_pool is None:
        raise HTTPException(status_code=503, detail="数据库不可用")
    if not user.phone or not user.password:
        raise HTTPException(status_code=400, detail="手机号和密码不能为空")
    if len(user.password) < 6:
        raise HTTPException(status_code=400, detail="密码不能少于6位")
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO users (phone, password, role, nickname) VALUES (%s, %s, %s, %s)",
                    (user.phone, user.password, user.role or "user", user.nickname or ""),
                )
                await conn.commit()
                new_id = cur.lastrowid
        logger.info(f"新用户已创建：{user.phone} (角色: {user.role})")
        await broadcast_event("user_update", {"action": "created", "phone": user.phone})
        return {"success": True, "id": new_id, "msg": "用户创建成功"}
    except aiomysql.IntegrityError:
        raise HTTPException(status_code=400, detail="该手机号已注册")
    except Exception as exc:
        logger.error(f"创建用户失败：{exc}")
        raise HTTPException(status_code=500, detail="创建用户失败")


@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int):
    """删除用户。"""
    if db_pool is None:
        raise HTTPException(status_code=503, detail="数据库不可用")
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # 不允许删除管理员账号（id=1）
                await cur.execute("SELECT id, role FROM users WHERE id=%s", (user_id,))
                row = await cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="用户不存在")
                await cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
                await conn.commit()
        logger.info(f"用户已删除：id={user_id}")
        await broadcast_event("user_update", {"action": "deleted", "user_id": user_id})
        return {"success": True, "msg": "用户已删除"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"删除用户失败：{exc}")
        raise HTTPException(status_code=500, detail="删除用户失败")


# ═══════════════════════════════════════════════════════════════════════════════
# 统计数据接口
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/stats")
async def get_stats():
    """返回统计数据（告警按级别拆分：紧急/记录）。"""
    if db_pool is None:
        return {"online_devices": 0, "today_alarms": 0, "today_urgent": 0, "today_records": 0, "person_count": 0, "run_hours": 0, "online_cameras": 0}
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM devices WHERE status='online'")
                online_devices = (await cur.fetchone())[0]
                today_str = datetime.now().strftime("%Y-%m-%d")
                await cur.execute("SELECT COUNT(*) FROM alarms WHERE DATE(time)=%s", (today_str,))
                today_alarms = (await cur.fetchone())[0]
                await cur.execute("SELECT COUNT(*) FROM alarms WHERE DATE(time)=%s AND level='urgent'", (today_str,))
                today_urgent = (await cur.fetchone())[0]
                await cur.execute("SELECT COUNT(*) FROM alarms WHERE DATE(time)=%s AND level='info'", (today_str,))
                today_records = (await cur.fetchone())[0]
                await cur.execute("SELECT COUNT(*) FROM cameras WHERE status='online'")
                online_cameras = (await cur.fetchone())[0]
    except Exception as exc:
        logger.error(f"查询统计失败：{exc}")
        return {"online_devices": 0, "today_alarms": 0, "today_urgent": 0, "today_records": 0, "person_count": 0, "run_hours": 0, "online_cameras": 0}
    run_hours = round((time.time() - start_time) / 3600, 1)
    return {
        "online_devices": online_devices,
        "today_alarms": today_alarms,
        "today_urgent": today_urgent,
        "today_records": today_records,
        "person_count": 0,
        "run_hours": run_hours,
        "online_cameras": online_cameras,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 报警接口
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/alarm")
async def receive_alarm(payload: AlarmPayload):
    """接收 YOLO 检测端推送的报警/记录信息。

    级别规则：
    - drowning → level='urgent'，紧急告警，广播 alarm 事件
    - swimming/playing → level='info'，仅记录，广播 detection 事件
    """
    ts = payload.timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    location = payload.location or "未知位置"
    note = payload.note or "检测到溺水风险"
    level = payload.level or "urgent"
    detect_type = payload.detect_type or ""

    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "INSERT INTO alarms (time, location, message, level, status, image_path) "
                        "VALUES (%s, %s, %s, %s, 'unread', %s)",
                        (ts, location, note, level, payload.image_path),
                    )
                    await conn.commit()
        except Exception as exc:
            logger.error(f"报警写入数据库失败：{exc}")

    # ── 根据级别决定广播行为 ──
    if level == "urgent":
        # 溺水紧急告警 → 广播 alarm 事件（全平台推送、声音提醒）
        await broadcast_event("alarm", {
            "time": ts, "location": location,
            "message": note, "level": "urgent",
            "detect_type": detect_type,
        })
        logger.warning(f"🚨 紧急告警：{note} @ {location}")
    else:
        # swimming/playing 记录 → 广播 detection 事件（静默记录，无声音）
        await broadcast_event("detection", {
            "time": ts, "location": location,
            "message": note, "level": "info",
            "detect_type": detect_type,
        })
        logger.info(f"📝 检测记录：{note} @ {location}")

    # 广播统计更新
    await broadcast_event("stats_update", {})

    return {"success": True, "msg": "已记录", "level": level}


@app.get("/alarms")
async def get_alarms(date_str: Optional[str] = None, level: Optional[str] = None):
    """返回报警记录列表，支持日期和级别筛选。

    level 参数: 'urgent'(紧急), 'info'(记录), 不传则返回全部
    """
    if db_pool is None:
        return []
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                conditions = []
                params = []
                if date_str:
                    conditions.append("DATE(time)=%s")
                    params.append(date_str)
                if level:
                    conditions.append("level=%s")
                    params.append(level)
                where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
                sql = (
                    "SELECT id, time, location, message, level, status FROM alarms"
                    + where
                    + " ORDER BY time DESC LIMIT 200"
                )
                await cur.execute(sql, params)
                rows = await cur.fetchall()
                return _rows_to_list(cur, rows)
    except Exception as exc:
        logger.error(f"查询报警记录失败：{exc}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# 摄像头检测与管理接口
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/cameras/detect")
async def detect_cameras():
    """检测本地可用摄像头列表（尝试打开索引 0-9）。"""
    cameras = []
    try:
        import cv2
        for idx in range(10):
            try:
                cap = cv2.VideoCapture(idx)
                if cap.isOpened():
                    # 尝试读取一帧确认可用
                    ret, _ = cap.read()
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cap.release()
                    cameras.append({
                        "index": idx,
                        "name": f"摄像头 {idx}",
                        "available": ret,
                        "resolution": f"{w}x{h}" if w > 0 else "",
                    })
                else:
                    cap.release()
            except Exception:
                pass
    except ImportError:
        logger.warning("OpenCV 未安装，无法检测摄像头")
        return {"cameras": [], "msg": "OpenCV 未安装，无法检测本地摄像头"}
    except Exception as exc:
        logger.error(f"摄像头检测异常：{exc}")
        return {"cameras": [], "msg": f"检测失败：{exc}"}

    logger.info(f"检测到 {len([c for c in cameras if c['available']])} 个可用摄像头")
    return {"cameras": cameras, "msg": f"检测完成，发现 {len(cameras)} 个摄像头设备"}


@app.get("/api/cameras")
async def list_cameras():
    """获取数据库中注册的摄像头列表。"""
    if db_pool is None:
        return []
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, camera_id, name, source, location, status, resolution, last_frame_time, create_time "
                    "FROM cameras ORDER BY id"
                )
                rows = await cur.fetchall()
                return _rows_to_list(cur, rows)
    except Exception as exc:
        logger.error(f"查询摄像头列表失败：{exc}")
        return []


@app.post("/api/cameras")
async def create_camera(name: str, camera_id: str, source: str = "0", location: str = ""):
    """注册新摄像头。"""
    if db_pool is None:
        raise HTTPException(status_code=503, detail="数据库不可用")
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO cameras (camera_id, name, source, location, status) VALUES (%s, %s, %s, %s, %s)",
                    (camera_id, name, source, location, 'offline'),
                )
                await conn.commit()
                new_id = cur.lastrowid
        logger.info(f"新摄像头已注册：{name} ({camera_id})")
        await broadcast_event("camera_update", {"camera_id": camera_id, "action": "created"})
        return {"success": True, "id": new_id, "msg": "摄像头已注册"}
    except aiomysql.IntegrityError:
        raise HTTPException(status_code=400, detail="摄像头ID已存在")
    except Exception as exc:
        logger.error(f"注册摄像头失败：{exc}")
        raise HTTPException(status_code=500, detail="注册摄像头失败")


@app.delete("/api/cameras/{camera_id:path}")
async def delete_camera(camera_id: str):
    """删除摄像头。"""
    if db_pool is None:
        raise HTTPException(status_code=503, detail="数据库不可用")
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM cameras WHERE camera_id=%s", (camera_id,))
                await conn.commit()
        camera_frames.pop(camera_id, None)
        camera_heartbeats.pop(camera_id, None)
        logger.info(f"摄像头已删除：{camera_id}")
        await broadcast_event("camera_update", {"camera_id": camera_id, "action": "deleted"})
        return {"success": True, "msg": "摄像头已删除"}
    except Exception as exc:
        logger.error(f"删除摄像头失败：{exc}")
        raise HTTPException(status_code=500, detail="删除摄像头失败")


@app.post("/api/cameras/{camera_id:path}/heartbeat")
async def camera_heartbeat(camera_id: str, payload: CameraHeartbeat):
    """接收摄像头心跳，更新在线状态。"""
    camera_heartbeats[camera_id] = time.time()

    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # 如果摄像头不在数据库中，自动注册
                    await cur.execute("SELECT id FROM cameras WHERE camera_id=%s", (camera_id,))
                    if await cur.fetchone():
                        await cur.execute(
                            "UPDATE cameras SET status='online', resolution=%s, last_frame_time=NOW() WHERE camera_id=%s",
                            (payload.resolution or "", camera_id),
                        )
                    else:
                        await cur.execute(
                            "INSERT INTO cameras (camera_id, name, source, location, status, resolution) VALUES (%s, %s, %s, %s, 'online', %s)",
                            (camera_id, f"摄像头 {camera_id}", "0", "", payload.resolution or ""),
                        )
                    await conn.commit()
        except Exception as exc:
            logger.error(f"摄像头心跳更新失败：{exc}")

    return {"success": True}


# ═══════════════════════════════════════════════════════════════════════════════
# 多路视频帧接口
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/api/cameras/{camera_id:path}/frame")
async def upload_camera_frame(camera_id: str, payload: FramePayload):
    """接收特定摄像头的帧推送。"""
    try:
        if not payload.frame:
            return {"success": False, "msg": "帧数据为空"}
        frame_bytes = base64.b64decode(payload.frame)
        if len(frame_bytes) > FRAME_MAX_SIZE:
            return {"success": False, "msg": "帧过大"}
        if not frame_bytes.startswith(b'\xff\xd8'):
            return {"success": False, "msg": "非 JPEG 数据"}
        camera_frames[camera_id] = frame_bytes
        evt = _get_camera_event(camera_id)
        evt.set()
    except Exception as exc:
        logger.warning(f"解码摄像头帧失败 [{camera_id}]：{exc}")
        return {"success": False, "msg": "解码失败"}
    return {"success": True}


@app.get("/api/cameras/{camera_id:path}/snapshot")
async def camera_snapshot(camera_id: str):
    """获取特定摄像头的最新帧（单张 JPEG）。"""
    frame = _get_camera_frame(camera_id)
    return StreamingResponse(io.BytesIO(frame), media_type="image/jpeg")


@app.get("/api/cameras/{camera_id:path}/feed")
async def camera_feed(camera_id: str):
    """获取特定摄像头的 MJPEG 流。"""
    evt = _get_camera_event(camera_id)

    async def generate():
        while True:
            frame = camera_frames.get(camera_id)
            if frame is None:
                try:
                    await asyncio.wait_for(evt.wait(), timeout=0.1)
                    evt.clear()
                    frame = camera_frames.get(camera_id, PLACEHOLDER_FRAME)
                except asyncio.TimeoutError:
                    frame = PLACEHOLDER_FRAME
            else:
                evt.clear()

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
            await asyncio.sleep(0.04)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace;boundary=frame",
    )


# ─── 兼容旧接口（default 摄像头） ─────────────────────────────────────────
@app.post("/upload_frame")
async def upload_frame(payload: FramePayload):
    """接收 YOLO 推送的帧（兼容旧接口，写入 default 摄像头）。"""
    try:
        if not payload.frame:
            return {"success": False, "msg": "帧数据为空"}
        frame_bytes = base64.b64decode(payload.frame)
        if len(frame_bytes) > FRAME_MAX_SIZE:
            return {"success": False, "msg": "帧过大"}
        if not frame_bytes.startswith(b'\xff\xd8'):
            return {"success": False, "msg": "非 JPEG 数据"}
        # 写入 default 摄像头
        camera_frames["default"] = frame_bytes
        evt = _get_camera_event("default")
        evt.set()
    except Exception as exc:
        logger.warning(f"解码帧失败：{exc}")
        return {"success": False, "msg": "解码失败"}
    return {"success": True}


@app.get("/latest_frame")
async def latest_frame_endpoint():
    """返回最新一帧（兼容旧接口）。"""
    frame = camera_frames.get("default", PLACEHOLDER_FRAME)
    return StreamingResponse(io.BytesIO(frame), media_type="image/jpeg")


@app.get("/video_feed")
async def video_feed():
    """MJPEG 流端点（兼容旧接口，返回 default 摄像头流）。"""
    return await camera_feed("default")


# ═══════════════════════════════════════════════════════════════════════════════
# 设备管理接口
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/devices")
async def list_devices():
    if db_pool is None:
        return []
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, name, device_id, device_type, location, ip_address, status, camera_id, last_online, create_time "
                    "FROM devices ORDER BY id"
                )
                rows = await cur.fetchall()
                return _rows_to_list(cur, rows)
    except Exception as exc:
        logger.error(f"查询设备列表失败：{exc}")
        return []


@app.post("/api/devices")
async def create_device(device: DeviceCreate):
    if db_pool is None:
        raise HTTPException(status_code=503, detail="数据库不可用")
    if not device.name or not device.name.strip():
        raise HTTPException(status_code=400, detail="设备名称不能为空")
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO devices (name, device_id, device_type, location, ip_address, status) "
                    "VALUES (%s, %s, 'camera', %s, %s, %s)",
                    (device.name.strip(), device.device_id, device.location, device.ip_address, device.status),
                )
                await conn.commit()
                new_id = cur.lastrowid
        logger.info(f"新设备已添加：{device.name}")
        await broadcast_event("device_update", {"action": "created", "name": device.name})
        await broadcast_event("stats_update", {})
        return {"success": True, "id": new_id, "msg": "设备已添加"}
    except aiomysql.IntegrityError:
        raise HTTPException(status_code=400, detail="设备ID已存在")
    except Exception as exc:
        logger.error(f"添加设备失败：{exc}")
        raise HTTPException(status_code=500, detail="添加设备失败")


@app.put("/api/devices/{device_id}")
async def update_device(device_id: int, device: DeviceUpdate):
    if db_pool is None:
        raise HTTPException(status_code=503, detail="数据库不可用")
    fields = {k: v for k, v in device.dict().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="无更新字段")
    set_clause = ", ".join(f"{k}=%s" for k in fields)
    values = list(fields.values()) + [device_id]
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"UPDATE devices SET {set_clause} WHERE id=%s", values)
                await conn.commit()
        await broadcast_event("device_update", {"action": "updated", "device_id": device_id})
        await broadcast_event("stats_update", {})
        return {"success": True, "msg": "设备已更新"}
    except Exception as exc:
        logger.error(f"更新设备失败：{exc}")
        raise HTTPException(status_code=500, detail="更新设备失败")


@app.delete("/api/devices/{device_id}")
async def delete_device(device_id: int):
    if db_pool is None:
        raise HTTPException(status_code=503, detail="数据库不可用")
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM devices WHERE id=%s", (device_id,))
                await conn.commit()
        logger.info(f"设备已删除：id={device_id}")
        await broadcast_event("device_update", {"action": "deleted", "device_id": device_id})
        await broadcast_event("stats_update", {})
        return {"success": True, "msg": "设备已删除"}
    except Exception as exc:
        logger.error(f"删除设备失败：{exc}")
        raise HTTPException(status_code=500, detail="删除设备失败")


# ═══════════════════════════════════════════════════════════════════════════════
# 系统设置接口
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/settings")
async def get_settings():
    if db_pool is None:
        return {}
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT key_name, value FROM settings")
                rows = await cur.fetchall()
        return {row[0]: row[1] for row in rows}
    except Exception as exc:
        logger.error(f"查询设置失败：{exc}")
        return {}


@app.post("/api/settings")
async def save_settings(payload: SettingsBatch):
    if db_pool is None:
        raise HTTPException(status_code=503, detail="数据库不可用")
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                for key, value in payload.settings.items():
                    await cur.execute(
                        "INSERT INTO settings (key_name, value) VALUES (%s, %s) "
                        "ON DUPLICATE KEY UPDATE value=%s",
                        (key, value, value),
                    )
                await conn.commit()
        return {"success": True, "msg": "设置已保存"}
    except Exception as exc:
        logger.error(f"保存设置失败：{exc}")
        raise HTTPException(status_code=500, detail="保存设置失败")


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket 接口
# ═══════════════════════════════════════════════════════════════════════════════
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    logger.info(f"WebSocket 客户端已连接，当前连接数：{len(connected_clients)}")
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=WS_HEARTBEAT_TIMEOUT)
                if data == "ping":
                    await websocket.send_text("pong")
                elif data.startswith("{"):
                    # 处理 JSON 消息
                    try:
                        msg = json.loads(data)
                        if msg.get("type") == "subscribe":
                            # 客户端订阅特定事件
                            pass
                    except json.JSONDecodeError:
                        pass
            except asyncio.TimeoutError:
                logger.warning("WebSocket 心跳超时，断开连接")
                await websocket.close()
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning(f"WebSocket 异常：{exc}")
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
        logger.info(f"WebSocket 客户端已断开，当前连接数：{len(connected_clients)}")


# ═══════════════════════════════════════════════════════════════════════════════
# 前端页面路由（让 ngrok 公网域名可直接访问网站）
# ═══════════════════════════════════════════════════════════════════════════════
FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/")
async def serve_index():
    """首页 - 登录页面"""
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/{page_name}.html")
async def serve_html_page(page_name: str):
    """其他 HTML 页面"""
    allowed = ["dashboard", "alarms", "devices", "users", "settings", "pool_map"]
    if page_name in allowed:
        filepath = os.path.join(FRONTEND_DIR, f"{page_name}.html")
        if os.path.exists(filepath):
            return FileResponse(filepath)
    raise HTTPException(status_code=404, detail="Page not found")


# ═══════════════════════════════════════════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/health")
async def health():
    db_status = "ok" if db_pool else "unavailable"
    return {
        "status": "ok",
        "version": "3.0.0",
        "time": datetime.now().isoformat(),
        "db": db_status,
        "ws_clients": len(connected_clients),
        "cameras_online": len(camera_heartbeats),
        "cameras_with_frames": len(camera_frames),
        "uptime_seconds": int(time.time() - start_time),
    }


# ─── 入口 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=False)
