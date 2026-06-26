"""
多端联动报警通知渠道
支持的渠道：短信、声光报警器、微信公众号、小程序订阅消息、WebSocket广播
"""

from abc import ABC, abstractmethod
import asyncio
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class NotificationChannel(ABC):
    """通知渠道基类"""
    
    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled
    
    @abstractmethod
    async def send(self, payload: Dict[str, Any]) -> bool:
        """发送通知，返回是否成功"""
        pass


class SMSChannel(NotificationChannel):
    """
    短信通知渠道
    支持腾讯云SMS、阿里云短信服务
    """
    def __init__(self, secret_id: str = "", secret_key: str = "", 
                 sdk_app_id: str = "", template_id: str = "",
                 sign_name: str = "", phone_numbers: list = None):
        super().__init__("sms")
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.sdk_app_id = sdk_app_id
        self.template_id = template_id
        self.sign_name = sign_name
        self.phone_numbers = phone_numbers or []
    
    async def send(self, payload: Dict[str, Any]) -> bool:
        """发送短信告警"""
        if not self.phone_numbers:
            logger.warning("[SMS] No phone numbers configured")
            return False
        
        location = payload.get('location', '未知位置')
        level = payload.get('level', 'urgent')
        detect_type = payload.get('detect_type', '未知')
        timestamp = payload.get('timestamp', '')
        
        # 构建短信内容
        content = f"【水域安防】{level}告警！{detect_type}检测 - 位置：{location} - 时间：{timestamp}"
        
        logger.info(f"[SMS] Would send to {self.phone_numbers}: {content}")
        
        # TODO: 集成腾讯云SMS SDK
        # from tencentcloud.sms.v20210111 import sms_client, models
        # For now, log and simulate
        for phone in self.phone_numbers:
            logger.info(f"[SMS] -> {phone}: {content}")
        
        return True


class SoundAlarmChannel(NotificationChannel):
    """
    声光报警器渠道
    通过HTTP请求触发现场声光报警设备
    """
    def __init__(self, device_urls: list = None):
        super().__init__("sound_alarm")
        self.device_urls = device_urls or []
    
    async def send(self, payload: Dict[str, Any]) -> bool:
        """触发声光报警"""
        if not self.device_urls:
            logger.warning("[SoundAlarm] No device URLs configured")
            return False
        
        import aiohttp
        
        level = payload.get('level', 'urgent')
        # 只有紧急告警才触发声光
        if level != 'urgent':
            return True
        
        alarm_data = {
            "action": "alarm",
            "level": level,
            "duration": 30,  # 报警持续30秒
            "location": payload.get('location', ''),
            "timestamp": payload.get('timestamp', '')
        }
        
        for url in self.device_urls:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=alarm_data, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            logger.info(f"[SoundAlarm] Triggered device at {url}")
                        else:
                            logger.error(f"[SoundAlarm] Device {url} returned {resp.status}")
            except Exception as e:
                logger.error(f"[SoundAlarm] Failed to trigger {url}: {e}")
        
        return True


class WeChatOAChannel(NotificationChannel):
    """
    微信公众号模板消息渠道
    """
    def __init__(self, app_id: str = "", app_secret: str = "",
                 template_id: str = "", openids: list = None):
        super().__init__("wechat_oa")
        self.app_id = app_id
        self.app_secret = app_secret
        self.template_id = template_id
        self.openids = openids or []
    
    async def send(self, payload: Dict[str, Any]) -> bool:
        """发送微信公众号模板消息"""
        if not self.openids:
            logger.warning("[WeChatOA] No openids configured")
            return False
        
        logger.info(f"[WeChatOA] Would send template message to {len(self.openids)} users")
        
        # TODO: 集成微信公众号API
        # 1. 获取access_token
        # 2. 发送模板消息
        
        for openid in self.openids:
            logger.info(f"[WeChatOA] -> {openid}: {payload.get('message', '')}")
        
        return True


class MiniProgramSubscribeChannel(NotificationChannel):
    """
    小程序订阅消息渠道
    """
    def __init__(self, app_id: str = "", app_secret: str = "",
                 template_id: str = ""):
        super().__init__("miniprogram_subscribe")
        self.app_id = app_id
        self.app_secret = app_secret
        self.template_id = template_id
    
    async def send(self, payload: Dict[str, Any]) -> bool:
        """发送小程序订阅消息"""
        logger.info(f"[MiniProgram] Would send subscribe message")
        # TODO: 集成微信小程序订阅消息API
        return True


class WebSocketChannel(NotificationChannel):
    """
    WebSocket广播渠道（已有，作为通知系统的一部分管理）
    """
    def __init__(self, broadcast_func=None):
        super().__init__("websocket")
        self.broadcast_func = broadcast_func
    
    async def send(self, payload: Dict[str, Any]) -> bool:
        """通过WebSocket广播"""
        if self.broadcast_func:
            try:
                event_type = 'alarm' if payload.get('level') == 'urgent' else 'detection'
                await self.broadcast_func(event_type, payload)
                return True
            except Exception as e:
                logger.error(f"[WebSocket] Broadcast failed: {e}")
        return False
