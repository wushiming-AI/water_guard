"""
轨迹分析模块

对跟踪目标的运动轨迹进行时序分析，
识别溺水风险行为特征：长时间静止、运动模式突变、垂直抖动等。
"""

import math
from collections import defaultdict, deque


class TrajectoryBuffer:
    """轨迹缓冲区，存储每个跟踪目标的历史位置，并进行运动分析。

    支持溺水风险特征检测：
    - 长时间静止不动
    - 运动模式从混乱到静止（挣扎后沉没）
    - 方向频繁突变
    - 垂直方向小幅抖动（水中上下起伏）
    """

    def __init__(self, max_length=100):
        """初始化轨迹缓冲区。

        Args:
            max_length: 每个目标保留的最大历史点数。
        """
        self.max_length = max_length
        # 每个目标的轨迹: track_id -> deque of (x, y, timestamp)
        self._trajectories = defaultdict(lambda: deque(maxlen=max_length))

    def add_point(self, track_id, x, y, timestamp):
        """为指定目标添加一个位置点。

        Args:
            track_id: 跟踪目标ID。
            x: 中心点 x 坐标（像素）。
            y: 中心点 y 坐标（像素）。
            timestamp: 当前时间戳（秒）。
        """
        self._trajectories[track_id].append((x, y, timestamp))

    def get_trajectory(self, track_id):
        """获取指定目标的历史轨迹。

        Args:
            track_id: 跟踪目标ID。

        Returns:
            [(x, y, timestamp), ...] 位置列表，可能为空。
        """
        return list(self._trajectories.get(track_id, []))

    def remove_track(self, track_id):
        """移除已失效目标的轨迹数据。

        Args:
            track_id: 要移除的目标ID。
        """
        self._trajectories.pop(track_id, None)

    def analyze_motion(self, track_id):
        """分析指定目标的运动特征。

        综合考虑速度、位移、方向变化等因素，
        判定运动模式：静止 / 缓慢 / 正常 / 异常。

        Args:
            track_id: 跟踪目标ID。

        Returns:
            dict 包含以下字段:
                - is_stationary: 是否长时间静止
                - avg_speed: 平均帧间位移（像素/帧）
                - motion_pattern: 运动模式 "static"/"slow"/"normal"/"erratic"
                - total_displacement: 总位移距离（像素）
                - direction_changes: 显著方向变化次数
        """
        traj = self.get_trajectory(track_id)
        result = {
            'is_stationary': False,
            'avg_speed': 0.0,
            'motion_pattern': 'static',
            'total_displacement': 0.0,
            'direction_changes': 0,
        }

        if len(traj) < 2:
            return result

        # ── 计算帧间位移和速度 ──
        speeds = []
        total_displacement = 0.0
        for i in range(1, len(traj)):
            dx = traj[i][0] - traj[i - 1][0]
            dy = traj[i][1] - traj[i - 1][1]
            dist = math.sqrt(dx * dx + dy * dy)
            speeds.append(dist)
            total_displacement += dist

        avg_speed = sum(speeds) / len(speeds) if speeds else 0.0

        # ── 计算方向变化次数 ──
        # 相邻帧间运动方向差异超过阈值视为一次方向变化
        direction_changes = 0
        min_speed_for_dir = 2.0  # 速度过小不计方向变化
        for i in range(2, len(traj)):
            dx1 = traj[i - 1][0] - traj[i - 2][0]
            dy1 = traj[i - 1][1] - traj[i - 2][1]
            dx2 = traj[i][0] - traj[i - 1][0]
            dy2 = traj[i][1] - traj[i - 1][1]

            speed1 = math.sqrt(dx1 * dx1 + dy1 * dy1)
            speed2 = math.sqrt(dx2 * dx2 + dy2 * dy2)
            if speed1 < min_speed_for_dir or speed2 < min_speed_for_dir:
                continue

            # 计算两帧运动方向夹角的余弦值
            cos_angle = (dx1 * dx2 + dy1 * dy2) / (speed1 * speed2)
            cos_angle = max(-1.0, min(1.0, cos_angle))
            angle = math.acos(cos_angle)

            # 方向变化超过 60° 算一次显著方向变化
            if angle > math.pi / 3.0:
                direction_changes += 1

        # ── 判断是否静止 ──
        # 最近 30 帧内平均位移小于阈值视为静止
        recent_n = min(30, len(speeds))
        recent_avg_speed = sum(speeds[-recent_n:]) / recent_n if recent_n > 0 else 0.0
        is_stationary = recent_avg_speed < 1.5

        # ── 判定运动模式 ──
        if is_stationary:
            motion_pattern = 'static'
        elif avg_speed < 3.0:
            motion_pattern = 'slow'
        elif avg_speed < 15.0:
            motion_pattern = 'normal'
        else:
            # 高速度，还需看方向变化频率判断是否异常
            dir_change_rate = direction_changes / max(len(traj) - 2, 1)
            if dir_change_rate > 0.3:
                motion_pattern = 'erratic'
            else:
                motion_pattern = 'normal'

        # 如果速度不快但方向变化频率很高，也算异常
        if motion_pattern in ('slow', 'normal') and len(traj) > 5:
            dir_change_rate = direction_changes / max(len(traj) - 2, 1)
            if dir_change_rate > 0.4:
                motion_pattern = 'erratic'

        result.update({
            'is_stationary': is_stationary,
            'avg_speed': avg_speed,
            'motion_pattern': motion_pattern,
            'total_displacement': total_displacement,
            'direction_changes': direction_changes,
        })
        return result

    def analyze_drowning_risk(self, track_id):
        """分析指定目标的溺水风险。

        基于多种溺水行为特征计算综合风险分数：
        1. 长时间静止不动（沉没后不动）
        2. 异常运动后突然静止（挣扎后沉没）
        3. 频繁方向变化（水中挣扎）
        4. 垂直方向小幅抖动（水中上下起伏）

        Args:
            track_id: 跟踪目标ID。

        Returns:
            (risk_score, risk_factors)
            risk_score: 风险分数 0.0-1.0
            risk_factors: 风险因素列表，每项为描述字符串
        """
        traj = self.get_trajectory(track_id)
        risk_score = 0.0
        risk_factors = []

        if len(traj) < 5:
            return 0.0, []

        motion = self.analyze_motion(track_id)

        # ── 因素1：长时间静止 ──
        # 在水中长时间不动是溺水的强信号
        if motion['is_stationary'] and len(traj) >= 15:
            # 静止时间越长，风险越高
            stationary_score = min(len(traj) / 60.0, 1.0) * 0.4
            risk_score += stationary_score
            risk_factors.append(f"长时间静止(avg_speed={motion['avg_speed']:.1f})")

        # ── 因素2：异常运动模式 ──
        # 挣扎表现为方向频繁变化
        if motion['motion_pattern'] == 'erratic':
            risk_score += 0.3
            risk_factors.append(
                f"异常运动模式(direction_changes={motion['direction_changes']})"
            )

        # ── 因素3：从异常运动转为静止（挣扎后沉没）──
        if len(traj) >= 10:
            # 分析前半段和后半段的运动模式
            mid = len(traj) // 2
            early_speeds = []
            late_speeds = []
            for i in range(1, len(traj)):
                dx = traj[i][0] - traj[i - 1][0]
                dy = traj[i][1] - traj[i - 1][1]
                dist = math.sqrt(dx * dx + dy * dy)
                if i < mid:
                    early_speeds.append(dist)
                else:
                    late_speeds.append(dist)

            early_avg = sum(early_speeds) / len(early_speeds) if early_speeds else 0
            late_avg = sum(late_speeds) / len(late_speeds) if late_speeds else 0

            # 前半段运动明显大于后半段，且后半段接近静止
            if early_avg > 5.0 and late_avg < 2.0 and early_avg > late_avg * 3:
                risk_score += 0.35
                risk_factors.append(
                    f"运动骤减(early={early_avg:.1f}, late={late_avg:.1f})"
                )

        # ── 因素4：垂直方向小幅抖动 ──
        # 溺水者常在水面上下起伏，表现为 y 坐标小幅周期性波动
        if len(traj) >= 10:
            y_values = [p[1] for p in traj]
            y_diffs = [y_values[i] - y_values[i - 1] for i in range(1, len(y_values))]

            # 统计 y 方向符号变化次数（上下起伏）
            y_sign_changes = 0
            for i in range(1, len(y_diffs)):
                if y_diffs[i] * y_diffs[i - 1] < 0:
                    y_sign_changes += 1

            # y 方向波动频率高但幅度小 → 水面起伏
            y_sign_rate = y_sign_changes / max(len(y_diffs) - 1, 1)
            y_amplitude = sum(abs(d) for d in y_diffs) / len(y_diffs)

            if y_sign_rate > 0.3 and 1.0 < y_amplitude < 10.0:
                bobbing_score = min(y_sign_rate, 1.0) * 0.25
                risk_score += bobbing_score
                risk_factors.append(
                    f"垂直抖动(sign_rate={y_sign_rate:.2f}, amp={y_amplitude:.1f})"
                )

        # 风险分数上限为 1.0
        risk_score = min(risk_score, 1.0)

        return risk_score, risk_factors
