"""
通知管理器 - 管理所有通知渠道，支持渠道配置和故障转移
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from .channels import (
    NotificationChannel, SMSChannel, SoundAlarmChannel,
    WeChatOAChannel, MiniProgramSubscribeChannel, WebSocketChannel
)

logger = logging.getLogger(__name__)


class ChannelConfig:
    """渠道配置"""
    def __init__(self, channel: NotificationChannel, 
                 priority: int = 0,      # 优先级（数字越小越优先）
                 cooldown_seconds: int = 5,  # 同一渠道冷却时间
                 required_levels: list = None):  # 哪些告警级别触发
        self.channel = channel
        self.priority = priority
        self.cooldown_seconds = cooldown_seconds
        self.required_levels = required_levels or ['urgent', 'warning', 'info']
        self.last_triggered: Optional[datetime] = None


class NotificationManager:
    """多端联动通知管理器"""
    
    def __init__(self):
        self.channels: List[ChannelConfig] = []
        self._lock = asyncio.Lock()
    
    def register_channel(self, channel: NotificationChannel, **kwargs):
        """注册通知渠道"""
        config = ChannelConfig(channel, **kwargs)
        self.channels.append(config)
        # 按优先级排序
        self.channels.sort(key=lambda c: c.priority)
        logger.info(f"[NotifyManager] Registered channel: {channel.name} (priority={config.priority})")
    
    async def broadcast(self, payload: Dict[str, Any]) -> Dict[str, bool]:
        """
        向所有已启用的渠道广播告警
        
        返回每个渠道的发送结果
        """
        results = {}
        level = payload.get('level', 'warning')
        
        async with self._lock:
            for config in self.channels:
                if not config.channel.enabled:
                    results[config.channel.name] = False
                    continue
                
                # 检查是否需要此级别
                if level not in config.required_levels:
                    results[config.channel.name] = False
                    continue
                
                # 冷却检查
                now = datetime.now()
                if config.last_triggered:
                    elapsed = (now - config.last_triggered).total_seconds()
                    if elapsed < config.cooldown_seconds:
                        logger.debug(f"[NotifyManager] Channel {config.channel.name} cooling down ({elapsed:.1f}s < {config.cooldown_seconds}s)")
                        results[config.channel.name] = False
                        continue
                
                # 发送通知
                try:
                    success = await config.channel.send(payload)
                    if success:
                        config.last_triggered = now
                    results[config.channel.name] = success
                except Exception as e:
                    logger.error(f"[NotifyManager] Channel {config.channel.name} error: {e}")
                    results[config.channel.name] = False
        
        return results
    
    def get_channel_status(self) -> Dict[str, Any]:
        """获取所有渠道状态"""
        return {
            config.channel.name: {
                'enabled': config.channel.enabled,
                'priority': config.priority,
                'required_levels': config.required_levels,
                'last_triggered': config.last_triggered.isoformat() if config.last_triggered else None
            }
            for config in self.channels
        }


# 全局通知管理器实例
_notification_manager: Optional[NotificationManager] = None


def get_notification_manager() -> NotificationManager:
    """获取全局通知管理器（懒初始化）"""
    global _notification_manager
    if _notification_manager is None:
        _notification_manager = NotificationManager()
    return _notification_manager
