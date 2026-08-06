"""
副本任务脚本。

本脚本负责自动执行当天的副本任务，支持 5 个副本：
蹈海去、金蝉心、琉璃碎、二重影、绿烟如梦。

游戏每天会从上述 5 个副本里随机提供 2 个作为当天可做副本，
脚本会在活动界面（Alt+C）中扫描副本入口图标并按命中顺序执行。

模板目录：templates/202FuBen/

预计依赖模板：
- 202FuBen/jm_daohaiqu.png         —— 活动界面「蹈海去」入口图标
- 202FuBen/jm_jinchanxin.png       —— 活动界面「金蝉心」入口图标
- 202FuBen/jm_liulisui.png         —— 活动界面「琉璃碎」入口图标
- 202FuBen/jm_erchongying.png      —— 活动界面「二重影」入口图标
- 202FuBen/jm_lvyanrumeng.png      —— 活动界面「绿烟如梦」入口图标
- 202FuBen/jm_fbxz_daohaiqu.png    —— 副本选择界面「蹈海去」名称
- 202FuBen/jm_fbxz_jinchanxin.png  —— 副本选择界面「金蝉心」名称
- 202FuBen/jm_fbxz_liulisui.png    —— 副本选择界面「琉璃碎」名称
- 202FuBen/jm_fbxz_erchongying.png —— 副本选择界面「二重影」名称
- 202FuBen/jm_fbxz_lvyanrumeng.png —— 副本选择界面「绿烟如梦」名称
- 202FuBen/jm_xuanze_fuben.png     —— NPC 对话框「选择副本」按钮

复用模板：
- 201ZhuaGui/quxiao.png            —— 战斗中的取消按钮，用于判断是否仍在战斗

本文件里所有坐标、搜索矩形、等待时长、偏移量均为占位值，
实测后由用户提供真实数值再行替换。占位值统一以较醒目的形式给出，
便于在日志和代码中一眼识别（例如点击点 (999, 999)、偏移 999、
搜索矩形默认覆盖客户区 (0, 0, 800, 600) 等）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from tasks.shared_rects import CANCEL_BUTTON_RECT, HUODONG_SEARCH_RECT

Logger = Callable[[str], None]
MatchResult = tuple[int, int, float]

MATCH_THRESHOLD = 0.85

# ─── 占位值 ──────────────────────────────────────────────────────────────────
_PLACEHOLDER_POINT = (999, 999)
_PLACEHOLDER_RECT = (0, 0, 800, 600)
_PLACEHOLDER_OFFSET = 999

# ─── 活动界面 ─────────────────────────────────────────────────────────────────
OPEN_HUODONG_HOTKEY = ("alt", "c")
OPEN_HUODONG_WAIT_SEC = 2.0
NAVIGATION_WAIT_SEC = 8.0
FUBEN_ENTRY_CLICK_OFFSET = 5

FUBEN_NAMES = (
    "蹈海去",
    "金蝉心",
    "琉璃碎",
    "二重影",
    "绿烟如梦",
)

FUBEN_ENTRY_TEMPLATES: dict[str, str] = {
    "蹈海去": "202FuBen/jm_daohaiqu.png",
    "金蝉心": "202FuBen/jm_jinchanxin.png",
    "琉璃碎": "202FuBen/jm_liulisui.png",
    "二重影": "202FuBen/jm_erchongying.png",
    "绿烟如梦": "202FuBen/jm_lvyanrumeng.png",
}

# ─── NPC 对话框 ───────────────────────────────────────────────────────────────
NPC_DIALOG_SELECT_TEMPLATE = "202FuBen/jm_xuanze_fuben.png"
NPC_DIALOG_SEARCH_RECT = _PLACEHOLDER_RECT  # 占位：覆盖全客户区
NPC_DIALOG_WAIT_SEC = 1.5
FUBEN_SELECT_PANEL_WAIT_SEC = 2.0

# ─── 副本选择界面 ────────────────────────────────────────────────────────────
FUBEN_SELECT_PANEL_TEMPLATES: dict[str, str] = {
    "蹈海去": "202FuBen/jm_fbxz_daohaiqu.png",
    "金蝉心": "202FuBen/jm_fbxz_jinchanxin.png",
    "琉璃碎": "202FuBen/jm_fbxz_liulisui.png",
    "二重影": "202FuBen/jm_fbxz_erchongying.png",
    "绿烟如梦": "202FuBen/jm_fbxz_lvyanrumeng.png",
}
FUBEN_SELECT_PANEL_SEARCH_RECT = _PLACEHOLDER_RECT  # 占位
FUBEN_SELECT_ENTER_OFFSET_X = 0
FUBEN_SELECT_ENTER_OFFSET_Y = _PLACEHOLDER_OFFSET  # 占位：名称命中点向下偏移
FUBEN_LOADING_WAIT_SEC = 5.0

# ─── 右上角点击区域 ──────────────────────────────────────────────────────────
TOP_RIGHT_AREA_1_CLICK: tuple[int, int] = _PLACEHOLDER_POINT  # 跳过剧情
TOP_RIGHT_AREA_2_CLICK: tuple[int, int] = _PLACEHOLDER_POINT  # 战斗 / 领奖 / 结束
TOP_RIGHT_AREA_3_CLICK: tuple[int, int] = _PLACEHOLDER_POINT  # 预留，不使用

# ─── 3 波战斗通用循环 ────────────────────────────────────────────────────────
BATTLE_CANCEL_TEMPLATE = "201ZhuaGui/quxiao.png"
BATTLE_POLL_INTERVAL_SEC = 15.0
BATTLE_MISS_LIMIT = 8
TOTAL_BATTLE_WAVES = 3
BATTLE_CHECK_THRESHOLD = MATCH_THRESHOLD

# ─── 副本结束与场景回归 ──────────────────────────────────────────────────────
SAFE_CLICK_POINT: tuple[int, int] = (400, 350)  # 关奖励飘字的安全点
AWARD_DISMISS_WAIT_SEC = 1.5
SCENE_TRANSITION_WAIT_SEC = 5.0


class TaskAbort(Exception):
    """用于按业务条件中止当前副本流程。"""


@dataclass
class FubenContext:
    """传给副本分支函数的上下文。"""

    bot: object
    check_stop: Callable
    wait_or_stop: Callable
    stop_event: object
    fuben_name: str


# ─── 模板匹配辅助 ────────────────────────────────────────────────────────────

def _find_first_match(
    bot,
    check_stop,
    stop_event,
    templates: Iterable[str],
    search_rect: tuple[int, int, int, int],
    *,
    label: str,
    threshold: float = MATCH_THRESHOLD,
) -> tuple[MatchResult | None, str | None]:
    """按顺序尝试 templates，返回第一个命中的 (match, template)。"""
    for template in templates:
        check_stop(stop_event)
        match = bot.find_image(
            template,
            threshold=threshold,
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
    threshold: float = MATCH_THRESHOLD,
) -> tuple[MatchResult, str]:
    """未命中则抛 TaskAbort 的模板匹配。"""
    match, template = _find_first_match(
        bot,
        check_stop,
        stop_event,
        templates,
        search_rect,
        label=label,
        threshold=threshold,
    )
    if not match or not template:
        names = " / ".join(templates)
        bot.log(f"在区域 {search_rect} 未找到{label}模板: {names}，终止副本流程。")
        raise TaskAbort(f"missing required template: {label}")
    return match, template


# ─── 活动界面扫描与副本入口点击 ──────────────────────────────────────────────

def _open_huodong(bot, check_stop, wait_or_stop, stop_event) -> None:
    """按 Alt+C 打开活动界面，并等待界面加载完成。"""
    check_stop(stop_event)
    bot.log("准备输入 Alt+C 打开活动界面。")
    bot.hotkey(*OPEN_HUODONG_HOTKEY)
    wait_or_stop(bot, stop_event, OPEN_HUODONG_WAIT_SEC)


def _scan_current_view(
    bot,
    check_stop,
    stop_event,
    *,
    skip_set: set[str],
) -> tuple[str, str, MatchResult] | None:
    """在当前活动界面视图中按 FUBEN_NAMES 顺序扫描未完成的副本入口。"""
    attempted_templates: list[str] = []
    for name in FUBEN_NAMES:
        if name in skip_set:
            continue
        template = FUBEN_ENTRY_TEMPLATES[name]
        attempted_templates.append(template)
        check_stop(stop_event)
        match = bot.find_image(
            template,
            threshold=MATCH_THRESHOLD,
            search_rect=HUODONG_SEARCH_RECT,
            log_miss=False,
        )
        if match:
            x, y, score = match
            bot.log(
                f"命中副本入口: {name} template={template} score={score:.4f} "
                f"center=({x},{y})"
            )
            return name, template, match

    bot.log(
        f"当前活动界面视图未命中任何目标副本入口。 "
        f"search_rect={HUODONG_SEARCH_RECT} "
        f"尝试过模板={attempted_templates} "
        f"已跳过={sorted(skip_set)}"
    )
    return None


def _click_fuben_entry(
    bot,
    check_stop,
    wait_or_stop,
    stop_event,
    name: str,
    template: str,
    match: MatchResult,
) -> None:
    """点击识别到的副本入口，并等待角色自动寻路到 NPC。"""
    check_stop(stop_event)
    x, y, score = match
    bot.log(
        f"点击副本入口: {name} template={template} score={score:.4f} "
        f"center=({x},{y}) offset={FUBEN_ENTRY_CLICK_OFFSET}"
    )
    bot.click(x, y, FUBEN_ENTRY_CLICK_OFFSET)
    bot.log(f"等待角色寻路到 NPC，约 {NAVIGATION_WAIT_SEC:.1f} 秒。")
    wait_or_stop(bot, stop_event, NAVIGATION_WAIT_SEC)


# ─── NPC 对话框与副本选择界面 ─────────────────────────────────────────────────

def _click_dialog_select_fuben(bot, check_stop, wait_or_stop, stop_event) -> None:
    """在 NPC 对话框中匹配「选择副本」按钮并点击。"""
    check_stop(stop_event)
    wait_or_stop(bot, stop_event, NPC_DIALOG_WAIT_SEC)
    match, template = _find_required_match(
        bot,
        check_stop,
        stop_event,
        (NPC_DIALOG_SELECT_TEMPLATE,),
        NPC_DIALOG_SEARCH_RECT,
        label="NPC 对话框-选择副本",
    )
    x, y, score = match
    bot.log(
        f"点击 NPC 对话框-选择副本: template={template} score={score:.4f} "
        f"center=({x},{y})"
    )
    bot.click(x, y, 0)
    wait_or_stop(bot, stop_event, FUBEN_SELECT_PANEL_WAIT_SEC)


def _pick_fuben_in_select_panel(
    bot,
    check_stop,
    wait_or_stop,
    stop_event,
    fuben_name: str,
) -> None:
    """在副本选择界面里匹配目标副本名，基于命中点向下偏移点击「进入」按钮。"""
    check_stop(stop_event)
    template = FUBEN_SELECT_PANEL_TEMPLATES[fuben_name]
    match, _ = _find_required_match(
        bot,
        check_stop,
        stop_event,
        (template,),
        FUBEN_SELECT_PANEL_SEARCH_RECT,
        label=f"副本选择界面-{fuben_name}",
    )
    cx, cy, score = match
    enter_x = cx + FUBEN_SELECT_ENTER_OFFSET_X
    enter_y = cy + FUBEN_SELECT_ENTER_OFFSET_Y
    bot.log(
        f"选择副本: {fuben_name} template={template} score={score:.4f} "
        f"name_center=({cx},{cy}) enter_click=({enter_x},{enter_y}) "
        f"offset=({FUBEN_SELECT_ENTER_OFFSET_X},{FUBEN_SELECT_ENTER_OFFSET_Y})"
    )
    bot.click(enter_x, enter_y, 0)
    bot.log(f"等待副本场景加载，约 {FUBEN_LOADING_WAIT_SEC:.1f} 秒。")
    wait_or_stop(bot, stop_event, FUBEN_LOADING_WAIT_SEC)


# ─── 右上角区域点击原语 ───────────────────────────────────────────────────────

def _click_skip_dialog(bot) -> None:
    """点击区域1：跳过剧情。"""
    x, y = TOP_RIGHT_AREA_1_CLICK
    bot.log(f"区域1-跳过剧情: click=({x},{y})")
    bot.click(x, y, 0)


def _click_area2(bot, *, reason: str) -> None:
    """点击区域2，reason 描述当前场景（进入战斗 / 领取副本奖励 / 结束副本）。"""
    x, y = TOP_RIGHT_AREA_2_CLICK
    bot.log(f"区域2-{reason}: click=({x},{y})")
    bot.click(x, y, 0)


# ─── 3 波战斗通用循环 ────────────────────────────────────────────────────────

def _find_battle_cancel(bot, check_stop, stop_event):
    check_stop(stop_event)
    return bot.find_image(
        BATTLE_CANCEL_TEMPLATE,
        threshold=BATTLE_CHECK_THRESHOLD,
        search_rect=CANCEL_BUTTON_RECT,
        log_miss=False,
    )


def _wait_wave_finish(
    bot,
    check_stop,
    wait_or_stop,
    stop_event,
    *,
    fuben_name: str,
    wave_index: int,
) -> bool:
    """等待当前波次战斗结束；命中取消按钮轮询，未命中即视为本波结束。"""
    miss_count = 0
    while True:
        match = _find_battle_cancel(bot, check_stop, stop_event)
        if match:
            bot.log(
                f"副本[{fuben_name}] 第 {wave_index} 波 战斗中："
                f"检测到取消按钮，{BATTLE_POLL_INTERVAL_SEC:.0f}s 后继续轮询。"
            )
            miss_count = 0
            wait_or_stop(bot, stop_event, BATTLE_POLL_INTERVAL_SEC)
            continue

        miss_count += 1
        bot.log(
            f"副本[{fuben_name}] 第 {wave_index} 波 未检测到取消按钮，"
            f"判定本波结束。"
        )
        return True


# ─── 副本结束与场景回归 ──────────────────────────────────────────────────────

def _finish_and_exit_fuben(
    bot,
    check_stop,
    wait_or_stop,
    stop_event,
    *,
    fuben_name: str,
) -> None:
    """3 波战斗完成后，领奖励 → 关飘字 → 结束副本。"""
    check_stop(stop_event)
    bot.log(f"副本[{fuben_name}] 开始结束流程：领取奖励。")
    _click_area2(bot, reason="领取副本奖励")
    wait_or_stop(bot, stop_event, AWARD_DISMISS_WAIT_SEC)

    check_stop(stop_event)
    sx, sy = SAFE_CLICK_POINT
    bot.log(f"副本[{fuben_name}] 安全点-关奖励飘字: click=({sx},{sy})")
    bot.click(sx, sy, 0)
    wait_or_stop(bot, stop_event, AWARD_DISMISS_WAIT_SEC)

    check_stop(stop_event)
    bot.log(f"副本[{fuben_name}] 结束本次副本。")
    _click_area2(bot, reason="结束副本")
    wait_or_stop(bot, stop_event, SCENE_TRANSITION_WAIT_SEC)


# ─── 5 个副本分支 ─────────────────────────────────────────────────────────────

def _run_fuben_daohaiqu(ctx: FubenContext) -> None:
    """蹈海去副本完整编排。"""
    bot = ctx.bot
    check_stop = ctx.check_stop
    wait_or_stop = ctx.wait_or_stop
    stop_event = ctx.stop_event

    bot.log("副本分支[蹈海去] 开始。")

    _click_dialog_select_fuben(bot, check_stop, wait_or_stop, stop_event)
    _pick_fuben_in_select_panel(
        bot, check_stop, wait_or_stop, stop_event, fuben_name="蹈海去"
    )

    for wave_index in range(1, TOTAL_BATTLE_WAVES + 1):
        check_stop(stop_event)
        bot.log(f"副本[蹈海去] 第 {wave_index} 波 开始。")
        _click_skip_dialog(bot)
        wait_or_stop(bot, stop_event, 0.5)
        _click_area2(bot, reason="进入战斗")
        wait_or_stop(bot, stop_event, 1.0)
        ok = _wait_wave_finish(
            bot,
            check_stop,
            wait_or_stop,
            stop_event,
            fuben_name="蹈海去",
            wave_index=wave_index,
        )
        if not ok:
            raise TaskAbort(f"蹈海去 第 {wave_index} 波 轮询异常")

    _finish_and_exit_fuben(
        bot, check_stop, wait_or_stop, stop_event, fuben_name="蹈海去"
    )
    bot.log("副本分支[蹈海去] 完成。")


def _run_fuben_placeholder(ctx: FubenContext) -> None:
    """占位分支：记录日志并安全返回，避免误用其它副本的流程。"""
    ctx.bot.log(
        f"副本分支[{ctx.fuben_name}] 尚未实现具体流程，安全返回；"
        "请在后续会话中补全该副本的战前/战后步骤。"
    )


def _run_fuben_jinchanxin(ctx: FubenContext) -> None:
    _run_fuben_placeholder(ctx)


def _run_fuben_liulisui(ctx: FubenContext) -> None:
    _run_fuben_placeholder(ctx)


def _run_fuben_erchongying(ctx: FubenContext) -> None:
    _run_fuben_placeholder(ctx)


def _run_fuben_lvyanrumeng(ctx: FubenContext) -> None:
    _run_fuben_placeholder(ctx)


FUBEN_HANDLERS: dict[str, Callable[[FubenContext], None]] = {
    "蹈海去": _run_fuben_daohaiqu,
    "金蝉心": _run_fuben_jinchanxin,
    "琉璃碎": _run_fuben_liulisui,
    "二重影": _run_fuben_erchongying,
    "绿烟如梦": _run_fuben_lvyanrumeng,
}


# ─── 单副本主流程 + 扫描循环 ─────────────────────────────────────────────────

def _run_single_fuben(
    bot,
    check_stop,
    wait_or_stop,
    stop_event,
    *,
    name: str,
    template: str,
    match: MatchResult,
) -> None:
    """点击副本入口 → 调度对应副本分支。"""
    _click_fuben_entry(
        bot, check_stop, wait_or_stop, stop_event, name, template, match
    )
    handler = FUBEN_HANDLERS.get(name)
    if handler is None:
        bot.log(f"未登记的副本分支: {name}，跳过。")
        return
    ctx = FubenContext(
        bot=bot,
        check_stop=check_stop,
        wait_or_stop=wait_or_stop,
        stop_event=stop_event,
        fuben_name=name,
    )
    handler(ctx)


def run(
    bot,
    check_stop,
    wait_or_stop,
    stop_event,
    *,
    task_options=None,
    task_flags=None,
):
    """
    副本任务主入口。

    当天扫描循环：开活动界面 → 按 FUBEN_NAMES 扫 → 命中就跑对应分支
    → 完成后加入 done_set → 回来继续扫 → 扫不到就结束。
    """
    del task_options, task_flags

    bot.log("开始执行副本逻辑。")
    done_set: set[str] = set()

    try:
        _open_huodong(bot, check_stop, wait_or_stop, stop_event)

        while True:
            check_stop(stop_event)
            result = _scan_current_view(
                bot,
                check_stop,
                stop_event,
                skip_set=done_set,
            )
            if result is None:
                if done_set:
                    bot.log(
                        f"当天副本已全部完成。 已跑副本={sorted(done_set)}"
                    )
                else:
                    bot.log("当前没有可做副本，副本流程结束。")
                return

            name, template, match = result
            try:
                _run_single_fuben(
                    bot,
                    check_stop,
                    wait_or_stop,
                    stop_event,
                    name=name,
                    template=template,
                    match=match,
                )
            except TaskAbort as abort:
                bot.log(
                    f"副本[{name}] 执行中断: {abort}，跳过该副本继续扫下一个。"
                )
                done_set.add(name)
                _open_huodong(bot, check_stop, wait_or_stop, stop_event)
                continue

            done_set.add(name)
            bot.log(f"已完成副本: {name}。 done={sorted(done_set)}")

            _open_huodong(bot, check_stop, wait_or_stop, stop_event)
    except TaskAbort as abort:
        bot.log(f"副本流程整体中断: {abort}")
        return
