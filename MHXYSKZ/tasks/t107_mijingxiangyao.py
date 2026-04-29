"""
秘境降妖任务脚本。

前置流程（打开任务界面、找图标、点前往）由 renwujiemian.py 完成。
本脚本只处理点击"前往"之后的逻辑：

1. 输入 Alt+C
2. 在指定区域查找 jm_mjxy / jm_mjxy_tj
3. 基于命中中心坐标向右偏移 155px 后点击
4. 在指定区域查找并点击 jm_mjxy_yyl
5. 如找到 mjxy_jr，则点击后等待 1 秒，再点击固定坐标 (473, 350)
6. 在指定区域查找并点击 mjxy_jxtz，等待 2 秒
7. 点击固定坐标 (708, 250) 后结束逻辑

模板图放在 templates/107MiJingXiangyao/ 下。

依赖模板：
- MJXY/jm_mjxy
- MJXY/jm_mjxy_tj
- MJXY/jm_mjxy_yyl
- MJXY/mjxy_jr
- MJXY/mjxy_jxtz
"""

from __future__ import annotations

from typing import Callable, Iterable

from tasks.shared_rects import HUODONG_SEARCH_RECT

Logger = Callable[[str], None]
MatchResult = tuple[int, int, float]


class TaskAbort(Exception):
    """用于按业务条件中止当前任务流程。"""

# 如果你的游戏实际快捷键不是 Alt+C，先改这里。
OPEN_MIJING_HOTKEY = ("alt", "c")

MIJING_TEMPLATES = (
    "107MiJingXiangyao/jm_mjxy",
    "107MiJingXiangyao/jm_mjxy_tj",
)
YIYOULI_TEMPLATE = "107MiJingXiangyao/jm_mjxy_yyl"
ENTER_TEMPLATE = "107MiJingXiangyao/mjxy_jr"
CONTINUE_TEMPLATE = "107MiJingXiangyao/mjxy_jxtz"

YIYOULI_SEARCH_RECT = (561, 200, 769, 448)
ENTER_SEARCH_RECT = (152, 470, 297, 511)
CONTINUE_SEARCH_RECT = (633, 444, 712, 517)

MIJING_OFFSET_X = 155
MIJING_CLICK_RANDOM_OFFSET = 10
COMMON_CLICK_RANDOM_OFFSET = 5

ENTER_FALLBACK_CLICK = (473, 350)
FINAL_CLICK = (708, 250)

MATCH_THRESHOLD = 0.85
OPEN_WAIT_SEC = 1.5

def _find_first_match(
    bot,
    check_stop,
    stop_event,
    templates: Iterable[str],
    search_rect: tuple[int, int, int, int],
    *,
    label: str,
) -> tuple[MatchResult | None, str | None]:
    for template in templates:
        check_stop(stop_event)
        match = bot.find_image(
            template,
            threshold=MATCH_THRESHOLD,
            search_rect=search_rect,
            log_miss=False,
        )
        if match:
            x, y, score = match
            bot.log(
                f"找到{label}模板 {template} score={score:.4f}，"
                f"中心=({x},{y})"
            )
            return match, template
    return None, None


def _find_required_match(
    bot,
    check_stop,
    stop_event,
    templates: Iterable[str],
    search_rect: tuple[int, int, int, int],
    *,
    label: str,
) -> tuple[MatchResult, str]:
    match, template = _find_first_match(
        bot,
        check_stop,
        stop_event,
        templates,
        search_rect,
        label=label,
    )
    if not match or not template:
        names = " / ".join(templates)
        bot.log(
            f"在区域 {search_rect} 未找到{label}模板: {names}，终止秘境降妖逻辑。"
        )
        raise TaskAbort(f"missing required template: {label}")
    return match, template


def run(bot, check_stop, wait_or_stop, stop_event):
    """秘境降妖主流程，renwujiemian.py 点击前往后调用。"""
    bot.log("开始执行秘境降妖逻辑")
    bot.log("准备输入 Alt+C 打开秘境界面。")
    bot.hotkey(*OPEN_MIJING_HOTKEY)
    wait_or_stop(bot, stop_event, OPEN_WAIT_SEC)

    try:
        mijing_match, template = _find_required_match(
            bot,
            check_stop,
            stop_event,
            MIJING_TEMPLATES,
            HUODONG_SEARCH_RECT,
            label="秘境降妖入口",
        )
        mijing_x, mijing_y, _score = mijing_match
        target_x = mijing_x + MIJING_OFFSET_X
        bot.log(
            f"基于 {template} 中心=({mijing_x},{mijing_y})，"
            f"右移 {MIJING_OFFSET_X}px 后点击 ({target_x},{mijing_y})。"
        )
        bot.click(target_x, mijing_y, MIJING_CLICK_RANDOM_OFFSET)
        wait_or_stop(bot, stop_event, 2)

        yiyouli_match, _template = _find_required_match(
            bot,
            check_stop,
            stop_event,
            (YIYOULI_TEMPLATE,),
            YIYOULI_SEARCH_RECT,
            label="已游历",
        )
        yiyouli_x, yiyouli_y, yiyouli_score = yiyouli_match
        bot.log(
            f"找到已游历 score={yiyouli_score:.4f}，"
            f"点击中心=({yiyouli_x},{yiyouli_y})。"
        )
        bot.click(yiyouli_x, yiyouli_y, COMMON_CLICK_RANDOM_OFFSET)
        wait_or_stop(bot, stop_event, 2)

        enter_match, _template = _find_first_match(
            bot,
            check_stop,
            stop_event,
            (ENTER_TEMPLATE,),
            ENTER_SEARCH_RECT,
            label="进入",
        )
        if enter_match:
            enter_x, enter_y, enter_score = enter_match
            bot.log(
                f"找到进入按钮 score={enter_score:.4f}，"
                f"点击中心=({enter_x},{enter_y})。"
            )
            bot.click(enter_x, enter_y, COMMON_CLICK_RANDOM_OFFSET)
            wait_or_stop(bot, stop_event, 2)
            check_stop(stop_event)
            bot.log(
                f"按流程补点固定坐标 ({ENTER_FALLBACK_CLICK[0]},{ENTER_FALLBACK_CLICK[1]})。"
            )
            bot.click(ENTER_FALLBACK_CLICK[0], ENTER_FALLBACK_CLICK[1], 0)
        else:
            bot.log("未找到进入按钮 mjxy_jr，直接继续检查继续挑战。")

        wait_or_stop(bot, stop_event, 2)

        continue_match, _template = _find_required_match(
            bot,
            check_stop,
            stop_event,
            (CONTINUE_TEMPLATE,),
            CONTINUE_SEARCH_RECT,
            label="继续挑战",
        )
        continue_x, continue_y, continue_score = continue_match
        bot.log(
            f"找到继续挑战 score={continue_score:.4f}，"
            f"点击中心=({continue_x},{continue_y})。"
        )
        bot.click(continue_x, continue_y, COMMON_CLICK_RANDOM_OFFSET)
        wait_or_stop(bot, stop_event, 2)

        check_stop(stop_event)
        bot.log(f"点击结束坐标 ({FINAL_CLICK[0]},{FINAL_CLICK[1]})。")
        bot.click(FINAL_CLICK[0], FINAL_CLICK[1], 0)
        bot.log("秘境降妖逻辑完成。")
    except TaskAbort:
        return
