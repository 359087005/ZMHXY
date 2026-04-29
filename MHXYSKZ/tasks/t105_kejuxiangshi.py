"""
科举乡试任务脚本。

前置流程（打开任务界面、找图标、点前往）由 renwujiemian.py 完成。
本脚本只处理点击"前往"之后的逻辑：

1. 等待答题界面弹出
2. 每道题 4 选 1，随机点击一个选项
3. 重复 10 次
4. 屏幕正中心右键点击关闭面板

模板图放在 templates/6科举乡试/ 下。
坐标和模板名均为占位值，请根据实际游戏截图替换。
"""

from __future__ import annotations

import random
from typing import Callable

Logger = Callable[[str], None]

# ─── 占位坐标 & 模板 ─────────────────────────────────────────────────────────

# 4 个选项的点击坐标（固定位置），占位
OPTION_COORDS = [
    (250, 300),   # 选项 A，占位
    (350, 300),   # 选项 B，占位
    (450, 300),   # 选项 C，占位
    (550, 300),   # 选项 D，占位
]

# 屏幕中心坐标（用于最后右键关闭面板），占位
SCREEN_CENTER = (400, 300)

# 答题界面是否已弹出的判定模板
QUIZ_PANEL_TEMPLATE = "105KeJuXiangShi/kj_panel.png"
QUIZ_PANEL_RECT = (200, 100, 600, 500)            # 占位

ICON_THRESHOLD = 0.85
RANDOM_OFFSET = 15

TOTAL_CLICKS = 10
CLICK_INTERVAL_RANGE = (1.0, 2.0)
PANEL_WAIT_TIMEOUT_SEC = 30.0
POLL_INTERVAL_RANGE = (2.0, 4.0)
AFTER_CLOSE_WAIT_SEC = 1.0


def run(bot, check_stop, wait_or_stop, stop_event):
    """科举乡试主流程，renwujiemian.py 点击前往后调用。"""
    import time

    bot.log("开始执行科举乡试逻辑")

    # 1. 轮询等待答题界面弹出
    bot.log("等待答题界面弹出...")
    deadline = time.monotonic() + PANEL_WAIT_TIMEOUT_SEC
    panel_found = False
    while time.monotonic() < deadline:
        check_stop(stop_event)
        match = bot.find_image(
            QUIZ_PANEL_TEMPLATE,
            threshold=ICON_THRESHOLD,
            search_rect=QUIZ_PANEL_RECT,
            log_miss=False,
        )
        if match:
            bot.log("答题界面已弹出。")
            panel_found = True
            break
        interval = random.uniform(*POLL_INTERVAL_RANGE)
        wait_or_stop(bot, stop_event, interval)

    if not panel_found:
        bot.log("等待答题界面超时，终止科举乡试。")
        return

    # 2. 随机点击 4 选 1，共 10 次
    for click_num in range(1, TOTAL_CLICKS + 1):
        check_stop(stop_event)
        choice = random.choice(OPTION_COORDS)
        x, y = choice
        bot.log(f"第 {click_num}/{TOTAL_CLICKS} 次答题，随机选择 ({x}, {y})")
        bot.click(x, y, RANDOM_OFFSET)

        interval = random.uniform(*CLICK_INTERVAL_RANGE)
        wait_or_stop(bot, stop_event, interval)

    # 3. 屏幕正中心右键关闭面板
    cx, cy = SCREEN_CENTER
    bot.log(f"答题完毕，右键关闭面板 ({cx}, {cy})")
    bot.right_click(cx, cy, RANDOM_OFFSET)
    wait_or_stop(bot, stop_event, AFTER_CLOSE_WAIT_SEC)

    bot.log("科举乡试任务完成。")
