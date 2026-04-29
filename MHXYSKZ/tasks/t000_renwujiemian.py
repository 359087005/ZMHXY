"""
活动界面调度模块。

流程：
1. Alt+C 打开活动界面
2. 向下拖拽 4 次，将列表滚到最顶部
3. 在列表区域匹配目标任务图标（普通 + 推荐两张模板）
4. 当前页未找到则向上翻页，最多翻 2 次
5. 找到任务图标后，在图标区域内匹配"参加"按钮并点击
6. 调用对应任务子脚本
7. 下一个任务重复以上流程

模板图放在 templates/000RenWuJieMian/ 下。
"""

from __future__ import annotations

import importlib
from typing import Callable

Logger = Callable[[str], None]

# ─── 快捷键 & 坐标常量 ─────────────────────────────────────────────────────

OPEN_ACTIVITY_HOTKEY = ("alt", "c")
OPEN_ACTIVITY_WAIT_SEC = 1.5

# 滚到顶部：鼠标从上往下拖，内容往上滚
SCROLL_TOP_START = (465, 200)
SCROLL_TOP_END = (465, 400)
SCROLL_TOP_TIMES = 4
SCROLL_SETTLE_SEC = 0.5

# 翻页查找：鼠标从下往上拖，内容往下滚
SCROLL_DOWN_START = (465, 380)
SCROLL_DOWN_END = (465, 180)
MAX_PAGE_SCROLLS = 2

# 任务列表搜索区域
TASK_LIST_RECT = (180, 140, 750, 430)

# 参加按钮模板
CANJIA_TEMPLATE = "000RenWuJieMian/jm_canjia.png"

# 匹配参数
ICON_THRESHOLD = 0.80
CANJIA_THRESHOLD = 0.80
RANDOM_OFFSET = 10
AFTER_CANJIA_CLICK_WAIT_SEC = 1.5
# 参加按钮搜索区域在图标区域基础上的扩展像素
CANJIA_SEARCH_PADDING = 10

# ─── 任务映射表 ────────────────────────────────────────────────────────────
# task_id → (模板列表, 对应模块名)
# 每个任务有普通和推荐两张模板，匹配任一即可

TASK_ICON_MAP = {
    "da_bao_tu": (
        ["000RenWuJieMian/jm_bt.png", "000RenWuJieMian/jm_bt_tj.png"],
        "tasks.t102_dabaotu",
    ),
    "shi_men": (
        ["000RenWuJieMian/jm_sm.png", "000RenWuJieMian/jm_sm_tj.png"],
        "tasks.t101_shimen",
    ),
    "mi_jing_xiang_yao": (
        ["000RenWuJieMian/jm_mjxy.png", "000RenWuJieMian/jm_mjxy_tj.png"],
        "tasks.t107_mijingxiangyao",
    ),
    "yun_biao": (
        ["000RenWuJieMian/jm_yb.png", "000RenWuJieMian/jm_yb_tj.png"],
        "tasks.t103_yabiao",
    ),
    "san_jie_qi_yuan": (
        ["000RenWuJieMian/jm_sjqy.png", "000RenWuJieMian/jm_sjqy_tj.png"],
        "tasks.t104_sanjieqiyuan",
    ),
    "ke_ju_xiang_shi": (
        ["000RenWuJieMian/jm_kj.png", "000RenWuJieMian/jm_kj_tj.png"],
        "tasks.t105_kejuxiangshi",
    ),
}

TASK_LABELS = {
    "da_bao_tu": "打宝图",
    "shi_men": "师门任务",
    "mi_jing_xiang_yao": "秘境降妖",
    "yun_biao": "押镖",
    "san_jie_qi_yuan": "三界奇缘",
    "ke_ju_xiang_shi": "科举乡试",
}


# ─── 内部函数 ──────────────────────────────────────────────────────────────

def _open_activity_panel(bot, check_stop, wait_or_stop, stop_event):
    """Alt+C 打开活动界面。"""
    check_stop(stop_event)
    bot.log("按 Alt+C 打开活动界面。")
    bot.hotkey(*OPEN_ACTIVITY_HOTKEY)
    wait_or_stop(bot, stop_event, OPEN_ACTIVITY_WAIT_SEC)


def _scroll_to_top(bot, check_stop, wait_or_stop, stop_event):
    """向下拖拽多次，将活动列表滚到最顶部。"""
    for i in range(SCROLL_TOP_TIMES):
        check_stop(stop_event)
        bot.drag(
            SCROLL_TOP_START[0], SCROLL_TOP_START[1],
            SCROLL_TOP_END[0], SCROLL_TOP_END[1],
        )
        wait_or_stop(bot, stop_event, SCROLL_SETTLE_SEC)
    bot.log("已拖拽到列表顶部。")


def _find_task_icon(bot, check_stop, wait_or_stop, stop_event, templates, label):
    """
    在任务列表区域查找任务图标，支持翻页。
    返回 (x, y, score, left, top, width, height) 或 None。
    """
    for attempt in range(MAX_PAGE_SCROLLS + 1):
        check_stop(stop_event)
        for tmpl in templates:
            match = bot.find_image(
                tmpl,
                threshold=ICON_THRESHOLD,
                search_rect=TASK_LIST_RECT,
                log_miss=False,
            )
            if match:
                x, y, score = match
                bot.log(f"找到 {label} 模板 {tmpl} score={score:.4f} center=({x},{y})")
                return match

        if attempt >= MAX_PAGE_SCROLLS:
            return None

        bot.log(f"当前页未找到 {label}，第 {attempt + 1} 次翻页。")
        bot.drag(
            SCROLL_DOWN_START[0], SCROLL_DOWN_START[1],
            SCROLL_DOWN_END[0], SCROLL_DOWN_END[1],
        )
        wait_or_stop(bot, stop_event, SCROLL_SETTLE_SEC)

    return None


def _click_canjia_in_icon_area(bot, check_stop, stop_event, icon_match):
    """
    在匹配到的任务图标区域内，查找并点击"参加"按钮。
    icon_match 为 find_image 返回的 (center_x, center_y, score)。
    由于 find_image 只返回中心坐标，这里以中心为基准构造搜索区域。
    """
    check_stop(stop_event)
    cx, cy, _score = icon_match

    # 以图标中心为基准，向四周扩展构造搜索区域
    # 任务图标大约 250x120 像素，参加按钮在图标右侧
    half_w, half_h = 140, 70
    pad = CANJIA_SEARCH_PADDING
    search_rect = (
        cx - half_w - pad,
        cy - half_h - pad,
        cx + half_w + pad,
        cy + half_h + pad,
    )

    canjia_match = bot.find_image(
        CANJIA_TEMPLATE,
        threshold=CANJIA_THRESHOLD,
        search_rect=search_rect,
    )
    if not canjia_match:
        bot.log("在图标区域内未找到参加按钮。")
        return False

    cj_x, cj_y, cj_score = canjia_match
    bot.log(f"找到参加按钮 score={cj_score:.4f}，点击 ({cj_x},{cj_y})。")
    bot.click(cj_x, cj_y, RANDOM_OFFSET)
    return True


# ─── 主流程 ────────────────────────────────────────────────────────────────

def run(bot, check_stop, wait_or_stop, stop_event, *, task_flags=None):
    """
    活动界面调度主流程。

    task_flags: 从 game_logic.py 传入的勾选状态字典，
                只处理其中勾选的、且在 TASK_ICON_MAP 中的任务。
    """
    if not task_flags:
        bot.log("未传入任务勾选状态，跳过活动界面调度。")
        return

    pending_tasks = [
        task_id
        for task_id, enabled in task_flags.items()
        if enabled and task_id in TASK_ICON_MAP
    ]

    if not pending_tasks:
        bot.log("没有需要通过活动界面执行的任务。")
        return

    labels = [TASK_LABELS.get(tid, tid) for tid in pending_tasks]
    bot.log(f"活动界面调度，待执行: {' / '.join(labels)}")

    for task_id in pending_tasks:
        check_stop(stop_event)
        templates, module_name = TASK_ICON_MAP[task_id]
        label = TASK_LABELS.get(task_id, task_id)

        # 1. 打开活动界面
        _open_activity_panel(bot, check_stop, wait_or_stop, stop_event)

        # 2. 滚到列表顶部
        _scroll_to_top(bot, check_stop, wait_or_stop, stop_event)

        # 3. 查找任务图标（支持翻页）
        bot.log(f"在活动界面中查找: {label}")
        icon_match = _find_task_icon(
            bot, check_stop, wait_or_stop, stop_event, templates, label,
        )

        if not icon_match:
            bot.log(f"活动界面中未找到 {label}，跳过。")
            # 关闭活动界面
            bot.press_key("esc")
            wait_or_stop(bot, stop_event, 0.5)
            continue

        # 4. 在图标区域内匹配并点击"参加"
        if not _click_canjia_in_icon_area(bot, check_stop, stop_event, icon_match):
            bot.log(f"{label} 未能点击参加按钮，跳过。")
            bot.press_key("esc")
            wait_or_stop(bot, stop_event, 0.5)
            continue

        wait_or_stop(bot, stop_event, AFTER_CANJIA_CLICK_WAIT_SEC)

        # 5. 执行对应任务脚本
        bot.log(f"开始执行: {label}")
        mod = importlib.import_module(module_name)
        importlib.reload(mod)
        mod.run(bot, check_stop, wait_or_stop, stop_event)
        bot.log(f"{label} 执行完毕。")

    bot.log("活动界面调度全部完成。")
