"""
抓鬼任务脚本。

模板图放在 templates/5抓鬼任务/ 下。

依赖模板：
- 201ZhuaGui/jm_zg2.png
- 201ZhuaGui/jm_zg.png
- 201ZhuaGui/jm_zgrw.png
- 201ZhuaGui/jm_jxzg.png

复用模板：
- 201ZhuaGui/quxiao.png
"""

from __future__ import annotations

from typing import Callable, Iterable

from tasks.shared_rects import CANCEL_BUTTON_RECT, HUODONG_SEARCH_RECT

Logger = Callable[[str], None]
MatchResult = tuple[int, int, float]

OVER_20_OPTION_KEY = "zhua_gui_over_20"
ROUNDS_OPTION_KEY = "zhua_gui_rounds"

OPEN_HUODONG_HOTKEY = ("alt", "c")

ZHUAGUI_HUODONG_TEMPLATES = (
    "201ZhuaGui/jm_zg2.png",
    "201ZhuaGui/jm_zg.png",
)
ZHUAGUI_TASK_TEMPLATE = "201ZhuaGui/jm_zgrw.png"
NEXT_ROUND_TEMPLATE = "201ZhuaGui/jm_jxzg.png"
BATTLE_CANCEL_TEMPLATE = "201ZhuaGui/quxiao.png"

ZHUAGUI_TASK_SEARCH_RECT = (562, 126, 770, 448)
NEXT_ROUND_SEARCH_RECT = (398, 240, 548, 369)

HUODONG_GOTO_OFFSET_X = 155
TASK_CLICK_RANDOM_OFFSET = 5
MAP_NAV_RANDOM_OFFSET = 0
NEXT_ROUND_CONFIRM_CLICK = (473, 337)
START_ZHUAGUI_CLICK = (698, 160)

OVER_20_NAV_STEPS = [
    ((36, 38), "打开地图", 2.0),
    ((383, 335), "切到长安城", 2.0),
    ((106, 27), "点击小地图", 2.0),
    ((228, 319), "点击钟馗", 8.0),
]

MATCH_THRESHOLD = 0.85
DEFAULT_WAIT_SEC = 3.0
OPEN_HUODONG_WAIT_SEC = 2.0
HUODONG_TELEPORT_WAIT_SEC = 20.0
START_ZHUAGUI_WAIT_SEC = 10.0
BATTLE_POLL_WAIT_SEC = 30.0
NEXT_ROUND_SEARCH_WAIT_SEC = 2.0
NEXT_ROUND_TELEPORT_WAIT_SEC = 10.0
NEXT_ROUND_MISS_LIMIT = 6


class TaskAbort(Exception):
    """用于按业务条件中止当前任务流程。"""


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
                f"找到{label}模板 {template} score={score:.4f}，中心=({x},{y})"
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
        bot.log(f"在区域 {search_rect} 未找到{label}模板: {names}，终止抓鬼逻辑。")
        raise TaskAbort(f"missing required template: {label}")
    return match, template


def _run_over_20_navigation(bot, check_stop, wait_or_stop, stop_event):
    bot.log("已勾选超20抓鬼，先走长安城 -> 钟馗的地图导航。")
    for (x, y), label, wait_sec in OVER_20_NAV_STEPS:
        check_stop(stop_event)
        bot.log(f"{label}：点击 ({x},{y})。")
        bot.click(x, y, MAP_NAV_RANDOM_OFFSET)
        wait_or_stop(bot, stop_event, wait_sec)


def _open_huodong_and_trigger_zhuagui(bot, check_stop, wait_or_stop, stop_event):
    bot.log("准备输入 Alt+C 打开活动界面。")
    bot.hotkey(*OPEN_HUODONG_HOTKEY)
    wait_or_stop(bot, stop_event, OPEN_HUODONG_WAIT_SEC)

    zhuagui_match, template = _find_required_match(
        bot,
        check_stop,
        stop_event,
        ZHUAGUI_HUODONG_TEMPLATES,
        HUODONG_SEARCH_RECT,
        label="抓鬼活动入口",
    )
    zhuagui_x, zhuagui_y, _score = zhuagui_match
    target_x = zhuagui_x + HUODONG_GOTO_OFFSET_X
    bot.log(
        f"基于 {template} 中心=({zhuagui_x},{zhuagui_y})，"
        f"右移 {HUODONG_GOTO_OFFSET_X}px 后点击 ({target_x},{zhuagui_y})。"
    )
    bot.click(target_x, zhuagui_y, 0)
    bot.log("等待 20 秒，避免角色在长安城时不触发传送。")
    wait_or_stop(bot, stop_event, HUODONG_TELEPORT_WAIT_SEC)


def _accept_zhuagui_task(bot, check_stop, stop_event):
    task_match, _template = _find_required_match(
        bot,
        check_stop,
        stop_event,
        (ZHUAGUI_TASK_TEMPLATE,),
        ZHUAGUI_TASK_SEARCH_RECT,
        label="抓鬼任务按钮",
    )
    task_x, task_y, task_score = task_match
    bot.log(
        f"找到抓鬼任务按钮 score={task_score:.4f}，点击中心=({task_x},{task_y})。"
    )
    bot.click(task_x, task_y, TASK_CLICK_RANDOM_OFFSET)


def _find_battle_cancel(bot, check_stop, stop_event):
    check_stop(stop_event)
    # 调试：保存截图，确认截到的内容是否正确
    try:
        import cv2
        from script_action import _capture_window_bgr
        frame = _capture_window_bgr(bot.hwnd)
        if frame is not None:
            cv2.imwrite("debug_cancel_frame.png", frame)
            bot.log("已保存截图到 debug_cancel_frame.png")
        else:
            bot.log("调试截图失败：frame 为 None")
    except Exception as e:
        bot.log(f"调试截图异常: {e}")
    return bot.find_image(
        BATTLE_CANCEL_TEMPLATE,
        threshold=MATCH_THRESHOLD,
        search_rect=CANCEL_BUTTON_RECT,
        log_miss=True,
    )



def _wait_for_next_round(bot, check_stop, wait_or_stop, stop_event) -> bool:
    miss_count = 0

    while True:
        cancel_match = _find_battle_cancel(bot, check_stop, stop_event)
        if cancel_match:
            bot.log("检测到战斗中的取消按钮，等待 30 秒后继续轮询。")
            miss_count = 0
            wait_or_stop(bot, stop_event, BATTLE_POLL_WAIT_SEC)
            continue

        wait_or_stop(bot, stop_event, NEXT_ROUND_SEARCH_WAIT_SEC)
        next_round_match = bot.find_image(
            NEXT_ROUND_TEMPLATE,
            threshold=MATCH_THRESHOLD,
            search_rect=NEXT_ROUND_SEARCH_RECT,
            log_miss=False,
        )
        if next_round_match:
            bot.log("识别到继续抓鬼提示，点击开始下一轮。")
            bot.click(
                NEXT_ROUND_CONFIRM_CLICK[0],
                NEXT_ROUND_CONFIRM_CLICK[1],
                0,
            )
            bot.log("开始下一轮..")
            wait_or_stop(bot, stop_event, NEXT_ROUND_TELEPORT_WAIT_SEC)
            return True

        cancel_match = _find_battle_cancel(bot, check_stop, stop_event)
        if cancel_match:
            bot.log("未找到 jm_jxzg.png，但重新检测到战斗中的取消按钮，等待 30 秒后继续轮询。")
            miss_count = 0
            wait_or_stop(bot, stop_event, BATTLE_POLL_WAIT_SEC)
            continue

        miss_count += 1
        bot.log(f"未找到 jm_jxzg.png，且未检测到战斗中的取消按钮，第 {miss_count} 次。")
        if miss_count > NEXT_ROUND_MISS_LIMIT:
            bot.log("连续超过 6 次未找到 jm_jxzg，且未检测到战斗中的取消按钮，按规则判定超过 3 分钟不在战斗，退出抓鬼逻辑。")
            return False


def run(bot, check_stop, wait_or_stop, stop_event, *, task_options=None, task_flags=None):
    """抓鬼主流程。"""
    del task_flags
    over_20_enabled = bool(task_options and task_options.get(OVER_20_OPTION_KEY))
    max_rounds = int(task_options.get(ROUNDS_OPTION_KEY, 0)) if task_options else 0
    if max_rounds > 0:
        bot.log(f"开始执行抓鬼逻辑，目标轮数: {max_rounds}")
    else:
        bot.log("开始执行抓鬼逻辑，不限轮数")

    round_count = 0

    try:
        if over_20_enabled:
            _run_over_20_navigation(bot, check_stop, wait_or_stop, stop_event)
        else:
            _open_huodong_and_trigger_zhuagui(bot, check_stop, wait_or_stop, stop_event)

        while True:
            check_stop(stop_event)
            _accept_zhuagui_task(bot, check_stop, stop_event)
            wait_or_stop(bot, stop_event, DEFAULT_WAIT_SEC)

            # 占位逻辑：人数不足时的特殊处理，后续有模板和坐标后再放开。
            # three_member_match = bot.find_image(
            #     "5抓鬼任务/xxx.png",
            #     threshold=MATCH_THRESHOLD,
            #     search_rect=(0, 0, 0, 0),
            #     log_miss=False,
            # )
            # if three_member_match:
            #     bot.click(0, 0, TASK_CLICK_RANDOM_OFFSET)
            #     wait_or_stop(bot, stop_event, DEFAULT_WAIT_SEC)
            #     bot.log("三人直接开启")

            bot.log(
                f"点击坐标 ({START_ZHUAGUI_CLICK[0]},{START_ZHUAGUI_CLICK[1]})，"
                "等待 10 秒后进入战斗轮询。"
            )
            bot.double_click(START_ZHUAGUI_CLICK[0], START_ZHUAGUI_CLICK[1], 0)

            wait_or_stop(bot, stop_event, START_ZHUAGUI_WAIT_SEC)

            if not _wait_for_next_round(bot, check_stop, wait_or_stop, stop_event):
                return

            round_count += 1
            bot.log(f"已完成第 {round_count} 轮抓鬼。")
            if max_rounds > 0 and round_count >= max_rounds:
                bot.log(f"已达到目标轮数 {max_rounds}，停止抓鬼。")
                return
    except TaskAbort:
        return
