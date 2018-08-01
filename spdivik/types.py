"""Reusable typings used across modules"""
from typing import Callable, Tuple, Dict, NamedTuple, List, Optional

import numpy as np

Table = np.ndarray  # 2D matrix
Centroids = Table
IntLabels = np.ndarray
BoolFilter = np.ndarray
Data = Table
Quality = float
SegmentationMethod = Callable[[Data], Tuple[IntLabels, Centroids]]
ScoredSegmentation = Tuple[IntLabels, Centroids, Quality]
SelfScoringSegmentation = Callable[[Data], ScoredSegmentation]
StopCondition = Callable[[Data], bool]
Filter = Callable[[Data], Tuple[BoolFilter, float]]
FilterName = str
Filters = Dict[FilterName, BoolFilter]
Thresholds = Dict[FilterName, float]
DivikResult = NamedTuple('DivikResult', [
    ('centroids', Centroids),
    ('quality', float),
    ('partition', IntLabels),
    ('filters', Filters),
    ('thresholds', Thresholds),
    ('merged', IntLabels),
    ('subregions', List[Optional['DivikResult']]),
])