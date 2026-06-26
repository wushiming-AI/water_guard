"""
水域溺水模拟视频生成器
用 OpenCV 合成泳池场景 + 模拟游泳者溺水过程，输出 .mp4 视频
用于 water_guard 系统演示，无需真实摄像头

场景设计：
  0~3s    — 正常游泳（人在水面水平移动，有规律划臂）
  3~5s    — 开始挣扎（垂直姿势，手臂快速挥动，头部上下起伏）
  5~8s    — 溺水加剧（身体下沉，水面只剩手臂，溅起水花）
  8~10s   — 沉入水中（人消失，水面恢复平静）

用法：
  python generate_demo.py                   # 默认 10s 640x480
  python generate_demo.py --duration 15     # 15 秒
  python generate_demo.py --output demo2.mp4 --width 1280 --height 720
"""
import argparse
import math
import numpy as np
import cv2

# ─── 配置 ─────────────────────────────────────────────────────────────────
WATER_BLUE = (180, 140, 80)       # 泳池水色 (BGR)
TILE_LIGHT = (195, 170, 100)      # 泳池瓷砖浅色
TILE_DARK = (160, 120, 50)        # 泳池瓷砖深色
SKIN_COLOR = (120, 160, 230)      # 肤色
HAIR_COLOR = (80, 80, 80)         # 发色
TRUNKS_COLOR = (220, 50, 50)      # 泳裤红色
SPLASH_COLOR = (255, 255, 255)    # 水花白色
LANE_LINE = (200, 180, 120)       # 泳道线

def draw_pool_background(frame, t):
    """绘制泳池背景：水面、泳道线、池壁"""
    h, w = frame.shape[:2]
    # 水面渐变
    for y in range(h):
        ratio = y / h
        b = int(180 - ratio * 40)
        g = int(150 - ratio * 20)
        r = int(100 - ratio * 30)
        frame[y, :] = (b, g, r)

    # 泳道线（水平）
    for lane_y in range(60, h - 60, 80):
        for x in range(0, w, 40):
            cv2.rectangle(frame, (x, lane_y - 2), (x + 20, lane_y + 2), LANE_LINE, -1)

    # 池壁边框
    cv2.rectangle(frame, (10, 10), (w - 10, h - 10), (60, 60, 60), 2)

    # 水深标记文字
    cv2.putText(frame, "POOL SURVEILLANCE", (w // 2 - 100, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    # 水面波纹（随时间变化）
    for i in range(0, w, 6):
        wave_y = int(48 + 3 * math.sin(t * 3 + i * 0.15))
        frame[wave_y, i] = (220, 210, 180)

    return frame

def draw_swimmer(frame, cx, cy, body_angle, arm_angle, is_drowning=False):
    """绘制一个游泳者
    Args:
        cx, cy: 身体中心坐标
        body_angle: 身体倾斜角度（弧度）
        arm_angle: 手臂摆动角度（弧度）
        is_drowning: 是否处于溺水状态
    """
    # 头部
    head_radius = 10
    head_cx = int(cx + 18 * math.sin(body_angle))
    head_cy = int(cy - 12 * math.cos(body_angle))
    cv2.circle(frame, (head_cx, head_cy), head_radius, SKIN_COLOR, -1)
    cv2.circle(frame, (head_cx, head_cy), head_radius, (100, 140, 200), 1)

    # 头发（头顶半圆）
    hair_pts = []
    for a in np.linspace(-math.pi, 0, 12):
        hx = int(head_cx + head_radius * math.cos(a))
        hy = int(head_cy + head_radius * math.sin(a) - 3)
        hair_pts.append((hx, hy))
    if len(hair_pts) > 2:
        cv2.fillPoly(frame, [np.array(hair_pts)], HAIR_COLOR)

    # 身体（躯干）
    body_len = 30
    body_top = (int(cx - 4 * math.sin(body_angle)), int(cy - 12 * math.cos(body_angle)))
    body_bot = (int(cx + body_len * math.sin(body_angle)), int(cy + body_len * math.cos(body_angle)))
    cv2.line(frame, body_top, body_bot, SKIN_COLOR, 8)

    # 泳裤
    trunk_y = int(cy + 6 * math.cos(body_angle))
    trunk_x = int(cx + 6 * math.sin(body_angle))
    cv2.ellipse(frame, (trunk_x, trunk_y), (12, 8), 0, 0, 360, TRUNKS_COLOR, -1)

    # 左臂
    l_shoulder = (int(cx), int(cy - 4))
    l_elbow = (int(cx - 15 * math.cos(arm_angle)), int(cy + 5 * math.sin(arm_angle)))
    l_hand = (int(l_elbow[0] - 12 * math.cos(arm_angle + 0.5)),
              int(l_elbow[1] + 12 * math.sin(arm_angle - 0.3)))
    cv2.line(frame, l_shoulder, l_elbow, SKIN_COLOR, 5)
    cv2.line(frame, l_elbow, l_hand, SKIN_COLOR, 4)

    # 右臂
    r_shoulder = (int(cx), int(cy - 4))
    r_elbow = (int(cx + 15 * math.cos(arm_angle + 1.0)), int(cy + 5 * math.sin(arm_angle + 1.0)))
    r_hand = (int(r_elbow[0] + 12 * math.cos(arm_angle + 0.3)),
              int(r_elbow[1] + 12 * math.sin(arm_angle - 0.5)))
    cv2.line(frame, r_shoulder, r_elbow, SKIN_COLOR, 5)
    cv2.line(frame, r_elbow, r_hand, SKIN_COLOR, 4)

    # 溺水特效：水花飞溅
    if is_drowning:
        for _ in range(12):
            sx = int(cx + np.random.randint(-25, 25))
            sy = int(cy - 10 + np.random.randint(-15, 5))
            cv2.circle(frame, (sx, sy), np.random.randint(1, 4), SPLASH_COLOR, -1)
        # 水面大波纹
        ripple_y = int(cy + 15)
        cv2.ellipse(frame, (cx, ripple_y), (30, 6), 0, 0, 360, (200, 220, 240), 1)

def generate_video(output_path, duration=10, width=640, height=480, fps=25):
    """生成模拟溺水视频"""
    total_frames = duration * fps
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    print(f"生成模拟视频: {output_path}")
    print(f"时长: {duration}s, 分辨率: {width}x{height}, 帧率: {fps}fps")

    # 游泳者初始位置和运动参数
    swimmer_cx = width // 3          # 水平位置
    swimmer_base_y = height // 2     # 基准水面高度

    for frame_idx in range(total_frames):
        t = frame_idx / fps                     # 当前时间（秒）
        phase = t / duration                     # 0→1 进度

        frame = np.zeros((height, width, 3), dtype=np.uint8)
        draw_pool_background(frame, t)

        # ── 游泳者运动逻辑 ──
        # 水平移动（从左游到中间）
        swimmer_x = width // 3 + 80 * min(phase, 1.0)

        # 身体角度
        body_angle = 0.1 * math.sin(t * 2.5)    # 正常游动时轻微的左右摇摆

        # 手臂摆动
        arm_angle = t * 4.0                       # 正常划臂频率

        # 垂直位置偏移
        vertical_offset = 0
        is_drowning = False

        if phase < 0.3:
            # 阶段1: 正常游泳（0~3s）
            vertical_offset = 3 * math.sin(t * 2)  # 微小的上下浮动
            body_angle = 0.05 * math.sin(t * 2.5)
            arm_angle = t * 4.0

        elif phase < 0.5:
            # 阶段2: 开始挣扎（3~5s）
            progress_in_stage = (phase - 0.3) / 0.2  # 0→1
            vertical_offset = 3 * math.sin(t * 2) - 8 * progress_in_stage
            body_angle = 0.2 * math.sin(t * 6)       # 身体倾斜加剧
            arm_angle = t * 8.0                        # 手臂快速挥动
            if progress_in_stage > 0.4:
                is_drowning = True

        elif phase < 0.8:
            # 阶段3: 溺水加剧（5~8s）
            progress_in_stage = (phase - 0.5) / 0.3
            vertical_offset = -5 - 20 * progress_in_stage  # 持续下沉
            body_angle = 0.4 * math.sin(t * 10)             # 剧烈倾斜
            arm_angle = t * 12.0                             # 极快挥臂
            is_drowning = True

        else:
            # 阶段4: 沉入水中（8~10s）
            progress_in_stage = (phase - 0.8) / 0.2
            # 人从水面消失，水面恢复平静
            opacity = 1.0 - progress_in_stage
            if opacity < 0:
                opacity = 0
            vertical_offset = -25 - 10 * progress_in_stage
            # 逐渐淡化
            if progress_in_stage > 0.5:
                continue  # 8.5s 后人不画了，表示已沉入
            is_drowning = True
            body_angle = 0
            arm_angle = t * 15.0

        swimmer_y = int(swimmer_base_y + vertical_offset)
        draw_swimmer(frame, int(swimmer_x), swimmer_y, body_angle, arm_angle, is_drowning)

        # ── 时间戳和状态标签 ──
        stage_names = ["Normal swimming", "Beginning to struggle",
                       "Drowning - rapid flailing", "Submerged - person lost"]
        stage_idx = min(int(phase * 4), 3)
        label = stage_names[stage_idx]

        color = (100, 255, 100) if stage_idx == 0 else \
                (0, 220, 255) if stage_idx == 1 else \
                (0, 100, 255) if stage_idx == 2 else \
                (0, 0, 200)

        cv2.putText(frame, f"Time: {t:.1f}s | {label}", (15, height - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

        out.write(frame)

        if frame_idx % 25 == 0:
            print(f"  进度: {frame_idx}/{total_frames} 帧 ({phase*100:.0f}%)")

    out.release()
    print(f"\n完成! 视频已保存到: {output_path}")
    print(f"文件大小: {__import__('os').path.getsize(output_path) / 1024:.1f} KB")
    return output_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="水域溺水模拟视频生成器")
    parser.add_argument("--output", default="demo_drowning.mp4", help="输出视频路径")
    parser.add_argument("--duration", type=int, default=10, help="视频时长（秒）")
    parser.add_argument("--width", type=int, default=640, help="视频宽度")
    parser.add_argument("--height", type=int, default=480, help="视频高度")
    parser.add_argument("--fps", type=int, default=25, help="帧率")
    args = parser.parse_args()

    generate_video(args.output, args.duration, args.width, args.height, args.fps)
