"""
打宝图任务脚本。

前置流程（打开任务界面、找图标、点前往）由 renwujiemian.py 完成。
本脚本只处理点击"前往"之后的逻辑：

1. 等待到达 NPC 旁边，自动弹出对话框
2. 在右侧固定区域点击"听听无妨"图标
3. 轮询右下角战斗取消按钮：连续 30 秒检测不到，判定打宝图已结束

模板图放在 templates/102BaoTuRenWu/ 下。
"听听无妨"的搜索区域为占位值，请根据实际游戏截图替换。
"""

from __future__ import annotations

import random
import time
from typing import Callable

from tasks.shared_rects import CANCEL_BUTTON_RECT

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

# 右下角战斗中的取消按钮（与 201ZhuaGui/quxiao.png 是同一张图）。
BATTLE_CANCEL_TEMPLATE = "102BaoTuRenWu/quxiao.png"
# 战斗动画会让取消按钮与静态模板有差异，真实战斗帧实测约 0.805，因此单独用 0.78。
BATTLE_CANCEL_THRESHOLD = 0.78
BATTLE_POLL_INTERVAL_SEC = 2.0
# 右下角连续这么久检测不到取消按钮，判定打宝图已结束（接任务后跑图到第一场战斗不超过 30 秒）。
BATTLE_END_IDLE_SEC = 30.0


def _wait_for_dabaotu_finish(bot, check_stop, wait_or_stop, stop_event):
    """轮询右下角取消按钮，连续 BATTLE_END_IDLE_SEC 秒检测不到即判定打宝图结束。

    从点击"听听无妨"后开始计时，每次检测到取消按钮都会重新计时。
    """
    bot.log(
        f"打宝图进行中：右下角连续 {BATTLE_END_IDLE_SEC:.0f} 秒检测不到取消按钮，"
        "即判定打宝图结束。"
    )
    last_battle_at = time.monotonic()
    seen_battle = False
    in_battle = False

    while True:
        check_stop(stop_event)
        match = bot.find_image(
            BATTLE_CANCEL_TEMPLATE,
            threshold=BATTLE_CANCEL_THRESHOLD,
            search_rect=CANCEL_BUTTON_RECT,
            log_miss=False,
        )
        now = time.monotonic()
        if match:
            if not in_battle:
                bot.log("检测到右下角取消按钮，打宝图战斗中。")
            in_battle = True
            seen_battle = True
            last_battle_at = now
        else:
            if in_battle:
                bot.log(
                    f"右下角未检测到取消按钮，开始计时 {BATTLE_END_IDLE_SEC:.0f} 秒。"
                )
            in_battle = False
            idle_sec = now - last_battle_at
            if idle_sec >= BATTLE_END_IDLE_SEC:
                if seen_battle:
                    bot.log(
                        f"右下角连续 {idle_sec:.0f} 秒未检测到取消按钮，判定打宝图已结束。"
                    )
                else:
                    bot.log(f"接任务后 {idle_sec:.0f} 秒内未检测到战斗，结束打宝图。")
                return

        wait_or_stop(bot, stop_event, BATTLE_POLL_INTERVAL_SEC)


def run(bot, check_stop, wait_or_stop, stop_event):
    """打宝图主流程，renwujiemian.py 点击前往后调用。"""
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

    # 2. 等待打宝图结束：右下角连续 30 秒检测不到取消按钮
    _wait_for_dabaotu_finish(bot, check_stop, wait_or_stop, stop_event)

    bot.log("打宝图任务完成。")
