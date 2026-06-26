"""
CBAM-YOLO: 将CBAM注意力模块注入YOLO主干网络

在CSPDarknet的backbone各stage输出后插入CBAM模块，增强远距离小目标的特征提取。

插入策略:
    - Stage 0 (浅层): 不插入CBAM，保留细粒度空间信息
    - Stage 1-4 (中深层): 插入CBAM，增强语义特征

支持YOLOv5和YOLOv8的结构适配。
"""

import torch.nn as nn
from .cbam import CBAM


class CBAMInjector:
    """向YOLO模型中注入CBAM注意力模块的注入器
    
    支持YOLOv5和YOLOv8两种主流模型结构。
    """
    
    @staticmethod
    def inject_into_yolov8(model, reduction_ratio=16):
        """向YOLOv8模型注入CBAM模块
        
        在backbone关键层输出后插入CBAM，增强特征表达。
        针对YOLOv8n/s/m/l/x等不同规模模型自适应。
        
        Args:
            model: Ultralytics YOLO模型对象 (model.model 为nn.Module列表)
            reduction_ratio: 通道注意力缩减比例
            
        Returns:
            注入CBAM后的模型
        """
        model_list = model.model
        
        # 遍历模型层，在backbone关键位置插入CBAM
        # YOLOv8 backbone结构: 0:Conv, 1:Conv, 2:C2f, 3:Conv, 4:C2f, 
        #                       5:Conv, 6:C2f, 7:Conv, 8:C2f, 9:SPPF
        # 在C2f和SPPF输出后插入CBAM
        
        injection_points = []
        for i, layer in enumerate(model_list):
            layer_type = type(layer).__name__
            if layer_type in ('C2f', 'SPPF', 'SPP'):
                injection_points.append((i, layer))
        
        # 跳过第一个C2f（stage 0，保留细粒度信息）
        injected_count = 0
        for idx, layer in injection_points:
            if injected_count == 0:
                injected_count += 1
                continue
            
            in_ch = CBAMInjector._get_out_channels(layer)
            if in_ch is None:
                continue
            
            cbam = CBAM(in_ch, reduction_ratio)
            model_list[idx] = nn.Sequential(layer, cbam)
            injected_count += 1
        
        print(f"[CBAM] Injected {injected_count - 1} CBAM modules into YOLOv8 backbone")
        return model
    
    @staticmethod
    def inject_into_yolov5(model, reduction_ratio=16):
        """向YOLOv5模型注入CBAM模块
        
        YOLOv5 backbone结构: model.model[i] for i in range(10) 对应backbone各层
        在C3模块输出后插入CBAM。
        
        Args:
            model: YOLOv5 模型对象
            reduction_ratio: 通道注意力缩减比例
            
        Returns:
            注入CBAM后的模型
        """
        model_list = model.model
        
        # YOLOv5 backbone中的C3模块索引
        injection_points = []
        for i, layer in enumerate(model_list):
            layer_type = type(layer).__name__
            if layer_type == 'C3':
                injection_points.append((i, layer))
        
        # 跳过第一个C3（浅层）
        injected_count = 0
        for idx, layer in injection_points:
            if injected_count == 0:
                injected_count += 1
                continue
            
            in_ch = CBAMInjector._get_out_channels(layer)
            if in_ch is None:
                continue
            
            cbam = CBAM(in_ch, reduction_ratio)
            model_list[idx] = nn.Sequential(layer, cbam)
            injected_count += 1
        
        print(f"[CBAM] Injected {injected_count - 1} CBAM modules into YOLOv5 backbone")
        return model
    
    @staticmethod
    def _get_out_channels(layer):
        """获取层的输出通道数
        
        尝试多种方式获取，兼容不同版本的YOLO模型。
        
        Args:
            layer: nn.Module层
            
        Returns:
            输出通道数，获取失败返回None
        """
        # 方式1: 直接属性
        for attr in ('out_channels', 'c2', 'out_ch', 'out_planes'):
            if hasattr(layer, attr):
                val = getattr(layer, attr)
                if isinstance(val, int):
                    return val
        
        # 方式2: nn.Sequential -> 取最后一个layer的输出
        if isinstance(layer, nn.Sequential):
            return CBAMInjector._get_out_channels(layer[-1])
        
        # 方式3: Conv2d类型
        if isinstance(layer, nn.Conv2d):
            return layer.out_channels
        
        # 方式4: cv2.conv 属性 (YOLOv5 C3)
        if hasattr(layer, 'cv2'):
            cv2 = layer.cv2
            if hasattr(cv2, 'conv') and isinstance(cv2.conv, nn.Conv2d):
                return cv2.conv.out_channels
            if isinstance(cv2, nn.Sequential):
                for m in reversed(cv2):
                    if isinstance(m, nn.Conv2d):
                        return m.out_channels
        
        # 方式5: cv3.conv 属性 (YOLOv8 C2f)
        if hasattr(layer, 'cv3'):
            cv3 = layer.cv3
            if hasattr(cv3, 'conv') and isinstance(cv3.conv, nn.Conv2d):
                return cv3.conv.out_channels
            if isinstance(cv3, nn.Sequential):
                for m in reversed(cv3):
                    if isinstance(m, nn.Conv2d):
                        return m.out_channels
        
        # 方式6: 尝试conv属性
        if hasattr(layer, 'conv') and isinstance(layer.conv, nn.Conv2d):
            return layer.conv.out_channels
        
        return None


def add_cbam_to_model(model, model_type='yolov8', reduction_ratio=16):
    """便捷函数: 向YOLO模型添加CBAM注意力模块
    
    Args:
        model: YOLO模型对象
        model_type: 模型类型，'yolov5' 或 'yolov8'
        reduction_ratio: 通道注意力缩减比例
        
    Returns:
        增强后的模型
    """
    if model_type == 'yolov8':
        return CBAMInjector.inject_into_yolov8(model, reduction_ratio)
    elif model_type == 'yolov5':
        return CBAMInjector.inject_into_yolov5(model, reduction_ratio)
    else:
        raise ValueError(f"Unsupported model type: {model_type}. Use 'yolov5' or 'yolov8'.")
