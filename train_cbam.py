"""
CBAM-YOLO 训练脚本

在YOLOv8基础上注入CBAM注意力模块，针对溺水检测场景进行训练。
溺水检测场景特点:
    - 小目标: 10-30米远距离，人体在画面中占比小
    - 水面环境: 反光、波纹干扰
    - 低对比度: 水下部分难以辨认

训练策略:
    - Mosaic数据增强: 提升小目标检测能力
    - 多尺度训练: 适应不同距离目标
    - Close mosaic: 最后10轮关闭mosaic，稳定收敛

Usage:
    python train_cbam.py --data dataset.yaml --epochs 100 --batch 16
    python train_cbam.py --data dataset.yaml --epochs 100 --batch 16 --base-model yolov8s.pt --output cbam_yolo_s.pt
"""

import argparse
import sys

from ultralytics import YOLO
from models.cbam_yolo import add_cbam_to_model


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='CBAM-YOLO: 带有CBAM注意力的溺水检测模型训练'
    )
    parser.add_argument(
        '--base-model', type=str, default='yolov8n.pt',
        help='基础模型路径 (默认: yolov8n.pt)'
    )
    parser.add_argument(
        '--data', type=str, default='dataset.yaml',
        help='数据集配置文件路径 (默认: dataset.yaml)'
    )
    parser.add_argument(
        '--epochs', type=int, default=100,
        help='训练轮数 (默认: 100)'
    )
    parser.add_argument(
        '--batch', type=int, default=16,
        help='批次大小 (默认: 16)'
    )
    parser.add_argument(
        '--imgsz', type=int, default=640,
        help='输入图像尺寸 (默认: 640)'
    )
    parser.add_argument(
        '--reduction', type=int, default=16,
        help='CBAM通道注意力缩减比例 (默认: 16)'
    )
    parser.add_argument(
        '--output', type=str, default='cbam_yolo_best.pt',
        help='输出模型路径 (默认: cbam_yolo_best.pt)'
    )
    parser.add_argument(
        '--device', type=str, default=None,
        help='训练设备，如 cuda:0, cpu (默认: 自动检测)'
    )
    parser.add_argument(
        '--workers', type=int, default=8,
        help='数据加载线程数 (默认: 8)'
    )
    parser.add_argument(
        '--resume', type=str, default=None,
        help='从检查点恢复训练'
    )
    return parser.parse_args()


def main():
    args = parse_args()
    
    # 1. 加载基础YOLO模型
    print(f"[CBAM-YOLO] 加载基础模型: {args.base_model}")
    model = YOLO(args.base_model)
    
    # 2. 注入CBAM注意力模块
    print(f"[CBAM-YOLO] 注入CBAM注意力模块 (reduction_ratio={args.reduction})...")
    add_cbam_to_model(model, model_type='yolov8', reduction_ratio=args.reduction)
    print("[CBAM-YOLO] CBAM模块注入完成")
    
    # 3. 训练配置（针对溺水检测小目标场景优化）
    print(f"[CBAM-YOLO] 开始训练: epochs={args.epochs}, batch={args.batch}, imgsz={args.imgsz}")
    
    results = model.train(
        data=args.data,
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=args.device,
        workers=args.workers,
        resume=args.resume,
        
        # 数据增强 - 针对小目标优化
        mosaic=1.0,              # mosaic增强，提升小目标召回
        scale=0.5,               # 更大的缩放范围
        shear=5.0,               # 剪切增强
        degrees=10.0,            # 旋转增强
        hsv_h=0.015,             # 色调变化
        hsv_s=0.4,               # 饱和度变化（水面颜色多变）
        hsv_v=0.3,               # 亮度变化（光照条件变化）
        translate=0.1,           # 平移增强
        flipud=0.0,              # 不进行上下翻转（水面上方通常不是水面）
        fliplr=0.5,              # 左右翻转
        
        # 关闭mosaic的轮数（稳定训练后期）
        close_mosaic=10,
        
        # 训练控制
        lr0=0.01,                # 初始学习率
        lrf=0.01,                # 最终学习率因子
        momentum=0.937,
        weight_decay=0.0005,
        warmup_epochs=3,
        warmup_momentum=0.8,
        
        # 损失权重
        box=7.5,                 # 提高box loss权重，重视定位精度
        cls=0.5,
        dfl=1.5,
        
    )
    
    # 4. 保存模型
    print(f"[CBAM-YOLO] 训练完成，保存模型到: {args.output}")
    model.save(args.output)
    print(f"[CBAM-YOLO] 模型已保存, 验证结果: {results}")


if __name__ == '__main__':
    main()
