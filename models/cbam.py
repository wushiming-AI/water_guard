"""
CBAM: Convolutional Block Attention Module
基于论文 "CBAM: Convolutional Block Attention Module" (Woo et al., ECCV 2018)

模块组成:
    1. ChannelAttention: 通道注意力 —— 关注"什么"是重要的
    2. SpatialAttention:  空间注意力 —— 关注"哪里"是重要的
    
使用方式:
    cbam = CBAM(in_channels=256, reduction_ratio=16, kernel_size=7)
    enhanced = cbam(feature_map)  # 输入输出shape相同
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class ChannelAttention(nn.Module):
    """通道注意力模块
    
    同时使用全局平均池化和全局最大池化来聚合空间信息，
    通过共享的MLP生成通道注意力权重。
    
    Args:
        in_channels: 输入特征图的通道数
        reduction_ratio: MLP中间层的缩减比例，默认16
    """
    
    def __init__(self, in_channels, reduction_ratio=16):
        super().__init__()
        reduced_channels = max(in_channels // reduction_ratio, 1)
        
        self.mlp = nn.Sequential(
            nn.Linear(in_channels, reduced_channels),
            nn.ReLU(inplace=True),
            nn.Linear(reduced_channels, in_channels)
        )
    
    def forward(self, x):
        """前向传播
        
        Args:
            x: 输入特征图 (B, C, H, W)
            
        Returns:
            加权后的特征图 (B, C, H, W)
        """
        b, c, h, w = x.shape
        
        # 全局平均池化路径
        avg_pool = F.adaptive_avg_pool2d(x, 1).view(b, c)
        avg_out = self.mlp(avg_pool)
        
        # 全局最大池化路径
        max_pool = F.adaptive_max_pool2d(x, 1).view(b, c)
        max_out = self.mlp(max_pool)
        
        # 融合两条路径并sigmoid
        attention = torch.sigmoid(avg_out + max_out).view(b, c, 1, 1)
        
        return x * attention


class SpatialAttention(nn.Module):
    """空间注意力模块
    
    对通道维度分别进行平均池化和最大池化，
    拼接后通过卷积生成空间注意力图。
    
    Args:
        kernel_size: 卷积核大小，默认7
    """
    
    def __init__(self, kernel_size=7):
        super().__init__()
        padding = kernel_size // 2
        self.conv = nn.Conv2d(
            2, 1, 
            kernel_size=kernel_size, 
            padding=padding, 
            bias=False
        )
    
    def forward(self, x):
        """前向传播
        
        Args:
            x: 输入特征图 (B, C, H, W)
            
        Returns:
            加权后的特征图 (B, C, H, W)
        """
        # 沿通道维度计算平均值和最大值
        avg_out = torch.mean(x, dim=1, keepdim=True)      # (B, 1, H, W)
        max_out, _ = torch.max(x, dim=1, keepdim=True)    # (B, 1, H, W)
        
        # 拼接后通过卷积生成空间注意力图
        combined = torch.cat([avg_out, max_out], dim=1)    # (B, 2, H, W)
        attention = torch.sigmoid(self.conv(combined))     # (B, 1, H, W)
        
        return x * attention


class CBAM(nn.Module):
    """CBAM注意力模块
    
    依次应用通道注意力和空间注意力，增强特征表示。
    
    Args:
        in_channels: 输入特征图的通道数
        reduction_ratio: 通道注意力MLP的缩减比例，默认16
        kernel_size: 空间注意力卷积核大小，默认7
    """
    
    def __init__(self, in_channels, reduction_ratio=16, kernel_size=7):
        super().__init__()
        self.channel_attention = ChannelAttention(in_channels, reduction_ratio)
        self.spatial_attention = SpatialAttention(kernel_size)
    
    def forward(self, x):
        """前向传播: 通道注意力 -> 空间注意力
        
        Args:
            x: 输入特征图 (B, C, H, W)
            
        Returns:
            增强后的特征图 (B, C, H, W)
        """
        x = self.channel_attention(x)
        x = self.spatial_attention(x)
        return x
