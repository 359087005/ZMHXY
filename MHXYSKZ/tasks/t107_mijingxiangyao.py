"""
秘境降妖任务脚本。

由 game_logic.py 直接调用（不经过活动界面调度），流程：

1. 输入 Alt+C 打开活动界面
2. 在活动列表区域查找 jm_mjxy / jm_mjxy_tj，基于命中中心向右偏移 155px 后点击
3. 在指定区域查找并点击 jm_mjxy_yyl（已游历）
4. 如找到 mjxy_jr（进入），点击后等待 2 秒，再点击固定坐标 (473, 350)
5. 连续挑战 3 次：等待并点击 mjxy_jxtz（继续挑战），确认右下角出现取消按钮（进入战斗）；
   战斗中不计等待超时，战斗结束后再点下一次继续挑战
6. 第 3 次挑战的战斗结束（右下角连续 6 秒检测不到取消按钮）后，
   点击固定坐标 (708, 250) 离开秘境

模板图放在 templates/107MiJingXiangyao/ 下。

依赖模板：
- 107MiJingXiangyao/jm_mjxy
- 107MiJingXiangyao/jm_mjxy_tj
- 107MiJingXiangyao/jm_mjxy_yyl
- 107MiJingXiangyao/mjxy_jr
- 107MiJingXiangyao/mjxy_jxtz

复用模板：
- 201ZhuaGui/quxiao.png（右下角战斗取消按钮）
"""

from __future__ import annotations

import time
from typing import Callable, Iterable

from tasks.shared_rects import CANCEL_BUTTON_RECT, HUODONG_SEARCH_RECT

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
# 右下角战斗中的取消按钮，与抓鬼、宝图共用同一张图。
BATTLE_CANCEL_TEMPLATE = "201ZhuaGui/quxiao.png"

YIYOULI_SEARCH_RECT = (561, 200, 769, 448)
ENTER_SEARCH_RECT = (152, 470, 297, 511)
CONTINUE_SEARCH_RECT = (633, 444, 712, 517)

MIJING_OFFSET_X = 155
MIJING_CLICK_RANDOM_OFFSET = 10
COMMON_CLICK_RANDOM_OFFSET = 5

ENTER_FALLBACK_CLICK = (473, 350)
# 三次挑战全部结束后，点击此坐标离开秘境。
LEAVE_MIJING_CLICK = (708, 250)

MATCH_THRESHOLD = 0.85
# 战斗动画会让取消按钮与静态模板有差异，真实战斗帧实测约 0.805，因此单独用 0.78。
BATTLE_CANCEL_THRESHOLD = 0.78
OPEN_WAIT_SEC = 1.5

# 每次进入秘境需要点击继续挑战的次数。
CHALLENGE_TIMES = 3
POLL_INTERVAL_SEC = 2.0
# 等待继续挑战出现的最长时间；战斗中（检测到取消按钮）的时间不计入。
CONTINUE_WAIT_TIMEOUT_SEC = 30.0
# 点击继续挑战后，等待进入战斗（右下角出现取消按钮）的最长时间。
BATTLE_START_TIMEOUT_SEC = 30.0
# 最后一次挑战后，右下角连续这么久检测不到取消按钮，判定战斗结束。
# 连续 3 次轮询都未命中才算结束，用于过滤偶发的抓帧丢失。
BATTLE_END_CONFIRM_SEC = 6.0


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


def _is_in_battle(bot, check_stop, stop_event) -> bool:
    """右下角能检测到取消按钮，即视为战斗中。"""
    check_stop(stop_event)
    match = bot.find_image(
        BATTLE_CANCEL_TEMPLATE,
        threshold=BATTLE_CANCEL_THRESHOLD,
        search_rect=CANCEL_BUTTON_RECT,
        log_miss=False,
    )
    return match is not None


def _wait_and_click_continue(
    bot,
    check_stop,
    wait_or_stop,
    stop_event,
    *,
    challenge_index: int,
):
    """等待继续挑战出现并点击；战斗中（检测到取消按钮）不计等待超时。"""
    idle_since = time.monotonic()
    in_battle = False
    while True:
        if _is_in_battle(bot, check_stop, stop_event):
            if not in_battle:
                bot.log("右下角检测到取消按钮，战斗中，等战斗结束后再点继续挑战。")
            in_battle = True
            idle_since = time.monotonic()
        else:
            if in_battle:
                bot.log(
                    f"右下角未检测到取消按钮，查找第 {challenge_index}/{CHALLENGE_TIMES} 次继续挑战。"
                )
            in_battle = False
            match, _template = _find_first_match(
                bot,
                check_stop,
                stop_event,
                (CONTINUE_TEMPLATE,),
                CONTINUE_SEARCH_RECT,
                label="继续挑战",
            )
            if match:
                x, y, _score = match
                bot.log(f"点击第 {challenge_index}/{CHALLENGE_TIMES} 次继续挑战 ({x},{y})。")
                bot.click(x, y, COMMON_CLICK_RANDOM_OFFSET)
                return

            idle_sec = time.monotonic() - idle_since
            if idle_sec >= CONTINUE_WAIT_TIMEOUT_SEC:
                bot.log(
                    f"{idle_sec:.0f} 秒内未找到第 {challenge_index} 次继续挑战，"
                    "终止秘境降妖逻辑。"
                )
                raise TaskAbort("missing continue challenge")

        wait_or_stop(bot, stop_event, POLL_INTERVAL_SEC)


def _wait_for_battle_start(
    bot,
    check_stop,
    wait_or_stop,
    stop_event,
    *,
    challenge_index: int,
):
    """点击继续挑战后，确认右下角出现取消按钮（已进入战斗）。"""
    started_at = time.monotonic()
    while True:
        if _is_in_battle(bot, check_stop, stop_event):
            bot.log(f"第 {challenge_index}/{CHALLENGE_TIMES} 次挑战已进入战斗。")
            return

        waited_sec = time.monotonic() - started_at
        if waited_sec >= BATTLE_START_TIMEOUT_SEC:
            bot.log(
                f"点击第 {challenge_index} 次继续挑战后 {waited_sec:.0f} 秒内未进入战斗，"
                "终止秘境降妖逻辑。"
            )
            raise TaskAbort("battle did not start")

        wait_or_stop(bot, stop_event, POLL_INTERVAL_SEC)


def _wait_for_battle_end(bot, check_stop, wait_or_stop, stop_event):
    """右下角连续 BATTLE_END_CONFIRM_SEC 秒检测不到取消按钮，判定战斗结束。"""
    last_battle_at = time.monotonic()
    while True:
        wait_or_stop(bot, stop_event, POLL_INTERVAL_SEC)
        if _is_in_battle(bot, check_stop, stop_event):
            last_battle_at = time.monotonic()
            continue

        idle_sec = time.monotonic() - last_battle_at
        if idle_sec >= BATTLE_END_CONFIRM_SEC:
            bot.log(
                f"右下角连续 {idle_sec:.0f} 秒未检测到取消按钮，"
                f"第 {CHALLENGE_TIMES}/{CHALLENGE_TIMES} 次挑战战斗结束。"
            )
            return


def run(bot, check_stop, wait_or_stop, stop_event):
    """秘境降妖主流程，由 game_logic.py 直接调用。"""
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

        for challenge_index in range(1, CHALLENGE_TIMES + 1):
            _wait_and_click_continue(
                bot,
                check_stop,
                wait_or_stop,
                stop_event,
                challenge_index=challenge_index,
            )
            wait_or_stop(bot, stop_event, 2)
            _wait_for_battle_start(
                bot,
                check_stop,
                wait_or_stop,
                stop_event,
                challenge_index=challenge_index,
            )

        # 第 3 次挑战的战斗结束：右下角没有取消按钮，且已点击 3 次继续挑战。
        _wait_for_battle_end(bot, check_stop, wait_or_stop, stop_event)
        wait_or_stop(bot, stop_event, 2)

        check_stop(stop_event)
        leave_x, leave_y = LEAVE_MIJING_CLICK
        bot.log(f"已完成 {CHALLENGE_TIMES} 次挑战，点击 ({leave_x},{leave_y}) 离开秘境。")
        bot.click(leave_x, leave_y, 0)
        wait_or_stop(bot, stop_event, 2)
        bot.log("秘境降妖逻辑完成。")
    except TaskAbort:
        return
