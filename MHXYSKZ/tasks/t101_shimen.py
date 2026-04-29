"""
师门任务脚本。

前置流程（打开活动界面、找图标、点参加）由 renwujiemian.py 完成。
点击参加后游戏全自动执行师门任务，脚本只需等待约 15 分钟。
"""

from __future__ import annotations

import random
from typing import Callable

Logger = Callable[[str], None]

TASK_WAIT_RANGE = (850.0, 950.0)    # 约 15 分钟，随机 850~950 秒


def run(bot, check_stop, wait_or_stop, stop_event):
    """师门任务主流程，renwujiemian.py 点击参加后调用。"""
    bot.log("开始执行师门任务逻辑")

    task_wait = random.uniform(*TASK_WAIT_RANGE)
    bot.log(f"师门任务进行中，等待 {task_wait:.0f}s（约 {task_wait / 60:.1f} 分钟）")
    wait_or_stop(bot, stop_event, task_wait)

    bot.log("师门任务完成。")
