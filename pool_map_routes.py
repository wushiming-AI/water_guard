"""
泳池平面图配置API
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pool-map", tags=["泳池平面图"])


class CameraPosition(BaseModel):
    camera_id: str
    x: float
    y: float
    angle: float = -90
    fov: float = 60
    label: str = ""
    zone: str = ""


class PoolMapConfig(BaseModel):
    pool_type: str = "rectangle"          # rectangle, irregular, composite
    width: float = 25.0                    # meters
    height: float = 15.0
    deep_zone_depth: float = 2.0
    shallow_zone_depth: float = 1.2
    cameras: List[CameraPosition] = []


# Default pool map configuration
DEFAULT_MAP_CONFIG = {
    "pool_type": "rectangle",
    "width": 25.0,
    "height": 15.0,
    "deep_zone_depth": 2.0,
    "shallow_zone_depth": 1.2,
    "cameras": [
        {"camera_id": "CAM-001", "x": 400, "y": 30, "angle": -90, "fov": 60, "label": "深水区1号", "zone": "深水区"},
        {"camera_id": "CAM-002", "x": 150, "y": 30, "angle": -90, "fov": 60, "label": "浅水区1号", "zone": "浅水区"},
        {"camera_id": "CAM-003", "x": 650, "y": 30, "angle": -90, "fov": 60, "label": "深水区2号", "zone": "深水区"},
        {"camera_id": "CAM-004", "x": 400, "y": 570, "angle": 90, "fov": 60, "label": "全景1号", "zone": "全区域"},
    ]
}


@router.get("/config")
async def get_map_config():
    """获取泳池平面图配置"""
    return {"config": DEFAULT_MAP_CONFIG}


@router.post("/config")
async def update_map_config(config: PoolMapConfig):
    """更新泳池平面图配置"""
    # TODO: 持久化到数据库
    logger.info(f"[PoolMap] Updated config: {config.pool_type} pool")
    return {"success": True, "message": "泳池平面图配置已更新"}
