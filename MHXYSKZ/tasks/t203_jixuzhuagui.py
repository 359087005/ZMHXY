"""
继续抓鬼任务脚本。

与 t201_zhuagui 的区别：不接任务、不开场，直接从当前状态接管。
角色已经在抓鬼战斗中时，直接判定为抓鬼战斗中，等本轮打完再走正常循环。

模板与坐标全部复用 tasks/t201_zhuagui.py。
"""

from __future__ import annotations

from tasks.t201_zhuagui import ROUNDS_OPTION_KEY, run_continue

__all__ = ["ROUNDS_OPTION_KEY", "run"]


def run(bot, check_stop, wait_or_stop, stop_event, *, task_options=None, task_flags=None):
    """入口：转发到 t201_zhuagui.run_continue。"""
    return run_continue(
        bot,
        check_stop,
        wait_or_stop,
        stop_event,
        task_options=task_options,
        task_flags=task_flags,
    )
