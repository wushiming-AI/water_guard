"""
双路视频流同步读取模块
支持可见光+红外摄像头同步采集

同步策略:
- 时间戳对齐: 按时间戳最近匹配帧
- 帧率适配: 以较低帧率为准
- 缓冲窗口: 维护帧缓冲，容忍小的时间偏移
"""

import threading
import time
import queue
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
import cv2
import numpy as np

@dataclass
class SyncedFrame:
    """同步帧对"""
    visible: Optional[np.ndarray] = None
    ir: Optional[np.ndarray] = None
    visible_timestamp: float = 0.0
    ir_timestamp: float = 0.0
    sync_timestamp: float = 0.0
    sync_quality: float = 1.0  # 同步质量 0-1


class DualStreamReader:
    """
    双路视频流读取器

    支持三种数据源:
    1. 两个独立的摄像头 (0, 1)
    2. 两个RTSP视频流
    3. 本地视频文件 + 摄像头
    """

    def __init__(self,
                 visible_source,
                 ir_source,
                 sync_window_ms: float = 100.0,
                 buffer_size: int = 30):
        """
        Args:
            visible_source: 可见光视频源 (同cv2.VideoCapture参数)
            ir_source: 红外视频源
            sync_window_ms: 同步窗口(毫秒)，此窗口内的帧视为同步
            buffer_size: 每路帧缓冲大小
        """
        self.visible_source = visible_source
        self.ir_source = ir_source
        self.sync_window_ms = sync_window_ms
        self.buffer_size = buffer_size

        self.vis_cap: Optional[cv2.VideoCapture] = None
        self.ir_cap: Optional[cv2.VideoCapture] = None

        self.vis_buffer = queue.Queue(maxsize=buffer_size)
        self.ir_buffer = queue.Queue(maxsize=buffer_size)

        self.running = False
        self._vis_thread: Optional[threading.Thread] = None
        self._ir_thread: Optional[threading.Thread] = None

    def open(self) -> bool:
        """打开双路视频流"""
        try:
            self.vis_cap = cv2.VideoCapture(self.visible_source)
            if not self.vis_cap.isOpened():
                print(f"[DualStream] Failed to open visible source: {self.visible_source}")
                return False

            self.ir_cap = cv2.VideoCapture(self.ir_source)
            if not self.ir_cap.isOpened():
                print(f"[DualStream] Failed to open IR source: {self.ir_source}")
                self.vis_cap.release()
                return False

            print(f"[DualStream] Opened dual streams:")
            print(f"  Visible: {self.visible_source} ({int(self.vis_cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(self.vis_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))})")
            print(f"  IR: {self.ir_source} ({int(self.ir_cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(self.ir_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))})")

            return True
        except Exception as e:
            print(f"[DualStream] Error opening streams: {e}")
            return False

    def start(self):
        """启动异步读取线程"""
        self.running = True
        self._vis_thread = threading.Thread(target=self._read_loop,
                                           args=(self.vis_cap, self.vis_buffer, "visible"),
                                           daemon=True)
        self._ir_thread = threading.Thread(target=self._read_loop,
                                          args=(self.ir_cap, self.ir_buffer, "ir"),
                                          daemon=True)
        self._vis_thread.start()
        self._ir_thread.start()
        print("[DualStream] Async read threads started")

    def stop(self):
        """停止异步读取"""
        self.running = False
        if self._vis_thread:
            self._vis_thread.join(timeout=2.0)
        if self._ir_thread:
            self._ir_thread.join(timeout=2.0)
        if self.vis_cap:
            self.vis_cap.release()
        if self.ir_cap:
            self.ir_cap.release()
        print("[DualStream] Stopped")

    def _read_loop(self, cap: cv2.VideoCapture, buf: queue.Queue, name: str):
        """异步读取循环"""
        frame_count = 0
        while self.running:
            ret, frame = cap.read()
            if not ret:
                print(f"[DualStream] {name} stream ended (frame {frame_count})")
                break

            timestamp = time.time()
            try:
                buf.put_nowait((timestamp, frame, frame_count))
                frame_count += 1
            except queue.Full:
                # 丢弃最旧的帧
                try:
                    buf.get_nowait()
                    buf.put_nowait((timestamp, frame, frame_count))
                    frame_count += 1
                except queue.Empty:
                    pass

    def read_synced(self, timeout: float = 1.0) -> Optional[SyncedFrame]:
        """
        读取一对同步帧

        同步逻辑:
        1. 取可见光缓冲最新帧
        2. 在红外缓冲中找时间戳最近的帧
        3. 时间差在同步窗口内 -> 返回同步帧对
        """
        try:
            vis_ts, vis_frame, _ = self.vis_buffer.get(timeout=timeout)

            # 收集红外缓冲中所有帧
            ir_frames = []
            while True:
                try:
                    ir_frames.append(self.ir_buffer.get_nowait())
                except queue.Empty:
                    break

            if not ir_frames:
                return SyncedFrame(
                    visible=vis_frame,
                    visible_timestamp=vis_ts,
                    sync_timestamp=vis_ts,
                    sync_quality=0.0  # 没有红外帧
                )

            # 找时间戳最接近的帧
            best_ir = min(ir_frames, key=lambda f: abs(f[0] - vis_ts))

            time_diff_ms = abs(best_ir[0] - vis_ts) * 1000
            quality = max(0, 1.0 - time_diff_ms / self.sync_window_ms)

            return SyncedFrame(
                visible=vis_frame,
                ir=best_ir[1],
                visible_timestamp=vis_ts,
                ir_timestamp=best_ir[0],
                sync_timestamp=(vis_ts + best_ir[0]) / 2,
                sync_quality=quality
            )

        except queue.Empty:
            return None

    def get_resolution(self) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """获取双路分辨率"""
        vis_w = int(self.vis_cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if self.vis_cap else 0
        vis_h = int(self.vis_cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if self.vis_cap else 0
        ir_w = int(self.ir_cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if self.ir_cap else 0
        ir_h = int(self.ir_cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if self.ir_cap else 0
        return (vis_w, vis_h), (ir_w, ir_h)
