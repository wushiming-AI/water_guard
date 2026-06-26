"""双模态融合检测包 (RGB + IR)

提供可见光 + 红外热成像的双模态融合溺水检测能力。

主要模块:
- ir_preprocess:   红外图像预处理 (RAW转换、伪彩色、CLAHE、去噪)
- dual_modal:      双模态融合检测管道 (早/晚/决策融合)
- dual_stream:     双路视频流同步读取
- ir_camera_simulator: 红外热像模拟器 (无真实IR硬件时使用)
- dual_modal_config:   配置管理 (时段自适应、预设方案)
"""

from fusion.ir_preprocess import IRPreprocessor, PaletteMode
from fusion.dual_modal import (
    DualModalDetector, FusionStrategy,
    DetectionResult, FusionResult,
)
from fusion.dual_stream import DualStreamReader, SyncedFrame
from fusion.ir_camera_simulator import IRCameraSimulator
from fusion.dual_modal_config import (
    DualModalConfig, default_config,
    DAYTIME_CONFIG, NIGHTTIME_CONFIG,
    HIGH_ACCURACY_CONFIG, HIGH_PERFORMANCE_CONFIG,
)

__all__ = [
    # 预处理
    "IRPreprocessor", "PaletteMode",
    # 融合检测
    "DualModalDetector", "FusionStrategy",
    "DetectionResult", "FusionResult",
    # 视频流
    "DualStreamReader", "SyncedFrame",
    # 模拟器
    "IRCameraSimulator",
    # 配置
    "DualModalConfig", "default_config",
    "DAYTIME_CONFIG", "NIGHTTIME_CONFIG",
    "HIGH_ACCURACY_CONFIG", "HIGH_PERFORMANCE_CONFIG",
]
