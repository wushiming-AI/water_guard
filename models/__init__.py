"""
models 包 - CBAM注意力增强模块

提供:
    - CBAM: 通道+空间注意力模块
    - ChannelAttention: 通道注意力
    - SpatialAttention: 空间注意力
    - CBAMInjector: YOLO模型CBAM注入器
    - add_cbam_to_model: 便捷注入函数
"""

from .cbam import CBAM, ChannelAttention, SpatialAttention
from .cbam_yolo import CBAMInjector, add_cbam_to_model

__all__ = [
    'CBAM',
    'ChannelAttention',
    'SpatialAttention',
    'CBAMInjector',
    'add_cbam_to_model',
]
