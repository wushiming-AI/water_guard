"""
双模态融合检测管道
支持可见光 + 红外热成像的特征级融合

融合策略:
1. 早融合(Early Fusion): 检测前融合，双路输入拼接后统一推理
2. 晚融合(Late Fusion): 分别检测后融合结果，加权平均
3. 决策融合: 各自检测，综合决策

针对溺水检测场景，推荐晚融合策略：
- 可见光擅长检测水面以上姿态 (swimming/playing/drowning)
- 红外擅长检测水下人体轮廓和温度异常 (drowning更敏感)
"""

import numpy as np
import cv2
from typing import Tuple, Optional, Dict, List, Any
from dataclasses import dataclass
from enum import Enum
import time


class FusionStrategy(Enum):
    """融合策略"""
    EARLY = "early"     # 早融合：拼接后统一检测
    LATE = "late"       # 晚融合：分别检测后融合
    DECISION = "decision"  # 决策级融合


@dataclass
class DetectionResult:
    """统一检测结果格式"""
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2
    confidence: float
    class_id: int
    class_name: str
    source: str  # "visible", "ir", "fused"
    temperature: Optional[float] = None  # 红外温度(如果可用)

@dataclass
class FusionResult:
    """融合检测结果"""
    detections: List[DetectionResult]
    fusion_time_ms: float
    visible_time_ms: float
    ir_time_ms: float
    strategy: FusionStrategy


class DualModalDetector:
    """
    双模态融合检测器

    工作流程:
    1. 接收同步的可见光帧和红外帧
    2. 根据融合策略处理
    3. 输出融合后的检测结果
    """

    def __init__(self,
                 visible_model,          # YOLO model for visible
                 ir_model=None,          # YOLO model for IR (optional, can share visible model)
                 strategy: FusionStrategy = FusionStrategy.LATE,
                 visible_weight: float = 0.6,
                 ir_weight: float = 0.4,
                 iou_threshold: float = 0.5,
                 confidence_threshold: float = 0.3):
        """
        Args:
            visible_model: 可见光YOLO模型
            ir_model: 红外YOLO模型 (None表示共用visible_model)
            strategy: 融合策略
            visible_weight: 可见光权重 (晚融合)
            ir_weight: 红外权重 (晚融合)
            iou_threshold: NMS IoU阈值
            confidence_threshold: 最小置信度
        """
        self.visible_model = visible_model
        self.ir_model = ir_model or visible_model
        self.strategy = strategy
        self.visible_weight = visible_weight
        self.ir_weight = ir_weight
        self.iou_threshold = iou_threshold
        self.confidence_threshold = confidence_threshold

    def detect(self,
               visible_frame: np.ndarray,
               ir_frame: np.ndarray,
               ir_preprocessor=None) -> FusionResult:
        """
        双模态检测主入口

        Args:
            visible_frame: 可见光BGR帧
            ir_frame: 红外原始帧
            ir_preprocessor: IRPreprocessor实例

        Returns:
            FusionResult: 融合检测结果
        """
        t_start = time.time()

        # 红外预处理
        if ir_preprocessor is not None:
            ir_processed = ir_preprocessor.process(ir_frame)
        else:
            ir_processed = ir_frame

        if self.strategy == FusionStrategy.LATE:
            return self._late_fusion(visible_frame, ir_processed, t_start)
        elif self.strategy == FusionStrategy.EARLY:
            return self._early_fusion(visible_frame, ir_processed, t_start)
        elif self.strategy == FusionStrategy.DECISION:
            return self._decision_fusion(visible_frame, ir_processed, t_start)
        else:
            raise ValueError(f"Unknown fusion strategy: {self.strategy}")

    def _late_fusion(self, visible: np.ndarray, ir: np.ndarray,
                     t_start: float) -> FusionResult:
        """晚融合：各自检测，加权融合结果"""

        # 可见光检测
        t_v = time.time()
        vis_results = self.visible_model(visible, verbose=False)
        vis_time = (time.time() - t_v) * 1000

        # 红外检测
        t_ir = time.time()
        ir_results = self.ir_model(ir, verbose=False)
        ir_time = (time.time() - t_ir) * 1000

        # 提取检测框
        detections = []

        # 可见光检测结果
        if len(vis_results) > 0 and vis_results[0].boxes is not None:
            boxes = vis_results[0].boxes
            for i in range(len(boxes)):
                box = boxes.xyxy[i].cpu().numpy()
                conf = float(boxes.conf[i])
                cls_id = int(boxes.cls[i])
                cls_name = vis_results[0].names.get(cls_id, f"class_{cls_id}")

                # 加权合并：可见光权重
                weighted_conf = conf * self.visible_weight * 2  # 结果会×原始权重

                if weighted_conf >= self.confidence_threshold:
                    detections.append(DetectionResult(
                        bbox=tuple(box),
                        confidence=conf,
                        class_id=cls_id,
                        class_name=cls_name,
                        source="visible",
                        temperature=None
                    ))

        # 红外检测结果
        if len(ir_results) > 0 and ir_results[0].boxes is not None:
            boxes = ir_results[0].boxes
            for i in range(len(boxes)):
                box = boxes.xyxy[i].cpu().numpy()
                conf = float(boxes.conf[i])
                cls_id = int(boxes.cls[i])
                cls_name = ir_results[0].names.get(cls_id, f"class_{cls_id}")

                # 红外加权：溺水类在红外中权重更高
                weighted_conf = conf * self.ir_weight * 2
                # 红外对溺水类检测更敏感
                if cls_name in ['drowning', 'person_underwater']:
                    weighted_conf *= 1.3

                if weighted_conf >= self.confidence_threshold:
                    # 红外帧中提取温度(如果可用)
                    temp = self._estimate_temperature(ir, box)

                    detections.append(DetectionResult(
                        bbox=tuple(box),
                        confidence=conf,
                        class_id=cls_id,
                        class_name=cls_name,
                        source="ir",
                        temperature=temp
                    ))

        # 去重合并 (基于IoU的NMS)
        merged = self._merge_detections(detections)

        fusion_time = (time.time() - t_start) * 1000

        return FusionResult(
            detections=merged,
            fusion_time_ms=fusion_time,
            visible_time_ms=vis_time,
            ir_time_ms=ir_time,
            strategy=FusionStrategy.LATE
        )

    def _early_fusion(self, visible: np.ndarray, ir: np.ndarray,
                      t_start: float) -> FusionResult:
        """早融合：双路输入拼接后统一检测"""
        t_v = time.time()

        # 确保尺寸一致
        if visible.shape != ir.shape:
            ir = cv2.resize(ir, (visible.shape[1], visible.shape[0]))

        # 通道拼接: [B, G, R, Ir_R, Ir_G, Ir_B] -> 6通道
        fused_input = np.concatenate([visible, ir], axis=2)

        # 6通道输入需要模型支持，这里简化为分别检测后平均
        # (完整的早融合需要修改模型第一层卷积的输入通道数)
        vis_results = self.visible_model(visible, verbose=False)
        ir_results = self.ir_model(ir, verbose=False)

        detections = []
        # 合并两路检测结果
        for results, source in [(vis_results, "visible"), (ir_results, "ir")]:
            if len(results) > 0 and results[0].boxes is not None:
                for box in results[0].boxes:
                    conf = float(box.conf[0])
                    if conf >= self.confidence_threshold:
                        detections.append(DetectionResult(
                            bbox=tuple(box.xyxy[0].cpu().numpy()),
                            confidence=conf,
                            class_id=int(box.cls[0]),
                            class_name=results[0].names.get(int(box.cls[0]), ""),
                            source=source
                        ))

        vis_time = (time.time() - t_v) * 1000
        merged = self._merge_detections(detections)

        return FusionResult(
            detections=merged,
            fusion_time_ms=(time.time() - t_start) * 1000,
            visible_time_ms=vis_time,
            ir_time_ms=vis_time,  # early fusion doesn't separate
            strategy=FusionStrategy.EARLY
        )

    def _decision_fusion(self, visible: np.ndarray, ir: np.ndarray,
                         t_start: float) -> FusionResult:
        """决策融合：各自检测，综合决策"""
        # 先用晚融合得到结果
        result = self._late_fusion(visible, ir, t_start)

        # 决策规则：红外检测到人体温度异常 + 可见光检测到异常姿态 -> 高置信度溺水
        for det in result.detections:
            if det.class_name == 'drowning':
                # 红外检测到的溺水权重更高
                if det.source == 'ir' and det.temperature and 30 < det.temperature < 40:
                    det.confidence = min(det.confidence * 1.5, 1.0)

        return result

    def _merge_detections(self, detections: List[DetectionResult]) -> List[DetectionResult]:
        """
        合并重叠检测框 (基于IoU的NMS + 加权平均)

        策略:
        - 同类别高IoU框：保留置信度最高者，合并来源信息
        - 边框重叠>0.5：按置信度加权平均位置
        """
        if len(detections) < 2:
            return detections

        # 按置信度排序
        detections.sort(key=lambda d: d.confidence, reverse=True)

        merged = []
        used = set()

        for i, det_i in enumerate(detections):
            if i in used:
                continue

            merged_det = det_i
            for j, det_j in enumerate(detections):
                if j <= i or j in used:
                    continue

                # 同类别且IoU > 阈值 -> 合并
                if det_i.class_id == det_j.class_id:
                    iou = self._compute_iou(det_i.bbox, det_j.bbox)
                    if iou > self.iou_threshold:
                        # 按置信度加权平均 bbox
                        w_i = det_i.confidence
                        w_j = det_j.confidence
                        w_sum = w_i + w_j

                        avg_bbox = tuple(
                            (det_i.bbox[k] * w_i + det_j.bbox[k] * w_j) / w_sum
                            for k in range(4)
                        )

                        merged_det = DetectionResult(
                            bbox=avg_bbox,
                            confidence=max(det_i.confidence, det_j.confidence),
                            class_id=det_i.class_id,
                            class_name=det_i.class_name,
                            source=f"{det_i.source}+{det_j.source}",
                            temperature=det_j.temperature or det_i.temperature
                        )
                        used.add(j)

            merged.append(merged_det)

        return merged

    @staticmethod
    def _compute_iou(box1, box2) -> float:
        """计算IoU"""
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])

        if x2 <= x1 or y2 <= y1:
            return 0.0

        inter = (x2 - x1) * (y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - inter

        return inter / union if union > 0 else 0.0

    @staticmethod
    def _estimate_temperature(ir_frame: np.ndarray, bbox: Tuple) -> Optional[float]:
        """从红外帧估计检测框内平均温度"""
        try:
            x1, y1, x2, y2 = [int(v) for v in bbox]
            h, w = ir_frame.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)

            if x2 <= x1 or y2 <= y1:
                return None

            region = ir_frame[y1:y2, x1:x2]
            if len(region.shape) == 3:
                region = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)

            return float(np.mean(region))
        except Exception:
            return None
