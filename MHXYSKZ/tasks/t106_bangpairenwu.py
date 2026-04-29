"""
帮派任务脚本。

前置流程（打开任务界面、找图标、点前往）由 renwujiemian.py 完成。
本脚本只处理点击"前往"之后的逻辑：

1. 等待到达帮派
2. 在固定区域找到帮派任务图标，点击一次
3. 等待约 2 小时任务自动完成（70 个子任务）

模板图放在 templates/7帮派任务/ 下。
坐标和模板名均为占位值，请根据实际游戏截图替换。
"""

from __future__ import annotations

import random
from typing import Callable

Logger = Callable[[str], None]

# ─── 占位坐标 & 模板 ─────────────────────────────────────────────────────────

# 帮派任务图标
BANGPAI_TEMPLATE = "106BangPaiRenWu/bp_task.png"
BANGPAI_SEARCH_RECT = (300, 200, 600, 500)        # 占位

ICON_THRESHOLD = 0.85
RANDOM_OFFSET = 15

PANEL_WAIT_TIMEOUT_SEC = 30.0
POLL_INTERVAL_RANGE = (2.0, 4.0)
AFTER_CLICK_WAIT_SEC = 2.0


def run(bot, check_stop, wait_or_stop, stop_event):
    """帮派任务主流程，renwujiemian.py 点击前往后调用。"""
    import time

    bot.log("开始执行帮派任务逻辑")

    # 1. 轮询等待帮派任务图标出现
    bot.log("等待到达帮派，轮询帮派任务图标...")
    deadline = time.monotonic() + PANEL_WAIT_TIMEOUT_SEC
    while time.monotonic() < deadline:
        check_stop(stop_event)
        match = bot.find_image(
            BANGPAI_TEMPLATE,
            threshold=ICON_THRESHOLD,
            search_rect=BANGPAI_SEARCH_RECT,
            log_miss=False,
        )
        if match:
            x, y, score = match
            bot.log(f"找到帮派任务图标 score={score:.4f}，点击。")
            bot.click(x, y, RANDOM_OFFSET)
            wait_or_stop(bot, stop_event, AFTER_CLICK_WAIT_SEC)
            bot.log("帮派任务已接取，等待自动完成（约 2 小时）。")
            return

        interval = random.uniform(*POLL_INTERVAL_RANGE)
        wait_or_stop(bot, stop_event, interval)

    bot.log("等待帮派任务图标超时，终止帮派任务。")
