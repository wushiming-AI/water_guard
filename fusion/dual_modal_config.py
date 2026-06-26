"""
双模态融合检测配置文件

包含双模态融合检测的所有配置参数，支持时段自适应权重调整。
属于 fusion 包的一部分。
"""

from dataclasses import dataclass, field
from typing import Dict, Any

# 从同级包导入，避免循环依赖
from fusion.dual_modal import FusionStrategy


@dataclass
class DualModalConfig:
    """双模态融合检测配置类
    
    管理可见光(RGB)和红外热成像(IR)双模态融合检测的所有配置参数。
    支持时段自适应权重调整，白天以RGB为主，夜间以IR为主。
    """
    
    # ========== 基础开关 ==========
    enabled: bool = False
    
    # ========== 融合策略 ==========
    strategy: str = "late"  # "early" / "late" / "decision"
    
    # ========== RGB 配置 ==========
    rgb_source: str = "0"
    rgb_confidence: float = 0.5
    
    # ========== IR 配置 ==========
    ir_source: str = "1"
    ir_confidence: float = 0.4
    ir_enabled: bool = True
    
    # ========== IR模拟器配置（无真实IR摄像头时使用） ==========
    use_ir_simulator: bool = True
    water_temperature: float = 25.0
    body_temperature: float = 37.0
    
    # ========== 融合参数 ==========
    rgb_weight: float = 0.6
    ir_weight: float = 0.4
    iou_threshold: float = 0.45
    complementary_threshold: float = 0.3
    
    # ========== 时段自适应 ==========
    use_time_adaptive: bool = True
    day_rgb_weight: float = 0.7      # 白天（6:00-18:00）
    night_rgb_weight: float = 0.3    # 夜间
    
    # ========== 溺水检测增强 ==========
    ir_drowning_boost: float = 1.2
    
    def get_effective_weights(self, hour: int = 12) -> tuple:
        """根据当前小时获取有效的RGB和IR权重
        
        Args:
            hour: 当前小时（24小时制，0-23）
            
        Returns:
            (rgb_weight, ir_weight) 元组，和为1.0
        """
        if not self.use_time_adaptive:
            return self.rgb_weight, self.ir_weight
        
        if 6 <= hour < 18:
            return self.day_rgb_weight, round(1.0 - self.day_rgb_weight, 2)
        else:
            return self.night_rgb_weight, round(1.0 - self.night_rgb_weight, 2)
    
    def get_strategy_enum(self) -> FusionStrategy:
        """获取融合策略枚举"""
        try:
            return FusionStrategy(self.strategy)
        except ValueError:
            import logging
            logging.getLogger(__name__).warning(
                f"未知的融合策略: {self.strategy}，回退到 late")
            return FusionStrategy.LATE
    
    def to_dict(self) -> Dict[str, Any]:
        """将配置转换为字典"""
        return {
            "enabled": self.enabled,
            "strategy": self.strategy,
            "rgb_source": self.rgb_source,
            "rgb_confidence": self.rgb_confidence,
            "ir_source": self.ir_source,
            "ir_confidence": self.ir_confidence,
            "ir_enabled": self.ir_enabled,
            "use_ir_simulator": self.use_ir_simulator,
            "water_temperature": self.water_temperature,
            "body_temperature": self.body_temperature,
            "rgb_weight": self.rgb_weight,
            "ir_weight": self.ir_weight,
            "iou_threshold": self.iou_threshold,
            "complementary_threshold": self.complementary_threshold,
            "use_time_adaptive": self.use_time_adaptive,
            "day_rgb_weight": self.day_rgb_weight,
            "night_rgb_weight": self.night_rgb_weight,
            "ir_drowning_boost": self.ir_drowning_boost,
        }
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "DualModalConfig":
        """从字典创建配置对象"""
        config = cls()
        for key, value in config_dict.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return config


# ========== 全局默认配置实例 ==========
default_config = DualModalConfig()

# ========== 预设配置 ==========

DAYTIME_CONFIG = DualModalConfig(
    enabled=True,
    strategy="late",
    rgb_confidence=0.5,
    ir_confidence=0.4,
    rgb_weight=0.7,
    ir_weight=0.3,
    use_time_adaptive=False,
)

NIGHTTIME_CONFIG = DualModalConfig(
    enabled=True,
    strategy="late",
    rgb_confidence=0.4,
    ir_confidence=0.5,
    rgb_weight=0.3,
    ir_weight=0.7,
    use_time_adaptive=False,
)

HIGH_ACCURACY_CONFIG = DualModalConfig(
    enabled=True,
    strategy="late",
    rgb_confidence=0.4,
    ir_confidence=0.35,
    rgb_weight=0.5,
    ir_weight=0.5,
    iou_threshold=0.4,
    complementary_threshold=0.25,
    ir_drowning_boost=1.5,
    use_time_adaptive=True,
)

HIGH_PERFORMANCE_CONFIG = DualModalConfig(
    enabled=True,
    strategy="early",
    rgb_confidence=0.5,
    ir_confidence=0.4,
    rgb_weight=0.6,
    ir_weight=0.4,
    use_time_adaptive=True,
)
