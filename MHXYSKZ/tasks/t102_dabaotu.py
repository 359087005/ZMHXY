"""
打宝图任务脚本。

前置流程（打开任务界面、找图标、点前往）由 renwujiemian.py 完成。
本脚本只处理点击"前往"之后的逻辑：

1. 等待到达 NPC 旁边，自动弹出对话框
2. 在右侧固定区域点击"听听无妨"图标
3. 等待约 20 分钟任务自动完成

模板图放在 templates/2宝图任务/ 下。
坐标和模板名均为占位值，请根据实际游戏截图替换。
"""

from __future__ import annotations

import random
from typing import Callable

Logger = Callable[[str], None]

# ─── 占位坐标 & 模板 ─────────────────────────────────────────────────────────

# "听听无妨"图标（对话框右侧）
LISTEN_TEMPLATE = "102BaoTuRenWu/jm_tingtingwufang.png"
LISTEN_SEARCH_RECT = (500, 200, 750, 500)         # 右侧区域，占位

ICON_THRESHOLD = 0.85
RANDOM_OFFSET = 15

PANEL_WAIT_TIMEOUT_SEC = 30.0
POLL_INTERVAL_RANGE = (2.0, 4.0)
AFTER_CLICK_WAIT_SEC = 2.0
TASK_WAIT_RANGE = (1150.0, 1250.0)    # 约 20 分钟，随机 1150~1250 秒


def run(bot, check_stop, wait_or_stop, stop_event):
    """打宝图主流程，renwujiemian.py 点击前往后调用。"""
    import time

    bot.log("开始执行打宝图逻辑")

    # 1. 轮询等待"听听无妨"图标出现
    bot.log("等待到达 NPC，轮询对话框...")
    deadline = time.monotonic() + PANEL_WAIT_TIMEOUT_SEC
    found = False
    while time.monotonic() < deadline:
        check_stop(stop_event)
        match = bot.find_image(
            LISTEN_TEMPLATE,
            threshold=ICON_THRESHOLD,
            search_rect=LISTEN_SEARCH_RECT,
            log_miss=True,
        )
        if match:
            x, y, score = match
            bot.log(f"找到[听听无妨] score={score:.4f}，点击。")
            bot.click(x, y, RANDOM_OFFSET)
            wait_or_stop(bot, stop_event, AFTER_CLICK_WAIT_SEC)
            found = True
            break

        interval = random.uniform(*POLL_INTERVAL_RANGE)
        wait_or_stop(bot, stop_event, interval)

    if not found:
        bot.log("等待对话框超时，终止打宝图。")
        return

    # 2. 等待任务自动完成（约 20 分钟）
    task_wait = random.uniform(*TASK_WAIT_RANGE)
    bot.log(f"打宝图进行中，等待 {task_wait:.0f}s（约 {task_wait / 60:.1f} 分钟）")
    wait_or_stop(bot, stop_event, task_wait)

    bot.log("打宝图任务完成。")
