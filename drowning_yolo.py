"""
水域溺水防控AI预警系统 - YOLO 检测模块
使用 YOLOv8 实时检测视频流中的溺水行为
v3.0 — 多摄像头支持、心跳机制、帧推送格式变更、向下兼容
"""
import argparse
import base64
import logging
import os
import signal
import sys
import time
from datetime import datetime
from typing import Optional

import cv2
import numpy as np
import requests

# ─── 日志配置 ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── 命令行参数解析 ───────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="水域溺水防控AI预警系统 - 检测模块")
parser.add_argument("--camera-id", default="CAM-001", help="摄像头ID")
parser.add_argument("--source", default=None, help="视频源（摄像头索引/RTSP地址/视频文件路径）")
parser.add_argument("--model", default="best.pt", help="YOLO模型路径")
parser.add_argument("--backend", default="http://127.0.0.1:8000", help="后端地址")
parser.add_argument("--location", default="默认位置", help="设备位置")
parser.add_argument("--track", default="True", help="是否启用多目标跟踪（True/False）")
parser.add_argument("--trajectory-len", default="30", help="轨迹显示点数", type=int)
args, _ = parser.parse_known_args()

# ─── 配置常量 ─────────────────────────────────────────────────────────────
BACKEND_URL: str = os.getenv("BACKEND_URL", args.backend)
VIDEO_SOURCE: str = os.getenv("VIDEO_SOURCE", args.source if args.source is not None else "0")
ALARM_CONFIDENCE: float = float(os.getenv("ALARM_CONFIDENCE", "0.6"))
MODEL_PATH: str = os.getenv("MODEL_PATH", args.model)
DEVICE_LOCATION: str = os.getenv("DEVICE_LOCATION", args.location)
CAMERA_ID: str = os.getenv("CAMERA_ID", args.camera_id)
PUSH_FPS: int = int(os.getenv("PUSH_FPS", "5"))             # 帧推送帧率（每秒推送次数）
ALARM_COOLDOWN: float = float(os.getenv("ALARM_COOLDOWN", "5.0"))   # drowning 报警冷却时间（秒）
RECORD_COOLDOWN: float = float(os.getenv("RECORD_COOLDOWN", "30.0")) # swimming/playing 记录冷却时间（秒）
JPEG_QUALITY: int = int(os.getenv("JPEG_QUALITY", "80"))    # JPEG 编码质量 (1-100)
RECONNECT_DELAY: float = float(os.getenv("RECONNECT_DELAY", "2.0"))  # 重连延迟（秒）
MAX_RECONNECT_ATTEMPTS: int = int(os.getenv("MAX_RECONNECT_ATTEMPTS", "10"))  # 最大重连次数
HEARTBEAT_INTERVAL: float = float(os.getenv("HEARTBEAT_INTERVAL", "10.0"))  # 心跳间隔（秒）
ENABLE_TRACK: bool = os.getenv("ENABLE_TRACK", args.track).lower() in ("true", "1", "yes")
TRAJECTORY_LEN: int = int(os.getenv("TRAJECTORY_LEN", str(args.trajectory_len)))  # 轨迹显示点数

# ─── 全局退出标志 ──────────────────────────────────────────────────────────
_shutdown = False


def _signal_handler(sig, frame):
    """处理 Ctrl+C 信号，优雅退出。"""
    global _shutdown
    logger.info(f"收到信号 {sig}，正在优雅退出...")
    _shutdown = True


# 注册信号处理
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def encode_frame_base64(frame: np.ndarray, quality: int = JPEG_QUALITY) -> str:
    """将 OpenCV BGR 帧编码为 base64 JPEG 字符串。

    Args:
        frame: OpenCV BGR numpy 数组。
        quality: JPEG 编码质量 (1-100)。

    Returns:
        base64 编码的 JPEG 字符串。
    """
    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buffer.tobytes()).decode("utf-8")


def push_frame(frame: np.ndarray, camera_id: str) -> bool:
    """推送视频帧到后端特定摄像头接口，同时向下兼容旧接口。

    Args:
        frame: OpenCV BGR numpy 数组。
        camera_id: 摄像头ID。

    Returns:
        True 推送成功，False 失败。
    """
    try:
        b64 = encode_frame_base64(frame)
        # 新接口：按摄像头ID推送
        resp = requests.post(
            f"{BACKEND_URL}/api/cameras/{camera_id}/frame",
            json={"frame": b64},
            timeout=2.0,
        )
        new_ok = resp.status_code == 200
        if not new_ok:
            logger.warning(f"推帧(新接口)响应异常：HTTP {resp.status_code}")

        # 旧接口：向下兼容 /upload_frame
        try:
            resp_legacy = requests.post(
                f"{BACKEND_URL}/upload_frame",
                json={"frame": b64},
                timeout=2.0,
            )
            legacy_ok = resp_legacy.status_code == 200
            if not legacy_ok:
                logger.warning(f"推帧(旧接口)响应异常：HTTP {resp_legacy.status_code}")
        except Exception:
            legacy_ok = False

        return new_ok or legacy_ok
    except requests.ConnectionError:
        logger.warning("推帧失败：后端连接被拒绝（请检查 backend.py 是否运行）")
        return False
    except requests.Timeout:
        logger.warning("推帧超时")
        return False
    except Exception as exc:
        logger.warning(f"推帧失败：{exc}")
        return False


def send_heartbeat(camera_id: str, status: str = "online", resolution: str = "") -> bool:
    """向后台发送摄像头心跳。

    Args:
        camera_id: 摄像头ID。
        status: 心跳状态（online / offline）。
        resolution: 视频分辨率信息。

    Returns:
        True 心跳成功，False 失败。
    """
    try:
        payload = {"status": status}
        if resolution:
            payload["resolution"] = resolution
        resp = requests.post(
            f"{BACKEND_URL}/api/cameras/{camera_id}/heartbeat",
            json=payload,
            timeout=3.0,
        )
        if resp.status_code == 200:
            logger.debug(f"心跳已发送：{camera_id} -> {status}")
            return True
        else:
            logger.warning(f"心跳响应异常：HTTP {resp.status_code}")
            return False
    except requests.ConnectionError:
        logger.warning("心跳发送失败：后端连接被拒绝")
        return False
    except requests.Timeout:
        logger.warning("心跳发送超时")
        return False
    except Exception as exc:
        logger.warning(f"心跳发送失败：{exc}")
        return False


def push_alarm(
    timestamp: str,
    location: str,
    camera_id: str,
    level: str = "urgent",
    detect_type: str = "drowning",
    image_path: Optional[str] = None,
    note: str = "检测到溺水风险",
) -> bool:
    """向后端推送报警/记录信息。

    Args:
        timestamp: 报警时间戳字符串（%Y-%m-%d %H:%M:%S）。
        location: 报警发生位置。
        camera_id: 摄像头ID。
        level: 告警级别 — 'urgent'(紧急/drowning) 或 'info'(记录/swimming/playing)。
        detect_type: 检测类别 — 'drowning'/'swimming'/'playing'。
        image_path: 截图路径（可选）。
        note: 报警描述信息。

    Returns:
        True 推送成功，False 失败。
    """
    try:
        payload = {
            "timestamp": timestamp,
            "location": location,
            "camera_id": camera_id,
            "level": level,
            "detect_type": detect_type,
            "image_path": image_path,
            "note": note,
        }
        resp = requests.post(
            f"{BACKEND_URL}/alarm",
            json=payload,
            timeout=3.0,
        )
        if resp.status_code == 200:
            logger.info(f"报警已推送：{timestamp} @ {location} (camera={camera_id})")
            return True
        else:
            logger.warning(f"报警推送响应异常：HTTP {resp.status_code}")
            return False
    except requests.ConnectionError:
        logger.warning("报警推送失败：后端连接被拒绝")
        return False
    except requests.Timeout:
        logger.warning("报警推送超时")
        return False
    except Exception as exc:
        logger.warning(f"报警推送失败：{exc}")
        return False


def save_alarm_snapshot(frame: np.ndarray, timestamp: str, camera_id: str) -> Optional[str]:
    """保存报警截图到本地。

    Args:
        frame: 当前帧。
        timestamp: 时间戳字符串（用于文件名）。
        camera_id: 摄像头ID。

    Returns:
        保存的文件路径，失败时返回 None。
    """
    try:
        save_dir = "alarm_snapshots"
        os.makedirs(save_dir, exist_ok=True)
        safe_ts = timestamp.replace(":", "-").replace(" ", "_")
        filepath = os.path.join(save_dir, f"{camera_id}_alarm_{safe_ts}.jpg")
        cv2.imwrite(filepath, frame)
        return filepath
    except Exception as exc:
        logger.warning(f"截图保存失败：{exc}")
        return None


def check_backend_health() -> bool:
    """检查后端是否在线。"""
    try:
        resp = requests.get(f"{BACKEND_URL}/health", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


def open_video_source(src) -> Optional[cv2.VideoCapture]:
    """打开视频源，返回 VideoCapture 对象。"""
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        return None
    # 优化缓冲区大小
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def get_video_resolution(cap: cv2.VideoCapture) -> str:
    """获取视频源的分辨率字符串。

    Args:
        cap: VideoCapture 对象。

    Returns:
        分辨率字符串，如 "1920x1080"。
    """
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return f"{w}x{h}"
    except Exception:
        return "unknown"


def run_detection() -> None:
    """主检测循环：读取视频流，执行 YOLO 检测，推送帧与报警，上报心跳。"""
    global _shutdown

    # ── 启动日志 ──────────────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("水域溺水防控AI预警系统 - 检测模块 v3.0")
    logger.info(f"  摄像头ID：{CAMERA_ID}")
    logger.info(f"  后端地址：{BACKEND_URL}")
    logger.info(f"  视频源：{VIDEO_SOURCE}")
    logger.info(f"  模型路径：{MODEL_PATH}")
    logger.info(f"  报警阈值：{ALARM_CONFIDENCE}")
    logger.info(f"  推帧帧率：{PUSH_FPS} fps")
    logger.info("=" * 50)

    if not check_backend_health():
        logger.warning("后端未响应，请确认 backend.py 已启动！")
        logger.warning("检测模块将在后端可用后继续运行...")

    # ── 尝试加载 YOLO 模型 ─────────────────────────────────────────────
    model = None
    try:
        from ultralytics import YOLO  # type: ignore
        if os.path.exists(MODEL_PATH):
            model = YOLO(MODEL_PATH)
            logger.info(f"YOLO 模型已加载：{MODEL_PATH} ✓")
        else:
            logger.warning(f"模型文件不存在：{MODEL_PATH}，将以无检测模式运行（仅推流）")
    except ImportError:
        logger.warning("ultralytics 未安装，将以无检测模式运行（仅推流）")
    except Exception as exc:
        logger.warning(f"YOLO 模型加载异常：{exc}，将以无检测模式运行")

    # ── 初始化多目标跟踪器 ─────────────────────────────────────────────
    tracker = None
    traj_buffer = None
    if ENABLE_TRACK:
        try:
            from trackers import Tracker, TrajectoryBuffer
            tracker = Tracker(max_age=30, min_hits=3, iou_threshold=0.3)
            traj_buffer = TrajectoryBuffer(max_length=100)
            logger.info("DeepSORT 多目标跟踪已启用 ✓")
        except ImportError:
            logger.warning("trackers 模块未找到，跟踪功能已禁用")

    # ── 打开视频源 ─────────────────────────────────────────────────────
    src = int(VIDEO_SOURCE) if VIDEO_SOURCE.isdigit() else VIDEO_SOURCE
    cap = open_video_source(src)
    if cap is None:
        logger.error(f"无法打开视频源：{VIDEO_SOURCE}")
        # 启动失败也发送 offline 心跳
        send_heartbeat(CAMERA_ID, status="offline")
        return

    logger.info(f"视频源已打开：{VIDEO_SOURCE} ✓")

    # 获取分辨率用于心跳上报
    resolution = get_video_resolution(cap)
    logger.info(f"视频分辨率：{resolution}")

    # ── 启动时发送 online 心跳 ────────────────────────────────────────
    send_heartbeat(CAMERA_ID, status="online", resolution=resolution)

    frame_interval: float = 1.0 / PUSH_FPS   # 推帧间隔（秒）
    heartbeat_interval: float = HEARTBEAT_INTERVAL  # 心跳间隔（秒）
    last_push_time: float = 0.0
    last_alarm_time: float = 0.0
    last_heartbeat_time: float = time.time()  # 记录上次心跳时间
    frame_count: int = 0
    reconnect_attempts: int = 0

    try:
        while not _shutdown:
            ret, frame = cap.read()
            if not ret:
                reconnect_attempts += 1
                if reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                    logger.error(f"连续 {MAX_RECONNECT_ATTEMPTS} 次读取失败，退出检测循环")
                    break
                logger.warning(f"读取帧失败（第 {reconnect_attempts} 次），{RECONNECT_DELAY}s 后重连...")
                time.sleep(RECONNECT_DELAY)
                cap.release()
                cap = open_video_source(src)
                if cap is None:
                    logger.error("重连失败，退出检测循环")
                    break
                # 重连后更新分辨率
                resolution = get_video_resolution(cap)
                continue

            # 重置重连计数
            reconnect_attempts = 0
            frame_count += 1

            current_time: float = time.time()
            annotated_frame: np.ndarray = frame.copy()
            alarm_triggered: bool = False
            alarm_label: str = "检测到溺水风险"
            alarm_level: str = "urgent"          # 告警级别: urgent(溺水) / info(游泳/戏水)
            detect_type: str = "drowning"         # 检测类别: drowning / swimming / playing

            # ── YOLO 推理 ──────────────────────────────────────────────
            if model is not None:
                try:
                    results = model(frame, verbose=False)

                    # 将 YOLO 检测结果转换为跟踪器输入格式
                    detections = []
                    for result in results:
                        boxes = result.boxes
                        if boxes is None:
                            continue
                        for box in boxes:
                            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                            conf = float(box.conf[0]) if box.conf is not None else 0.0
                            cls_id = int(box.cls[0]) if box.cls is not None else -1
                            detections.append([x1, y1, x2, y2, conf, cls_id])

                    # ── 多目标跟踪 ────────────────────────────────────
                    tracked_objects = []
                    if tracker is not None:
                        tracked_objects = tracker.update(detections)

                        # 更新轨迹缓冲区
                        timestamp = current_time
                        for obj in tracked_objects:
                            cx = (obj['bbox'][0] + obj['bbox'][2]) / 2
                            cy = (obj['bbox'][1] + obj['bbox'][3]) / 2
                            traj_buffer.add_point(obj['track_id'], cx, cy, timestamp)

                    # ── 绘制跟踪结果（优先使用跟踪信息）───────────────
                    if tracker is not None and tracked_objects:
                        for obj in tracked_objects:
                            tid = obj['track_id']
                            bx1, by1, bx2, by2 = [int(v) for v in obj['bbox']]
                            conf = obj['confidence']
                            cls_id = obj['class_id']

                            # 获取类别名称
                            label_name = str(cls_id)
                            for result in results:
                                if result.names and cls_id in result.names:
                                    label_name = result.names[cls_id]
                                    break
                            label_lower = label_name.lower()

                            # 根据检测类别决定边框颜色
                            if label_lower == "drowning":
                                box_color = (0, 0, 255)
                            elif label_lower == "swimming":
                                box_color = (255, 165, 0)
                            elif label_lower == "playing":
                                box_color = (0, 200, 100)
                            else:
                                box_color = (0, 255, 255)

                            # 绘制边界框
                            cv2.rectangle(annotated_frame, (bx1, by1), (bx2, by2), box_color, 2)

                            # 绘制 track_id 标签
                            label_text = f"ID:{tid} {label_name} {conf:.2f}"
                            cv2.putText(
                                annotated_frame,
                                label_text,
                                (bx1, max(by1 - 5, 0)),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.6,
                                box_color,
                                2,
                            )

                            # 绘制轨迹线（最近 N 个点）
                            traj = traj_buffer.get_trajectory(tid)
                            if len(traj) >= 2:
                                points = traj[-TRAJECTORY_LEN:]
                                for i in range(1, len(points)):
                                    pt1 = (int(points[i - 1][0]), int(points[i - 1][1]))
                                    pt2 = (int(points[i][0]), int(points[i][1]))
                                    # 越近的点颜色越亮
                                    alpha = i / len(points)
                                    color = (
                                        int(box_color[0] * alpha),
                                        int(box_color[1] * alpha),
                                        int(box_color[2] * alpha),
                                    )
                                    cv2.line(annotated_frame, pt1, pt2, color, 2)

                            # ── 溺水风险分析 ──
                            if traj_buffer is not None and label_lower == "drowning":
                                risk_score, risk_factors = traj_buffer.analyze_drowning_risk(tid)
                                if risk_score > 0.3:
                                    risk_text = f"Risk:{risk_score:.0%}"
                                    cv2.putText(
                                        annotated_frame,
                                        risk_text,
                                        (bx1, max(by1 - 25, 0)),
                                        cv2.FONT_HERSHEY_SIMPLEX,
                                        0.6,
                                        (0, 0, 255),
                                        2,
                                    )

                            # ── 分级处理 ──
                            if conf >= ALARM_CONFIDENCE:
                                alarm_triggered = True
                                if label_lower == "drowning":
                                    alarm_level = "urgent"
                                    detect_type = "drowning"
                                    alarm_label = f"⚠ 检测到溺水，置信度 {conf:.2f}"
                                elif label_lower == "swimming":
                                    alarm_level = "info"
                                    detect_type = "swimming"
                                    alarm_label = f"🏊 检测到游泳，置信度 {conf:.2f}"
                                elif label_lower == "playing":
                                    alarm_level = "info"
                                    detect_type = "playing"
                                    alarm_label = f"🤽 检测到戏水，置信度 {conf:.2f}"
                                else:
                                    alarm_level = "info"
                                    detect_type = label_lower
                                    alarm_label = f"检测到 {label_name}，置信度 {conf:.2f}"
                    else:
                        # 无跟踪器或无跟踪结果，使用原始绘制逻辑
                        for result in results:
                            boxes = result.boxes
                            if boxes is None:
                                continue
                            for box in boxes:
                                conf = float(box.conf[0]) if box.conf is not None else 0.0
                                cls_id = int(box.cls[0]) if box.cls is not None else -1
                                label = (
                                    result.names.get(cls_id, str(cls_id))
                                    if result.names else str(cls_id)
                                )
                                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())

                                label_lower = label.lower()
                                if label_lower == "drowning":
                                    box_color = (0, 0, 255)
                                elif label_lower == "swimming":
                                    box_color = (255, 165, 0)
                                elif label_lower == "playing":
                                    box_color = (0, 200, 100)
                                else:
                                    box_color = (0, 255, 255)

                                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), box_color, 2)
                                cv2.putText(
                                    annotated_frame,
                                    f"{label} {conf:.2f}",
                                    (x1, max(y1 - 5, 0)),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.6,
                                    box_color,
                                    2,
                                )

                                if conf >= ALARM_CONFIDENCE:
                                    alarm_triggered = True
                                    if label_lower == "drowning":
                                        alarm_level = "urgent"
                                        detect_type = "drowning"
                                        alarm_label = f"⚠ 检测到溺水，置信度 {conf:.2f}"
                                    elif label_lower == "swimming":
                                        alarm_level = "info"
                                        detect_type = "swimming"
                                        alarm_label = f"🏊 检测到游泳，置信度 {conf:.2f}"
                                    elif label_lower == "playing":
                                        alarm_level = "info"
                                        detect_type = "playing"
                                        alarm_label = f"🤽 检测到戏水，置信度 {conf:.2f}"
                                    else:
                                        alarm_level = "info"
                                        detect_type = label_lower
                                        alarm_label = f"检测到 {label}，置信度 {conf:.2f}"
                except Exception as exc:
                    logger.warning(f"YOLO 推理异常：{exc}")

            # ── 报警/记录推送（带分级冷却时间）──────────────────────────
            cooldown = ALARM_COOLDOWN if alarm_level == "urgent" else RECORD_COOLDOWN
            if alarm_triggered and (current_time - last_alarm_time) >= cooldown:
                last_alarm_time = current_time
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # 只有溺水(urgent)才保存截图
                snapshot_path = None
                if alarm_level == "urgent":
                    snapshot_path = save_alarm_snapshot(annotated_frame, ts, CAMERA_ID)
                push_alarm(
                    timestamp=ts,
                    location=DEVICE_LOCATION,
                    camera_id=CAMERA_ID,
                    level=alarm_level,
                    detect_type=detect_type,
                    image_path=snapshot_path,
                    note=alarm_label,
                )

            # ── 按帧率推送每一帧到后端 ──────────────────────────────────
            if (current_time - last_push_time) >= frame_interval:
                last_push_time = current_time
                push_frame(annotated_frame, CAMERA_ID)

            # ── 心跳上报（每 HEARTBEAT_INTERVAL 秒一次）───────────────
            if (current_time - last_heartbeat_time) >= heartbeat_interval:
                last_heartbeat_time = current_time
                send_heartbeat(CAMERA_ID, status="online", resolution=resolution)

            # ── 本地预览（可选） ──────────────────────────────────────
            cv2.imshow("WaterGuard Detection", annotated_frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                logger.info("用户按下 Q 键，退出检测")
                break

            # 每100帧打印一次状态
            if frame_count % 100 == 0:
                logger.info(f"运行中... 已处理 {frame_count} 帧 (camera={CAMERA_ID})")

    except KeyboardInterrupt:
        logger.info("用户中断，正在退出...")
    finally:
        # ── 退出时发送 offline 心跳 ──────────────────────────────────
        send_heartbeat(CAMERA_ID, status="offline", resolution=resolution)
        cap.release()
        cv2.destroyAllWindows()
        logger.info("检测循环已结束")
        logger.info(f"总共处理 {frame_count} 帧 (camera={CAMERA_ID})")


if __name__ == "__main__":
    run_detection()
