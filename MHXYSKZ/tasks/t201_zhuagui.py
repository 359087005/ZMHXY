"""
抓鬼任务脚本。

模板图放在 templates/5抓鬼任务/ 下。

依赖模板：
- 201ZhuaGui/jm_zg2.png
- 201ZhuaGui/jm_zg.png
- 201ZhuaGui/jm_zgrw.png
- 201ZhuaGui/jm_jxzg_qd.png（继续抓鬼弹窗的「确定」按钮，静态无倒计时）

素材（不参与匹配，仅留档便于重新裁模板）：
- 201ZhuaGui/jm_jxzg_full.png  完整客户区截图（802x602，含 1px 边框）
- 201ZhuaGui/jm_jxzg_263.png / jm_jxzg_84.png  两种倒计时状态的弹窗

复用模板：
- 201ZhuaGui/quxiao.png
"""

from __future__ import annotations

import time
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
# 弹窗上倒计时在「取消(263)」那一侧，「确定」按钮是完全静态的，
# 所以只拿确定按钮当模板：实测倒计时 263/84 两种状态下分数都是 0.9999。
# 对照：把含倒计时的取消按钮当模板，同样两张图只有 0.78 / 0.93，会卡在阈值上下。
NEXT_ROUND_TEMPLATES = ("201ZhuaGui/jm_jxzg_qd.png",)
BATTLE_CANCEL_TEMPLATE = "201ZhuaGui/quxiao.png"

ZHUAGUI_TASK_SEARCH_RECT = (562, 126, 770, 448)
NEXT_ROUND_SEARCH_RECT = (398, 240, 548, 369)

HUODONG_GOTO_OFFSET_X = 155
TASK_CLICK_RANDOM_OFFSET = 5
MAP_NAV_RANDOM_OFFSET = 0
# 确定按钮中心，实测值。优先点匹配到的中心，这个坐标只在拿不到中心时兜底。
NEXT_ROUND_CONFIRM_CLICK = (474, 340)
START_ZHUAGUI_CLICK = (698, 160)

OVER_20_NAV_STEPS = [
    ((36, 38), "打开地图", 2.0),
    ((383, 335), "切到长安城", 2.0),
    ((106, 27), "点击小地图", 2.0),
    ((228, 319), "点击钟馗", 8.0),
]

MATCH_THRESHOLD = 0.85
# PW_RENDERFULLCONTENT 抓的是整个窗口，按客户区尺寸裁剪会整体偏移
# （实测 dx=+8 dy=+31，正好是边框和标题栏厚度），坐标系全错，因此不能用。
# PW_CLIENTONLY 的坐标系才和模板一致。
NEXT_ROUND_FULL_CONTENT = False
DEFAULT_WAIT_SEC = 3.0
OPEN_HUODONG_WAIT_SEC = 2.0
HUODONG_TELEPORT_WAIT_SEC = 20.0
# 任务指引没有模板可匹配（只是边框+变化的文字），位置固定，用固定坐标点。
# 固定点两次：第一次没生效时第二次会成功；第一次已生效时第二次被游戏判为无效，无副作用。
GUIDE_CLICK_TIMES = 2
GUIDE_CLICK_GAP_SEC = 3.0
BATTLE_POLL_WAIT_SEC = 30.0
NEXT_ROUND_SEARCH_WAIT_SEC = 2.0
NEXT_ROUND_TELEPORT_WAIT_SEC = 10.0
# 脱离战斗后允许的最长空转时间：超过这个时长仍没等到「继续抓鬼」，才判定异常退出。
NEXT_ROUND_IDLE_TIMEOUT_SEC = 180.0
# PrintWindow 偶发返回不含取消按钮的中间态帧，单帧判定会误判成「已脱离战斗」。
# 实测同一帧离线必命中 0.9997，所以这里连抓几帧，任一命中即视为仍在战斗。
BATTLE_CANCEL_RETRY = 3
BATTLE_CANCEL_RETRY_GAP_SEC = 0.25
# 空转期间只保留前几次的现场截图，避免 180 秒内刷出几十张图。
NEXT_ROUND_DEBUG_DUMP_LIMIT = 3


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


def _click_task_guide(bot, check_stop, wait_or_stop, stop_event):
    """点右侧任务指引开始抓鬼。

    指引只是边框+会变的文字，没有可用模板，但位置固定，所以按固定坐标点。
    固定点 GUIDE_CLICK_TIMES 次、间隔 GUIDE_CLICK_GAP_SEC，
    覆盖首次点击偶发无效的情况；重复点击不会有副作用。
    """
    for attempt in range(1, GUIDE_CLICK_TIMES + 1):
        check_stop(stop_event)
        bot.log(
            f"点击任务指引 ({START_ZHUAGUI_CLICK[0]},{START_ZHUAGUI_CLICK[1]})，"
            f"第 {attempt}/{GUIDE_CLICK_TIMES} 次。"
        )
        bot.double_click(START_ZHUAGUI_CLICK[0], START_ZHUAGUI_CLICK[1], 0)
        if attempt < GUIDE_CLICK_TIMES:
            wait_or_stop(bot, stop_event, GUIDE_CLICK_GAP_SEC)


def _find_battle_cancel(bot, check_stop, stop_event):
    """判断是否仍在战斗：连抓多帧，任一命中即算命中。

    单帧判定会被 PrintWindow 的偶发中间态帧带偏，导致战斗中被误判为已脱战。
    """
    for attempt in range(1, BATTLE_CANCEL_RETRY + 1):
        check_stop(stop_event)
        match = bot.find_image(
            BATTLE_CANCEL_TEMPLATE,
            threshold=MATCH_THRESHOLD,
            search_rect=CANCEL_BUTTON_RECT,
            log_miss=False,
        )
        if match:
            if attempt > 1:
                bot.log(f"取消按钮在第 {attempt} 帧命中（前 {attempt - 1} 帧抓帧未命中）。")
            return match
        if attempt < BATTLE_CANCEL_RETRY:
            time.sleep(BATTLE_CANCEL_RETRY_GAP_SEC)
    return None


def _save_png(path: str, image) -> None:
    """用 imencode+tofile 落盘：cv2.imwrite 遇到非 ASCII 路径会静默失败。"""
    import cv2
    import numpy as np

    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"imencode 失败: {path}")
    np.asarray(buf).tofile(path)


def _debug_dump_next_round_miss(bot, miss_count: int) -> None:
    """未识别到继续抓鬼时落盘现场信息。

    同时用两种 PrintWindow 方式各抓一帧并打印 md5：
    - md5 每次不变 -> 抓到的是 DWM 缓存旧帧
    - 两种方式 md5 不同 -> PW_CLIENTONLY 漏掉了弹窗所在的子窗口层
    """
    # 前几次都报，之后每 15 次采样一次：
    # 战斗中会连续 miss 很久，只看前 3 次可能全落在战斗刚开始的瞬间。
    if miss_count > NEXT_ROUND_DEBUG_DUMP_LIMIT and miss_count % 15 != 0:
        return
    try:
        import hashlib

        from script_action import (
            _capture_window_bgr,
            _crop_frame_to_search_rect,
            _load_template_image,
            _match_template,
            _prepare_match_frame,
        )

        frames: dict[str, object] = {}
        frame = _capture_window_bgr(bot.hwnd)
        if frame is None:
            bot.log("调试[jxzg]：抓帧失败（PrintWindow 返回空帧）。")
        else:
            frames["client"] = frame
            height, width = frame.shape[:2]
            digest = hashlib.md5(frame.tobytes()).hexdigest()[:12]
            bot.log(f"调试[jxzg]：抓帧 {width}x{height} md5={digest}")

        # 每个模板配一个它自己的搜索区，一起报：
        # 继续抓鬼弹窗 -> NEXT_ROUND_SEARCH_RECT
        # 战斗取消按钮 -> CANCEL_BUTTON_RECT（战斗中却检测不到它，说明这个区域可能不对）
        probes = [(name, NEXT_ROUND_SEARCH_RECT) for name in NEXT_ROUND_TEMPLATES]
        probes.append((BATTLE_CANCEL_TEMPLATE, CANCEL_BUTTON_RECT))

        for label, frame in frames.items():
            gray_full = _prepare_match_frame(frame, True)
            frame_h, frame_w = frame.shape[:2]

            for name, rect in probes:
                template, path = _load_template_image(name, True)
                t_h, t_w = template.shape[:2]
                full = _match_template(gray_full, template, -1.0)
                if full:
                    fx, fy = full[0], full[1]
                    inside = (
                        rect[0] <= fx <= rect[2] and rect[1] <= fy <= rect[3]
                    )
                    full_text = (
                        f"全图={full[2]:.4f}@({fx},{fy}) "
                        f"{'在' if inside else '不在'}搜索区{rect}内"
                    )
                else:
                    full_text = f"全图无法匹配（模板 {t_w}x{t_h} 大于画面 {frame_w}x{frame_h}?）"

                crop, _ox, _oy, normalized = _crop_frame_to_search_rect(frame, rect)
                if crop is None:
                    region_text = f" 搜索区{rect}无效/超出画面"
                else:
                    c_h, c_w = crop.shape[:2]
                    if c_w < t_w or c_h < t_h:
                        region_text = f" 搜索区实际{c_w}x{c_h} 比模板小，必然匹配不到"
                    else:
                        region = _match_template(_prepare_match_frame(crop, True), template, -1.0)
                        region_text = (
                            f" 搜索区{normalized}={region[2]:.4f}"
                            if region
                            else f" 搜索区{normalized}无法匹配"
                        )
                    _save_png(
                        f"debug_jxzg_{miss_count}_{label}_{path.stem}_region.png", crop
                    )

                bot.log(
                    f"调试[jxzg]：{label} {path.name}({t_w}x{t_h}) "
                    f"{full_text}{region_text} 阈值={MATCH_THRESHOLD}"
                )

            _save_png(f"debug_jxzg_{miss_count}_{label}_full.png", frame)

        if frames:
            bot.log(f"调试[jxzg]：已保存 debug_jxzg_{miss_count}_*.png")
    except Exception as exc:
        bot.log(f"调试[jxzg]：保存现场信息失败: {exc!r}")


def _wait_for_next_round(bot, check_stop, wait_or_stop, stop_event) -> bool:
    miss_count = 0
    idle_since = time.monotonic()

    while True:
        cancel_match = _find_battle_cancel(bot, check_stop, stop_event)
        if cancel_match:
            bot.log("检测到战斗中的取消按钮，等待 30 秒后继续轮询。")
            miss_count = 0
            idle_since = time.monotonic()
            wait_or_stop(bot, stop_event, BATTLE_POLL_WAIT_SEC)
            continue

        wait_or_stop(bot, stop_event, NEXT_ROUND_SEARCH_WAIT_SEC)
        next_round_match, _next_round_template = _find_first_match(
            bot,
            check_stop,
            stop_event,
            NEXT_ROUND_TEMPLATES,
            NEXT_ROUND_SEARCH_RECT,
            label="继续抓鬼提示",
        )
        if next_round_match:
            # 模板就是确定按钮本身，匹配中心即按钮中心，直接点它最准。
            click_x, click_y, score = next_round_match
            bot.log(
                f"识别到继续抓鬼提示 score={score:.4f}，"
                f"点击确定按钮中心=({click_x},{click_y})。"
            )
            bot.click(click_x, click_y, 0)
            bot.log("开始下一轮..")
            wait_or_stop(bot, stop_event, NEXT_ROUND_TELEPORT_WAIT_SEC)
            return True

        cancel_match = _find_battle_cancel(bot, check_stop, stop_event)
        if cancel_match:
            bot.log("未找到 jm_jxzg.png，但重新检测到战斗中的取消按钮，等待 30 秒后继续轮询。")
            miss_count = 0
            idle_since = time.monotonic()
            wait_or_stop(bot, stop_event, BATTLE_POLL_WAIT_SEC)
            continue

        miss_count += 1
        idle_sec = time.monotonic() - idle_since
        bot.log(
            f"未找到 jm_jxzg.png，且未检测到战斗中的取消按钮，"
            f"第 {miss_count} 次，已空转 {idle_sec:.0f}/{NEXT_ROUND_IDLE_TIMEOUT_SEC:.0f} 秒。"
        )
        _debug_dump_next_round_miss(bot, miss_count)
        if idle_sec >= NEXT_ROUND_IDLE_TIMEOUT_SEC:
            bot.log(
                f"已连续 {idle_sec:.0f} 秒既不在战斗、也没等到继续抓鬼提示，退出抓鬼逻辑。"
            )
            return False


def run_continue(bot, check_stop, wait_or_stop, stop_event, *, task_options=None, task_flags=None):
    """继续抓鬼：跳过接任务和开场，直接从当前状态接管。

    适用于角色已经在抓鬼战斗中、或已经站在钟馗旁边的情况。
    检测到战斗中就直接当作抓鬼战斗中处理，等这一轮打完再走正常循环。
    """
    del task_flags
    max_rounds = int(task_options.get(ROUNDS_OPTION_KEY, 0)) if task_options else 0
    if max_rounds > 0:
        bot.log(f"继续抓鬼：从当前状态接管，目标轮数 {max_rounds}")
    else:
        bot.log("继续抓鬼：从当前状态接管，不限轮数")

    round_count = 0

    try:
        check_stop(stop_event)
        if _find_battle_cancel(bot, check_stop, stop_event):
            bot.log("检测到战斗中的取消按钮，判定当前已在抓鬼战斗中，直接等待本轮结束。")
        else:
            bot.log("当前未检测到战斗，直接进入轮询等待继续抓鬼提示。")

        # 先把当前这一轮等完，再接正常循环
        if not _wait_for_next_round(bot, check_stop, wait_or_stop, stop_event):
            return
        round_count += 1
        bot.log(f"已完成第 {round_count} 轮抓鬼。")
        if max_rounds > 0 and round_count >= max_rounds:
            bot.log(f"已达到目标轮数 {max_rounds}，停止抓鬼。")
            return

        while True:
            check_stop(stop_event)
            _accept_zhuagui_task(bot, check_stop, stop_event)
            wait_or_stop(bot, stop_event, DEFAULT_WAIT_SEC)

            _click_task_guide(bot, check_stop, wait_or_stop, stop_event)

            if not _wait_for_next_round(bot, check_stop, wait_or_stop, stop_event):
                return

            round_count += 1
            bot.log(f"已完成第 {round_count} 轮抓鬼。")
            if max_rounds > 0 and round_count >= max_rounds:
                bot.log(f"已达到目标轮数 {max_rounds}，停止抓鬼。")
                return
    except TaskAbort:
        return


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

            _click_task_guide(bot, check_stop, wait_or_stop, stop_event)

            if not _wait_for_next_round(bot, check_stop, wait_or_stop, stop_event):
                return

            round_count += 1
            bot.log(f"已完成第 {round_count} 轮抓鬼。")
            if max_rounds > 0 and round_count >= max_rounds:
                bot.log(f"已达到目标轮数 {max_rounds}，停止抓鬼。")
                return
    except TaskAbort:
        return
