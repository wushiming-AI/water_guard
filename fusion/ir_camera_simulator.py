"""
红外热像模拟器
用于在没有真实红外摄像头时模拟IR视频流

原理：
1. 从RGB帧提取人体区域
2. 模拟人体热辐射（体温37°C vs 水温25°C）
3. 生成伪热成像图
"""

import cv2
import numpy as np
from typing import List


class IRCameraSimulator:
    """红外热像模拟器
    
    从可见光(RGB)帧生成模拟的红外热成像帧，
    用于在没有真实红外摄像头的情况下测试和开发双模态检测功能。
    
    模拟原理：
    - 水温低于体温，在热成像中显示为较冷（暗）区域
    - 人体（体温37°C）在水面（水温25°C）上显示为明显的热源（亮）区域
    - 通过高斯模糊模拟热扩散效应
    """
    
    def __init__(self, water_temp: float = 25.0, body_temp: float = 37.0,
                 ambient_temp: float = 30.0):
        """
        初始化红外热像模拟器
        
        Args:
            water_temp: 水温（°C），决定背景温度
            body_temp: 体温（°C），决定人体热辐射强度
            ambient_temp: 环境温度（°C）
        """
        self.water_temp = water_temp
        self.body_temp = body_temp
        self.ambient_temp = ambient_temp
    
    def generate_ir_frame(self, rgb_frame: np.ndarray, 
                          detection_boxes: List[List] = None) -> np.ndarray:
        """
        从RGB帧生成模拟IR帧
        
        算法：
        1. 将RGB转灰度作为基础温度分布图
        2. 水体区域设为均匀水温
        3. 人体检测框区域设为体温，加上高斯模糊模拟热扩散
        4. 添加热噪声
        5. 应用热成像调色板（COLORMAP_JET）
        
        Args:
            rgb_frame: RGB输入帧，形状 (H, W, 3)，BGR格式
            detection_boxes: YOLO检测到的人体框列表，
                            每个元素为 [x1, y1, x2, y2, cls, conf, ...]
            
        Returns:
            ir_frame: 模拟IR帧，形状 (H, W, 3)，热力调色板伪彩色
        """
        h, w = rgb_frame.shape[:2]
        
        # 1. 基础温度图（灰度反转：RGB亮的区域在IR中可能是冷的）
        gray = cv2.cvtColor(rgb_frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        
        # 2. 初始化温度图（假设整帧为水温）
        temp_map = np.full((h, w), self.water_temp, dtype=np.float32)
        
        # 3. 在检测框中设置体温
        if detection_boxes:
            for box in detection_boxes:
                if len(box) >= 4:
                    x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)
                    
                    if x2 <= x1 or y2 <= y1:
                        continue
                    
                    # 创建人体热源mask（椭圆形状更贴近人体）
                    mask = np.zeros((h, w), np.float32)
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    rx, ry = max(1, (x2 - x1) // 2), max(1, (y2 - y1) // 2)
                    cv2.ellipse(mask, (cx, cy), (rx, ry), 0, 0, 360, 1.0, -1)
                    
                    # 高斯模糊模拟热扩散
                    kernel_w = max(3, rx // 2 * 2 + 1)
                    kernel_h = max(3, ry // 2 * 2 + 1)
                    mask = cv2.GaussianBlur(mask, (kernel_w, kernel_h), rx / 3)
                    
                    # 设置体温（只对mask>0的区域生效）
                    temp_map = temp_map * (1 - mask) + self.body_temp * mask
        
        # 4. 添加传感器噪声（模拟红外传感器噪声）
        noise = np.random.normal(0, 0.5, (h, w)).astype(np.float32)
        temp_map += noise
        
        # 5. 归一化并应用热力调色板
        temp_min, temp_max = self.water_temp - 2, self.body_temp + 3
        temp_normalized = np.clip((temp_map - temp_min) / (temp_max - temp_min), 0, 1)
        temp_uint8 = (temp_normalized * 255).astype(np.uint8)
        
        # 应用热力调色板 (OpenCV COLORMAP_JET: 蓝->青->绿->黄->红)
        ir_colored = cv2.applyColorMap(temp_uint8, cv2.COLORMAP_JET)
        
        return ir_colored
    
    def generate_ir_from_frame(self, rgb_frame: np.ndarray, 
                                boxes: List[List]) -> np.ndarray:
        """便捷接口：从RGB帧生成模拟IR帧"""
        return self.generate_ir_frame(rgb_frame, boxes)
    
    def set_water_temperature(self, temp: float):
        """设置水温（°C）"""
        self.water_temp = temp
    
    def set_body_temperature(self, temp: float):
        """设置体温（°C）"""
        self.body_temp = temp
