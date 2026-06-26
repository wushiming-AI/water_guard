"""
通知渠道配置管理
存储和读取通知渠道配置（数据库/配置文件）
"""

from typing import Dict, Any, List, Optional
import json
import logging

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "sms": {
        "enabled": False,
        "provider": "tencent",       # tencent / aliyun
        "secret_id": "",
        "secret_key": "",
        "sdk_app_id": "",
        "template_id": "",
        "sign_name": "水域安防",
        "phone_numbers": [],          # 告警接收手机号列表
        "cooldown_seconds": 60,       # 短信60秒冷却
        "required_levels": ["urgent"]  # 仅紧急告警发短信
    },
    "sound_alarm": {
        "enabled": False,
        "device_urls": [],            # 声光报警器HTTP地址列表
        "duration": 30,               # 默认报警持续时间(秒)
        "cooldown_seconds": 10,
        "required_levels": ["urgent"]
    },
    "wechat_oa": {
        "enabled": False,
        "app_id": "",
        "app_secret": "",
        "template_id": "",
        "openids": [],
        "cooldown_seconds": 30,
        "required_levels": ["urgent", "warning"]
    },
    "miniprogram": {
        "enabled": True,              # 默认启用
        "app_id": "",
        "template_id": "",
        "cooldown_seconds": 10,
        "required_levels": ["urgent", "warning", "info"]
    },
    "websocket": {
        "enabled": True,              # WebSocket始终启用
        "cooldown_seconds": 1,
        "required_levels": ["urgent", "warning", "info"]
    }
}


class NotifySettings:
    """通知设置管理器"""
    
    def __init__(self):
        self._config = DEFAULT_CONFIG.copy()
    
    def load_from_dict(self, config: Dict[str, Any]):
        """从字典加载配置"""
        for channel, settings in config.items():
            if channel in self._config:
                self._config[channel].update(settings)
    
    def get_channel_config(self, channel: str) -> Dict[str, Any]:
        """获取指定渠道配置"""
        return self._config.get(channel, {})
    
    def set_channel_config(self, channel: str, settings: Dict[str, Any]):
        """设置指定渠道配置"""
        if channel in self._config:
            self._config[channel].update(settings)
    
    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        return self._config.copy()
    
    def to_json(self) -> str:
        """序列化为JSON"""
        return json.dumps(self._config, ensure_ascii=False, indent=2)


notify_settings = NotifySettings()
