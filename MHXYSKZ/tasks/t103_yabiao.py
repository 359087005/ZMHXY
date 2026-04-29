"""
押镖任务脚本。

前置流程（打开活动界面、找图标、点参加）由 renwujiemian.py 完成。
本脚本处理点击参加之后的逻辑：

1. 轮询匹配 jm_biaoju.png，匹配成功后点击
2. 等待 3 分钟
3. 重复以上步骤共 3 轮
4. 任务结束

模板图放在 templates/YBiao/ 下。
"""

from __future__ import annotations

import random
from typing import Callable

Logger = Callable[[str], None]

BIAOJU_TEMPLATE = "103YaBiao/jm_biaoju.png"
BIAOJU_SEARCH_RECT = (550, 230, 770, 500)

ICON_THRESHOLD = 0.80
RANDOM_OFFSET = 10

TOTAL_ROUNDS = 3
ROUND_WAIT_SEC = 180.0          # 每轮等待 3 分钟
POLL_TIMEOUT_SEC = 60.0         # 每轮轮询超时
POLL_INTERVAL_RANGE = (2.0, 4.0)
AFTER_CLICK_WAIT_SEC = 2.0


def _poll_and_click_biaoju(bot, check_stop, wait_or_stop, stop_event, round_num):
    """轮询等待镖局图标出现并点击。"""
    import time
    deadline = time.monotonic() + POLL_TIMEOUT_SEC
    bot.log(f"第 {round_num} 轮：轮询等待镖局图标...")

    while time.monotonic() < deadline:
        check_stop(stop_event)
        match = bot.find_image(
            BIAOJU_TEMPLATE,
            threshold=ICON_THRESHOLD,
            search_rect=BIAOJU_SEARCH_RECT,
            log_miss=False,
        )
        if match:
            x, y, score = match
            bot.log(f"第 {round_num} 轮：找到镖局图标 score={score:.4f}，点击。")
            bot.click(x, y, RANDOM_OFFSET)
            wait_or_stop(bot, stop_event, AFTER_CLICK_WAIT_SEC)
            return True

        interval = random.uniform(*POLL_INTERVAL_RANGE)
        wait_or_stop(bot, stop_event, interval)

    bot.log(f"第 {round_num} 轮：等待镖局图标超时。")
    return False


def run(bot, check_stop, wait_or_stop, stop_event):
    """押镖主流程，renwujiemian.py 点击参加后调用。"""
    bot.log("开始执行押镖逻辑")

    for i in range(1, TOTAL_ROUNDS + 1):
        check_stop(stop_event)

        if not _poll_and_click_biaoju(bot, check_stop, wait_or_stop, stop_event, i):
            bot.log("未找到镖局图标，终止押镖。")
            return

        bot.log(f"第 {i} 轮完成，等待 {ROUND_WAIT_SEC:.0f}s。")
        wait_or_stop(bot, stop_event, ROUND_WAIT_SEC)

    bot.log("押镖任务完成。")
