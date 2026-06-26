"""
双模态融合溺水检测 - 主脚本
同时使用可见光和红外热成像进行溺水检测

Usage:
    # 双摄像头（默认晚融合）
    python ir_fusion.py --vis-source 0 --ir-source 1 --model best.pt

    # 使用红外模拟器（无需真实IR摄像头）
    python ir_fusion.py --vis-source 0 --ir-source sim --model best.pt

    # 双模型 + RTSP 红外流 + 决策融合
    python ir_fusion.py --vis-source 0 --ir-source "rtsp://..." \\
        --vis-model best.pt --ir-model ir_best.pt --fusion decision

    # 使用预设配置
    python ir_fusion.py --vis-source 0 --ir-source sim --preset nighttime
"""

import argparse
import sys
import os
import time
import logging
from datetime import datetime
import cv2
import numpy as np

logging.basicConfig(level=logging.INFO,
                   format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger("ir_fusion")

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ultralytics import YOLO
from fusion.ir_preprocess import IRPreprocessor, PaletteMode
from fusion.dual_modal import DualModalDetector, FusionStrategy
from fusion.dual_stream import DualStreamReader
from fusion.ir_camera_simulator import IRCameraSimulator
from fusion.dual_modal_config import (
    DualModalConfig,
    DAYTIME_CONFIG, NIGHTTIME_CONFIG,
    HIGH_ACCURACY_CONFIG, HIGH_PERFORMANCE_CONFIG,
)

# 预设配置映射
PRESETS = {
    "daytime": DAYTIME_CONFIG,
    "nighttime": NIGHTTIME_CONFIG,
    "high_accuracy": HIGH_ACCURACY_CONFIG,
    "high_performance": HIGH_PERFORMANCE_CONFIG,
}


def parse_args():
    parser = argparse.ArgumentParser(description="双模态融合溺水检测")

    # 视频源
    parser.add_argument('--vis-source', type=str, default='0',
                       help='可见光视频源 (摄像头索引/RTSP/文件路径)')
    parser.add_argument('--ir-source', type=str, default='1',
                       help='红外视频源 (摄像头索引/RTSP/文件路径)，设为 "sim" 使用红外模拟器')

    # 模型
    parser.add_argument('--vis-model', type=str, default='best.pt',
                       help='可见光模型路径')
    parser.add_argument('--ir-model', type=str, default=None,
                       help='红外模型路径 (默认共用可见光模型)')

    # 融合参数
    parser.add_argument('--fusion', choices=['early', 'late', 'decision'],
                       default='late', help='融合策略 (默认: late)')
    parser.add_argument('--vis-weight', type=float, default=0.6,
                       help='可见光权重 (默认: 0.6)')
    parser.add_argument('--ir-weight', type=float, default=0.4,
                       help='红外权重 (默认: 0.4)')

    # 预设配置（优先级高于单独参数）
    parser.add_argument('--preset', choices=list(PRESETS.keys()), default=None,
                       help='使用预设配置 (daytime/nighttime/high_accuracy/high_performance)')

    # 红外预处理
    parser.add_argument('--ir-palette', choices=['ironbow', 'white_hot', 'black_hot', 'rainbow'],
                       default='ironbow', help='红外伪彩色调色板 (默认: ironbow)')
    parser.add_argument('--ir-clahe', type=float, default=2.0,
                       help='红外CLAHE增强 (默认: 2.0)')

    # IR模拟器参数
    parser.add_argument('--water-temp', type=float, default=25.0,
                       help='模拟水温°C (默认: 25.0)')
    parser.add_argument('--body-temp', type=float, default=37.0,
                       help='模拟体温°C (默认: 37.0)')

    # 检测参数
    parser.add_argument('--conf', type=float, default=0.4,
                       help='置信度阈值 (默认: 0.4)')
    parser.add_argument('--camera-id', type=str, default='CAM-001',
                       help='摄像头ID')
    parser.add_argument('--backend', type=str, default='http://127.0.0.1:8000',
                       help='后端API地址')
    parser.add_argument('--location', type=str, default='泳池-双模态',
                       help='设备位置')

    # 显示
    parser.add_argument('--display', action='store_true', default=True,
                       help='显示检测画面')
    parser.add_argument('--no-display', action='store_false', dest='display',
                       help='不显示画面')

    return parser.parse_args()


def draw_detection(frame, results, color_map=None):
    """绘制检测结果"""
    if color_map is None:
        color_map = {
            'drowning': (0, 0, 255),       # 红色
            'swimming': (0, 165, 255),     # 橙色
            'playing': (0, 255, 0),        # 绿色
            'person_underwater': (255, 0, 255),  # 紫色
            'visible': (255, 0, 0),        # 蓝色-可见光源
            'ir': (0, 255, 255),           # 黄色-红外源
            'fused': (0, 255, 0),          # 绿色-融合源
        }

    for det in results.detections:
        x1, y1, x2, y2 = [int(v) for v in det.bbox]
        cls_name = det.class_name
        source = det.source

        color = color_map.get(cls_name, (255, 255, 255))

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        # 标签
        label = f"{cls_name} {det.confidence:.2f}"
        if det.temperature is not None:
            label += f" {det.temperature:.1f}C"

        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
        cv2.rectangle(frame, (x1, y1 - th - 4), (x1 + tw + 4, y1), color, -1)
        cv2.putText(frame, label, (x1 + 2, y1 - 4),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # 来源标记
        source_color = color_map.get(source.split('+')[0], (255, 255, 255))
        cv2.circle(frame, (x2 - 5, y1 + 5), 4, source_color, -1)

    return frame


def main():
    args = parse_args()

    # 应用预设配置
    effective_weights = (args.vis_weight, args.ir_weight)
    if args.preset and args.preset in PRESETS:
        cfg = PRESETS[args.preset]
        logger.info(f"应用预设配置: {args.preset}")
        args.fusion = cfg.strategy
        effective_weights = (cfg.rgb_weight, cfg.ir_weight)
        args.conf = min(cfg.rgb_confidence, cfg.ir_confidence)
        if cfg.use_time_adaptive:
            now = datetime.now()
            effective_weights = cfg.get_effective_weights(now.hour)
            logger.info(f"  时段自适应权重: RGB={effective_weights[0]}, IR={effective_weights[1]}"
                       f" (当前 {now.hour}:00)")

    logger.info("=" * 60)
    logger.info("双模态融合溺水检测系统启动")
    logger.info(f"  可见光源: {args.vis_source}")
    logger.info(f"  红外源: {args.ir_source}")
    logger.info(f"  融合策略: {args.fusion}")
    logger.info(f"  融合权重: RGB={effective_weights[0]}, IR={effective_weights[1]}")
    logger.info(f"  可见光模型: {args.vis_model}")
    logger.info(f"  红外模型: {args.ir_model or args.vis_model}")
    logger.info("=" * 60)

    # 加载模型
    vis_model = YOLO(args.vis_model)
    ir_model = YOLO(args.ir_model) if args.ir_model else vis_model

    # 创建红外预处理器
    ir_preprocessor = IRPreprocessor(
        palette=PaletteMode(args.ir_palette),
        clahe_clip_limit=args.ir_clahe
    )

    # 创建融合检测器
    fusion_detector = DualModalDetector(
        visible_model=vis_model,
        ir_model=ir_model,
        strategy=FusionStrategy(args.fusion),
        visible_weight=effective_weights[0],
        ir_weight=effective_weights[1],
        confidence_threshold=args.conf
    )

    # 判断是否使用红外模拟器
    use_simulator = (args.ir_source == "sim")
    ir_simulator = None
    ir_cap = None

    if use_simulator:
        logger.info("启用红外热像模拟器（无需真实IR摄像头）")
        ir_simulator = IRCameraSimulator(
            water_temp=args.water_temp,
            body_temp=args.body_temp
        )
        # 仅打开可见光摄像头
        cap = cv2.VideoCapture(args.vis_source)
        if not cap.isOpened():
            logger.error(f"无法打开可见光视频源: {args.vis_source}")
            return
        logger.info(f"可见光视频源已打开: {args.vis_source}")
    else:
        # 使用真实双路视频流
        stream = DualStreamReader(args.vis_source, args.ir_source)
        if not stream.open():
            logger.error("无法打开双路视频流，退出")
            return
        stream.start()
        cap = None  # DualStreamReader 管理自己的capture

    logger.info("双模态检测运行中... (按q退出)")

    frame_count = 0
    total_fusion_time = 0
    vis_model_for_sim = vis_model  # 用于模拟器提取检测框

    try:
        while True:
            if use_simulator:
                ret, vis_frame = cap.read()
                if not ret:
                    logger.warning("可见光视频流结束")
                    break

                # 用可见光模型快速检测人体框 → 生成模拟IR
                vis_results = vis_model_for_sim(vis_frame, verbose=False)
                detection_boxes = []
                if len(vis_results) > 0 and vis_results[0].boxes is not None:
                    for box in vis_results[0].boxes:
                        detection_boxes.append(
                            box.xyxy[0].cpu().numpy().tolist()
                        )

                ir_frame = ir_simulator.generate_ir_frame(vis_frame, detection_boxes)
                synced = type('SyncedFrame', (), {
                    'visible': vis_frame,
                    'ir': ir_frame,
                    'visible_timestamp': time.time(),
                    'ir_timestamp': time.time(),
                    'sync_timestamp': time.time(),
                    'sync_quality': 1.0,
                })()
            else:
                synced = stream.read_synced(timeout=1.0)
                if synced is None:
                    continue
                if synced.visible is None:
                    continue

            # 如果没有红外帧，退化为可见光检测
            if synced.ir is None:
                vis_results = vis_model(synced.visible, verbose=False)
                frame_count += 1
                if args.display:
                    vis_display = synced.visible.copy()
                    if len(vis_results) > 0 and vis_results[0].boxes is not None:
                        for box in vis_results[0].boxes:
                            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
                            cv2.rectangle(vis_display, (x1, y1), (x2, y2),
                                        (0, 255, 0), 2)
                    cv2.putText(vis_display, "IR unavailable - visible only",
                               (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                    cv2.imshow('Dual-Modal Detection', vis_display)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                continue

            # 双模态融合检测
            result = fusion_detector.detect(
                visible_frame=synced.visible,
                ir_frame=synced.ir,
                ir_preprocessor=ir_preprocessor
            )

            frame_count += 1
            total_fusion_time += result.fusion_time_ms

            # 统计
            drowning_count = sum(
                1 for d in result.detections if d.class_name == 'drowning'
            )

            if frame_count % 30 == 0:
                avg_time = total_fusion_time / frame_count
                logger.info(
                    f"Frame {frame_count}: {len(result.detections)} detects "
                    f"({drowning_count} drowning), "
                    f"avg fusion: {avg_time:.1f}ms, "
                    f"sync quality: {synced.sync_quality:.2f}"
                )

            if args.display:
                vis_display = draw_detection(synced.visible.copy(), result)

                # 顶部信息栏
                cv2.putText(vis_display,
                           f"Detects: {len(result.detections)} | "
                           f"Drowning: {drowning_count} | "
                           f"Fusion: {result.fusion_time_ms:.0f}ms | "
                           f"Strategy: {result.strategy.value}",
                           (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

                cv2.putText(vis_display,
                           f"Sync: {synced.sync_quality:.2f} | "
                           f"Vis: {result.visible_time_ms:.0f}ms | "
                           f"IR: {result.ir_time_ms:.0f}ms | "
                           f"{'SIM' if use_simulator else 'REAL'}",
                           (10, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

                # 红外缩略图（右下角1/4大小）
                ir_small = cv2.resize(synced.ir,
                                     (synced.ir.shape[1] // 4,
                                      synced.ir.shape[0] // 4))
                h, w = ir_small.shape[:2]
                vh, vw = vis_display.shape[:2]
                vis_display[vh - h - 10:vh - 10, vw - w - 10:vw - 10] = ir_small
                cv2.rectangle(vis_display,
                             (vw - w - 10, vh - h - 10),
                             (vw - 10, vh - 10), (0, 255, 255), 2)
                cv2.putText(vis_display, "IR",
                           (vw - w - 10, vh - h - 15),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

                cv2.imshow('Dual-Modal Detection', vis_display)

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

    except KeyboardInterrupt:
        logger.info("用户中断")
    finally:
        if use_simulator and cap:
            cap.release()
        else:
            stream.stop()
        cv2.destroyAllWindows()
        logger.info(
            f"处理了 {frame_count} 帧，"
            f"平均融合时间: {total_fusion_time / max(frame_count, 1):.1f}ms"
        )


if __name__ == '__main__':
    main()
