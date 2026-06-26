"""
红外热成像预处理模块
支持常见红外相机输出格式：14-bit RAW, 8-bit pseudo-color JPEG, radiometric JPG

主要功能:
1. RAW到温度值转换 (Planck公式)
2. 伪彩色调色板映射 (Ironbow, WhiteHot, BlackHot, Rainbow)
3. 自适应对比度增强 (CLAHE)
4. 红外噪声去除 (Non-Local Means, 中值滤波)
"""

import numpy as np
import cv2
from typing import Tuple, Optional, Literal
from enum import Enum

class PaletteMode(Enum):
    """伪彩色调色板模式"""
    IRONBOW = "ironbow"       # 铁红热 (最常用)
    WHITE_HOT = "white_hot"   # 白热
    BLACK_HOT = "black_hot"   # 黑热
    RAINBOW = "rainbow"       # 彩虹

class IRPreprocessor:
    """红外图像预处理器"""

    def __init__(self,
                 palette: PaletteMode = PaletteMode.IRONBOW,
                 clahe_clip_limit: float = 2.0,
                 clahe_tile_size: Tuple[int, int] = (8, 8),
                 denoise_strength: float = 10.0):
        self.palette = palette
        self.clahe = cv2.createCLAHE(
            clipLimit=clahe_clip_limit,
            tileGridSize=clahe_tile_size
        )
        self.denoise_strength = denoise_strength

    def raw_to_temperature(self, raw_data: np.ndarray,
                          emissivity: float = 0.98,
                          reflected_temp: float = 20.0) -> np.ndarray:
        """
        将RAW数据转换为温度值(摄氏度)

        Args:
            raw_data: 14-bit RAW数据, shape (H, W)
            emissivity: 发射率 (水≈0.98)
            reflected_temp: 反射温度

        Returns:
            np.ndarray: 温度矩阵 (摄氏度), shape (H, W)
        """
        # 简化的温度转换 (实际需根据相机标定参数调整)
        raw_normalized = raw_data.astype(np.float32) / 16383.0  # 14-bit max
        temp = raw_normalized * 120.0 - 20.0  # 映射到 -20°C ~ 100°C
        return temp

    def temperature_to_pseudo_color(self, temp_data: np.ndarray) -> np.ndarray:
        """
        温度数据 -> 伪彩色图像

        Args:
            temp_data: 温度矩阵, shape (H, W), 值范围约 -20 ~ 100

        Returns:
            np.ndarray: BGR彩色图像, shape (H, W, 3), dtype=uint8
        """
        # 归一化到 [0, 255]
        t_min, t_max = 15.0, 45.0  # 泳池环境典型温度范围
        normalized = np.clip((temp_data - t_min) / (t_max - t_min), 0, 1)
        gray = (normalized * 255).astype(np.uint8)

        if self.palette == PaletteMode.IRONBOW:
            return cv2.applyColorMap(gray, cv2.COLORMAP_JET)
        elif self.palette == PaletteMode.WHITE_HOT:
            return cv2.applyColorMap(gray, cv2.COLORMAP_HOT)
        elif self.palette == PaletteMode.BLACK_HOT:
            return cv2.applyColorMap(255 - gray, cv2.COLORMAP_HOT)
        elif self.palette == PaletteMode.RAINBOW:
            return cv2.applyColorMap(gray, cv2.COLORMAP_RAINBOW)
        else:
            return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    def enhance_contrast(self, img: np.ndarray) -> np.ndarray:
        """CLAHE对比度增强（适合红外图像低对比度特点）"""
        if len(img.shape) == 3:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            l = self.clahe.apply(l)
            lab = cv2.merge([l, a, b])
            return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        else:
            return self.clahe.apply(img)

    def denoise(self, img: np.ndarray) -> np.ndarray:
        """红外图像去噪（非局部均值滤波）"""
        return cv2.fastNlMeansDenoisingColored(
            img, None, self.denoise_strength, 10, 7, 21
        )

    def extract_human_temperature_regions(self, temp_data: np.ndarray) -> np.ndarray:
        """
        提取人体温度区域（用于辅助检测）

        人体体温≈37°C，水中温差明显
        返回：二值掩膜, 人体温度区域为255
        """
        human_temp_min, human_temp_max = 25.0, 42.0  # 水中人体温度范围
        mask = np.zeros_like(temp_data, dtype=np.uint8)
        mask[(temp_data >= human_temp_min) & (temp_data <= human_temp_max)] = 255
        # 形态学处理：去除小噪点，连接破碎区域
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        return mask

    def process(self, ir_frame: np.ndarray, mode: str = "pseudo_color") -> np.ndarray:
        """
        一站式红外预处理

        Args:
            ir_frame: 输入红外帧 (可能为RAW灰度或伪彩色图像)
            mode: "pseudo_color" | "gray" | "both"

        Returns:
            处理后的图像 (BGR彩色或灰度)
        """
        if len(ir_frame.shape) == 2:
            # 灰度RAW图像
            gray = ir_frame
        else:
            # 已经是彩色图像，转灰度用于处理
            gray = cv2.cvtColor(ir_frame, cv2.COLOR_BGR2GRAY)

        # 增强对比度
        enhanced = self.enhance_contrast(gray)

        if mode == "gray":
            return enhanced

        # 伪彩色映射
        colored = self.temperature_to_pseudo_color(enhanced.astype(np.float32) * 0.1)

        # 降噪
        colored = self.denoise(colored)

        return colored
