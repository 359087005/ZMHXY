"""
挖宝图任务脚本。

从 game_logic.py 中摘出，独立为单任务模块。
模板图放在 templates/102BaoTuRenWu/ 下。

依赖模板：
- 102BaoTuRenWu/bb_baotu.png
- 102BaoTuRenWu/jm_shiyong.png
- 102BaoTuRenWu/quxiao.png
"""

from __future__ import annotations

from typing import Callable

from tasks.shared_rects import BAG_SEARCH_RANGE, CANCEL_BUTTON_RECT

Logger = Callable[[str], None]
MatchResult = tuple[int, int, float]

# 如果你的游戏实际快捷键不是 Alt+E，先改这里。
OPEN_BAG_HOTKEY = ("alt", "e")

BAOTU_TEMPLATE = "102BaoTuRenWu/bb_baotu.png"
USE_BUTTON_TEMPLATE = "102BaoTuRenWu/jm_shiyong"
CANCEL_TEMPLATE = "102BaoTuRenWu/quxiao.png"

USE_BUTTON_RECT = (619, 473, 712, 525)

BAG_SCROLL_START = (588, 463)
BAG_SCROLL_END = (588, 163)

MAX_BAG_SCROLLS = 3
MAX_NO_USE_MISSES = 4

BAOTU_THRESHOLD = 0.90
USE_BUTTON_THRESHOLD = 0.90
CANCEL_THRESHOLD = 0.90

RANDOM_OFFSET = 15
OPEN_BAG_WAIT_SEC = 0.8
BAG_SCROLL_SETTLE_SEC = 0.6
AFTER_BAOTU_DOUBLE_CLICK_WAIT_SEC = 20.0
AFTER_USE_CLICK_WAIT_SEC = 20.0
BATTLE_WAIT_SEC = 20.0
NO_USE_RETRY_WAIT_SEC = 5.0


def _find_baotu_in_bag(bot, check_stop, wait_or_stop, stop_event) -> MatchResult | None:
    for attempt in range(MAX_BAG_SCROLLS + 1):
        check_stop(stop_event)
        match = bot.find_image(
            BAOTU_TEMPLATE,
            threshold=BAOTU_THRESHOLD,
            search_rect=BAG_SEARCH_RANGE,
            log_miss=False,
        )
        if match:
            if attempt > 0:
                bot.log(f"翻页后找到宝图，第 {attempt} 次翻页命中。")
            return match

        if attempt == 0:
            bot.log("背包首页未找到宝图..")

        if attempt >= MAX_BAG_SCROLLS:
            return None

        bot.log(f"第 {attempt + 1} 次向上翻页查找宝图。")
        bot.drag(
            BAG_SCROLL_START[0],
            BAG_SCROLL_START[1],
            BAG_SCROLL_END[0],
            BAG_SCROLL_END[1],
        )
        wait_or_stop(bot, stop_event, BAG_SCROLL_SETTLE_SEC)

    return None


def _wait_for_use_button(bot, check_stop, wait_or_stop, stop_event) -> bool:
    consecutive_misses = 0

    while True:
        check_stop(stop_event)
        use_match = bot.find_image(
            USE_BUTTON_TEMPLATE,
            threshold=USE_BUTTON_THRESHOLD,
            search_rect=USE_BUTTON_RECT,
            log_miss=False,
        )
        if use_match:
            x, y, score = use_match
            bot.log(f"识别到使用按钮 score={score:.4f}，准备点击。")
            bot.click(x, y, RANDOM_OFFSET)
            wait_or_stop(bot, stop_event, AFTER_USE_CLICK_WAIT_SEC)
            consecutive_misses = 0
            continue

        bot.log("界面没有使用按钮")
        cancel_match = bot.find_image(
            CANCEL_TEMPLATE,
            threshold=CANCEL_THRESHOLD,
            search_rect=CANCEL_BUTTON_RECT,
            log_miss=False,
        )
        if cancel_match:
            bot.log("正在战斗!")
            consecutive_misses = 0
            wait_or_stop(bot, stop_event, BATTLE_WAIT_SEC)
            continue

        consecutive_misses += 1
        if consecutive_misses >= MAX_NO_USE_MISSES:
            bot.log("没有宝图了.")
            return False

        wait_or_stop(bot, stop_event, NO_USE_RETRY_WAIT_SEC)


def run(bot, check_stop, wait_or_stop, stop_event):
    """挖宝图主流程，由 game_logic.py 调用。"""
    bot.log("开始执行挖宝图逻辑")
    bot.log("准备打开背包。")
    bot.hotkey(*OPEN_BAG_HOTKEY)
    wait_or_stop(bot, stop_event, OPEN_BAG_WAIT_SEC)

    baotu_match = _find_baotu_in_bag(bot, check_stop, wait_or_stop, stop_event)
    if not baotu_match:
        bot.log("背包中未找到宝图，结束。")
        return

    x, y, score = baotu_match
    bot.log(f"识别到宝图 score={score:.4f}，准备双击。")
    bot.double_click(x, y, RANDOM_OFFSET)
    wait_or_stop(bot, stop_event, AFTER_BAOTU_DOUBLE_CLICK_WAIT_SEC)

    _wait_for_use_button(bot, check_stop, wait_or_stop, stop_event)
    bot.log("挖宝图流程结束。")
