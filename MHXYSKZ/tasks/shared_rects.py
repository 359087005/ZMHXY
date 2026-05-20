"""
任务间共用的识别区域常量。

后续任务如果需要在活动界面、背包或战斗状态里找图，
优先直接复用这里的公共矩形范围。
"""

from __future__ import annotations

HUODONG_SEARCH_RECT = (174, 117, 749, 398)
BAG_SEARCH_RANGE = (402, 159, 717, 469)
CANCEL_BUTTON_RECT = (737, 519, 800, 600)

__all__ = [
    "HUODONG_SEARCH_RECT",
    "BAG_SEARCH_RANGE",
    "CANCEL_BUTTON_RECT",
]
