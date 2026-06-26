"""
通知管理API路由
提供通知渠道配置、测试、状态查询接口
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notify", tags=["通知管理"])


class ChannelStatusResponse(BaseModel):
    """渠道状态响应"""
    name: str
    enabled: bool
    priority: int
    required_levels: List[str]
    last_triggered: Optional[str] = None


class NotifyConfigUpdate(BaseModel):
    """通知配置更新请求"""
    channel: str                     # sms / sound_alarm / wechat_oa / miniprogram / websocket
    enabled: Optional[bool] = None
    settings: Optional[Dict] = None


class NotifyTestRequest(BaseModel):
    """通知测试请求"""
    channel: str
    message: str = "这是一条测试告警消息"
    level: str = "warning"


@router.get("/channels")
async def list_channels():
    """获取所有通知渠道状态"""
    from notify.manager import get_notification_manager
    manager = get_notification_manager()
    return {"channels": manager.get_channel_status()}


@router.get("/settings")
async def get_settings():
    """获取通知配置"""
    from notify.settings import notify_settings
    return {"settings": notify_settings.get_all()}


@router.post("/settings")
async def update_settings(config: NotifyConfigUpdate):
    """更新通知配置"""
    from notify.settings import notify_settings
    from notify.manager import get_notification_manager
    
    settings = config.settings or {}
    if config.enabled is not None:
        settings['enabled'] = config.enabled
    
    notify_settings.set_channel_config(config.channel, settings)
    
    return {"success": True, "message": f"渠道 {config.channel} 配置已更新"}


@router.post("/test")
async def test_notification(req: NotifyTestRequest):
    """测试通知渠道"""
    from notify.manager import get_notification_manager
    from notify.channels import SMSChannel, SoundAlarmChannel
    from notify.settings import notify_settings
    
    manager = get_notification_manager()
    
    payload = {
        "timestamp": __import__('datetime').datetime.now().isoformat(),
        "location": "测试位置",
        "message": req.message,
        "level": req.level,
        "detect_type": "测试"
    }
    
    results = await manager.broadcast(payload)
    
    return {
        "success": True,
        "results": results,
        "message": f"已向 {sum(1 for v in results.values() if v)} 个渠道发送测试通知"
    }


@router.post("/silence/{channel}")
async def silence_channel(channel: str, duration_seconds: int = 300):
    """静默指定渠道（临时关闭）"""
    from notify.manager import get_notification_manager
    
    manager = get_notification_manager()
    for config in manager.channels:
        if config.channel.name == channel:
            config.channel.enabled = False
            # TODO: 定时恢复
            logger.info(f"[NotifyAPI] Silenced channel {channel} for {duration_seconds}s")
            return {"success": True, "message": f"渠道 {channel} 已静默 {duration_seconds} 秒"}
    
    raise HTTPException(status_code=404, detail=f"渠道 {channel} 不存在")


@router.post("/unsilence/{channel}")
async def unsilence_channel(channel: str):
    """取消静默"""
    from notify.manager import get_notification_manager
    
    manager = get_notification_manager()
    for config in manager.channels:
        if config.channel.name == channel:
            config.channel.enabled = True
            return {"success": True, "message": f"渠道 {channel} 已恢复"}
    
    raise HTTPException(status_code=404, detail=f"渠道 {channel} 不存在")
