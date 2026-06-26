"""
DeepSORT 多目标跟踪模块

简化版 DeepSORT 实现，用于 YOLO 检测结果的跨帧目标跟踪。
包含卡尔曼滤波运动预测和匈牙利算法数据关联。
"""

import numpy as np

try:
    from scipy.optimize import linear_sum_assignment
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def _compute_iou(bbox1, bbox2):
    """计算两个边界框的 IoU（交并比）。

    Args:
        bbox1: [x1, y1, x2, y2] 格式的边界框。
        bbox2: [x1, y1, x2, y2] 格式的边界框。

    Returns:
        IoU 值，范围 [0, 1]。
    """
    # 计算交集区域
    ix1 = max(bbox1[0], bbox2[0])
    iy1 = max(bbox1[1], bbox2[1])
    ix2 = min(bbox1[2], bbox2[2])
    iy2 = min(bbox1[3], bbox2[3])

    inter_w = max(0.0, ix2 - ix1)
    inter_h = max(0.0, iy2 - iy1)
    inter_area = inter_w * inter_h

    # 计算并集区域
    area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
    area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
    union_area = area1 + area2 - inter_area

    if union_area <= 0:
        return 0.0
    return inter_area / union_area


class KalmanFilter:
    """简化版卡尔曼滤波器，用于边界框运动预测。

    状态向量: [x, y, a, h, dx, dy, da, dh]
    其中 (x, y) 为中心点，a 为宽高比，h 为高度，
    (dx, dy, da, dh) 为对应的速度分量。
    """

    def __init__(self, bbox):
        """初始化卡尔曼滤波器。

        Args:
            bbox: 初始边界框 [x1, y1, x2, y2]。
        """
        # 将 [x1,y1,x2,y2] 转换为 [cx, cy, aspect, h]
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        cx = bbox[0] + w / 2.0
        cy = bbox[1] + h / 2.0
        aspect = w / max(h, 1e-6)

        # 状态向量 [x, y, a, h, dx, dy, da, dh]
        self.x = np.array([cx, cy, aspect, h, 0, 0, 0, 0], dtype=np.float64)

        # 状态转移矩阵（匀速运动模型）
        self.F = np.eye(8, dtype=np.float64)
        self.F[0, 4] = 1.0  # x += dx
        self.F[1, 5] = 1.0  # y += dy
        self.F[2, 6] = 1.0  # a += da
        self.F[3, 7] = 1.0  # h += dh

        # 观测矩阵（只观测位置和形状，不观测速度）
        self.H = np.eye(4, 8, dtype=np.float64)

        # 过程噪声协方差
        self.Q = np.eye(8, dtype=np.float64)
        self.Q[4:, 4:] *= 0.01  # 速度噪声较小

        # 观测噪声协方差
        self.R = np.eye(4, dtype=np.float64) * 1.0

        # 状态协方差矩阵
        self.P = np.eye(8, dtype=np.float64)
        self.P[4:, 4:] *= 1000.0  # 速度初始不确定性大
        self.P *= 10.0

    def predict(self):
        """预测下一时刻状态。

        Returns:
            预测的边界框 [x1, y1, x2, y2]。
        """
        # 状态预测: x = F * x
        self.x = self.F @ self.x
        # 协方差预测: P = F * P * F^T + Q
        self.P = self.F @ self.P @ self.F.T + self.Q

        # 如果高度变为负，重置速度
        if self.x[3] <= 0:
            self.x[3] = 1.0
            self.x[7] = 0.0

        return self._state_to_bbox()

    def update(self, bbox):
        """用观测值更新卡尔曼滤波器状态。

        Args:
            bbox: 观测到的边界框 [x1, y1, x2, y2]。
        """
        # 将 bbox 转换为观测向量 [cx, cy, aspect, h]
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        z = np.array([
            bbox[0] + w / 2.0,
            bbox[1] + h / 2.0,
            w / max(h, 1e-6),
            h,
        ], dtype=np.float64)

        # 卡尔曼增益: K = P * H^T * (H * P * H^T + R)^(-1)
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)

        # 状态更新: x = x + K * (z - H * x)
        y = z - self.H @ self.x
        self.x = self.x + K @ y

        # 协方差更新: P = (I - K * H) * P
        I_KH = np.eye(8) - K @ self.H
        self.P = I_KH @ self.P

    def _state_to_bbox(self):
        """将状态向量转换为边界框格式。

        Returns:
            边界框 [x1, y1, x2, y2]。
        """
        cx, cy, a, h = self.x[:4]
        w = a * h
        return [
            cx - w / 2.0,
            cy - h / 2.0,
            cx + w / 2.0,
            cy + h / 2.0,
        ]


class Track:
    """单个目标跟踪轨迹。

    维护一个目标的卡尔曼滤波器、命中计数和生命周期信息。
    """

    _next_id = 1  # 全局轨迹 ID 计数器

    def __init__(self, detection, max_age=30, min_hits=3):
        """初始化跟踪轨迹。

        Args:
            detection: 检测结果 [x1, y1, x2, y2, confidence, class_id]。
            max_age: 最大允许丢失帧数。
            min_hits: 确认轨迹所需的最小连续命中次数。
        """
        self.track_id = Track._next_id
        Track._next_id += 1

        self.kf = KalmanFilter(detection[:4])
        self.class_id = int(detection[5])
        self.confidence = float(detection[4])
        self.hits = 1
        self.age = 1
        self.time_since_update = 0
        self.max_age = max_age
        self.min_hits = min_hits

    def predict(self):
        """预测下一帧位置。"""
        self.kf.predict()
        self.age += 1
        self.time_since_update += 1

    def update(self, detection):
        """用检测结果更新轨迹。

        Args:
            detection: 检测结果 [x1, y1, x2, y2, confidence, class_id]。
        """
        self.kf.update(detection[:4])
        self.hits += 1
        self.time_since_update = 0
        self.confidence = float(detection[4])
        self.class_id = int(detection[5])

    @property
    def bbox(self):
        """当前预测/更新的边界框。"""
        return self.kf._state_to_bbox()

    @property
    def is_confirmed(self):
        """轨迹是否已确认（命中次数达到阈值）。"""
        return self.hits >= self.min_hits

    @property
    def is_dead(self):
        """轨迹是否已失效（超过最大丢失帧数）。"""
        return self.time_since_update > self.max_age


class Tracker:
    """DeepSORT 多目标跟踪器（简化版）。

    使用卡尔曼滤波进行运动预测，匈牙利算法进行检测-轨迹关联。

    Usage:
        tracker = Tracker()
        tracked = tracker.update(detections)
        for obj in tracked:
            print(obj['track_id'], obj['bbox'])
    """

    def __init__(self, max_age=30, min_hits=3, iou_threshold=0.3):
        """初始化跟踪器。

        Args:
            max_age: 轨迹最大丢失帧数，超过后删除。
            min_hits: 确认轨迹的最小连续命中次数。
            iou_threshold: IoU 匹配阈值，低于此值不关联。
        """
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self.tracks = []

    def update(self, detections):
        """用当前帧检测结果更新跟踪器。

        Args:
            detections: 检测结果列表，每个元素为
                [x1, y1, x2, y2, confidence, class_id]。

        Returns:
            已确认的跟踪目标列表，每个元素为字典:
                {
                    'track_id': int,
                    'bbox': [x1, y1, x2, y2],
                    'class_id': int,
                    'confidence': float,
                    'age': int,
                    'hits': int,
                    'time_since_update': int,
                }
        """
        # ── 第1步：对所有现有轨迹进行卡尔曼预测 ──
        for track in self.tracks:
            track.predict()

        if len(detections) == 0:
            # 无检测结果，仅清理失效轨迹
            self.tracks = [t for t in self.tracks if not t.is_dead]
            return self._get_tracked_objects()

        # ── 第2步：计算代价矩阵（IoU 距离）──
        # 代价 = 1 - IoU，越小表示匹配越好
        num_tracks = len(self.tracks)
        num_dets = len(detections)
        cost_matrix = np.zeros((num_tracks, num_dets), dtype=np.float64)

        for t_idx, track in enumerate(self.tracks):
            pred_bbox = track.bbox
            for d_idx, det in enumerate(detections):
                iou = _compute_iou(pred_bbox, det[:4])
                cost_matrix[t_idx, d_idx] = 1.0 - iou

        # ── 第3步：使用匈牙利算法进行最优匹配 ──
        matched, unmatched_tracks, unmatched_dets = self._associate(
            cost_matrix, num_tracks, num_dets
        )

        # ── 第4步：更新已匹配的轨迹 ──
        for t_idx, d_idx in matched:
            self.tracks[t_idx].update(detections[d_idx])

        # ── 第5步：为未匹配的检测创建新轨迹 ──
        for d_idx in unmatched_dets:
            new_track = Track(detections[d_idx], self.max_age, self.min_hits)
            self.tracks.append(new_track)

        # ── 第6步：删除失效轨迹 ──
        self.tracks = [t for t in self.tracks if not t.is_dead]

        return self._get_tracked_objects()

    def _associate(self, cost_matrix, num_tracks, num_dets):
        """执行检测-轨迹关联。

        优先使用 scipy 匈牙利算法，否则使用贪心 IoU 匹配。

        Args:
            cost_matrix: 代价矩阵，shape=(num_tracks, num_dets)。
            num_tracks: 轨迹数量。
            num_dets: 检测数量。

        Returns:
            (matched, unmatched_tracks, unmatched_dets)
            matched: [(t_idx, d_idx), ...] 匹配对
            unmatched_tracks: 未匹配的轨迹索引列表
            unmatched_dets: 未匹配的检测索引列表
        """
        if num_tracks == 0:
            return [], [], list(range(num_dets))

        matched = []
        unmatched_tracks = set(range(num_tracks))
        unmatched_dets = set(range(num_dets))

        if _HAS_SCIPY and num_tracks > 0 and num_dets > 0:
            # 使用 scipy 匈牙利算法求解最优匹配
            row_indices, col_indices = linear_sum_assignment(cost_matrix)
            for r, c in zip(row_indices, col_indices):
                if cost_matrix[r, c] <= (1.0 - self.iou_threshold):
                    matched.append((r, c))
                    unmatched_tracks.discard(r)
                    unmatched_dets.discard(c)
        else:
            # 贪心 IoU 匹配：每次选 IoU 最大的配对
            while unmatched_tracks and unmatched_dets:
                # 在未匹配项中找最小代价（最大 IoU）
                best_cost = float('inf')
                best_t = -1
                best_d = -1
                for t in unmatched_tracks:
                    for d in unmatched_dets:
                        if cost_matrix[t, d] < best_cost:
                            best_cost = cost_matrix[t, d]
                            best_t = t
                            best_d = d

                if best_cost > (1.0 - self.iou_threshold):
                    break  # 剩余匹配都不满足阈值

                matched.append((best_t, best_d))
                unmatched_tracks.discard(best_t)
                unmatched_dets.discard(best_d)

        return matched, sorted(unmatched_tracks), sorted(unmatched_dets)

    def _get_tracked_objects(self):
        """获取所有已确认且当前帧有更新的跟踪目标。

        Returns:
            跟踪目标字典列表。
        """
        results = []
        for track in self.tracks:
            if track.is_confirmed and track.time_since_update == 0:
                results.append({
                    'track_id': track.track_id,
                    'bbox': track.bbox,
                    'class_id': track.class_id,
                    'confidence': track.confidence,
                    'age': track.age,
                    'hits': track.hits,
                    'time_since_update': track.time_since_update,
                })
        return results
