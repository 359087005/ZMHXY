"""
游戏内逻辑脚本。

主界面点击「执行脚本」后，会热重载并调用本文件的 run(hwnd, log)。
本文件负责按勾选功能块分发任务；支持直接执行的任务会跳过任务界面调度。
"""

from __future__ import annotations

import importlib
import inspect
import time
from typing import Callable

Logger = Callable[[str], None]
TaskFlags = dict[str, bool]
TaskOptions = dict[str, bool]

TASK_LABELS = {
    "shi_men": "师门任务",
    "wa_bao_tu": "挖宝图",
    "da_bao_tu": "打宝图",
    "mi_jing_xiang_yao": "秘境降妖",
    "zhua_gui": "抓鬼任务",
    "ji_xu_zhua_gui": "继续抓鬼",
    "fu_ben": "副本",
    "yun_biao": "运镖",
    "san_jie_qi_yuan": "三界奇缘",
    "ke_ju_xiang_shi": "科举乡试",
    "bang_pai_ren_wu": "帮派任务",
}

OPTION_LABELS = {
    "zhua_gui_over_20": "超20抓鬼",
}

DIRECT_RUN_TASK_MODULES = {
    "wa_bao_tu": "tasks.t199_wabaotu",
    "mi_jing_xiang_yao": "tasks.t107_mijingxiangyao",
    "zhua_gui": "tasks.t201_zhuagui",
    "ji_xu_zhua_gui": "tasks.t203_jixuzhuagui",
    "fu_ben": "tasks.t202_fuben",
}


class ScriptStopped(Exception):
    pass


# 创建绑定当前窗口句柄的自动化对象，并热重载底层动作库。
def _make_bot(hwnd: int, log: Logger):
    import script_action
    importlib.reload(script_action)
    return script_action.WindowAutomation(hwnd, log)


# 检查外部是否请求终止脚本，若已请求则抛出中止异常。
def _check_stop(stop_event):
    if stop_event is not None and stop_event.is_set():
        raise ScriptStopped()


# 统一处理等待过程，并在等待前后继续响应终止请求。
def _wait_or_stop(bot, stop_event, seconds: float):
    seconds = max(seconds, 0)
    _check_stop(stop_event)
    if seconds <= 0:
        return
    bot.log(f"等待 {seconds:.2f}s")
    if stop_event is None:
        time.sleep(seconds)
        return
    if stop_event.wait(seconds):
        raise ScriptStopped()


# 按任务模块实际支持的参数，转发公共回调、勾选项和附加选项。
def _run_task_module(
    module,
    bot,
    stop_event,
    *,
    task_flags: TaskFlags | None = None,
    task_options: TaskOptions | None = None,
):
    kwargs = {}
    try:
        params = inspect.signature(module.run).parameters
    except (TypeError, ValueError):
        params = {}

    if "task_flags" in params:
        kwargs["task_flags"] = task_flags
    if "task_options" in params:
        kwargs["task_options"] = task_options

    module.run(bot, _check_stop, _wait_or_stop, stop_event, **kwargs)


# 作为 GUI 的总入口，负责诊断、准备窗口并分发到具体任务模块。
def run(
    hwnd: int,
    log: Logger,
    *,
    stop_event=None,
    task_flags: TaskFlags | None = None,
    task_options: TaskOptions | None = None,
):
    bot = _make_bot(hwnd, log)
    selected_flags = task_flags or {}
    selected_options = task_options or {}
    selected_ids = [
        task_id
        for task_id, enabled in selected_flags.items()
        if enabled and task_id in TASK_LABELS
    ]
    if not selected_ids:
        bot.log("未勾选任何功能块，本次不执行。")
        return

    try:
        _check_stop(stop_event)
        bot.diagnose()
        bot.prepare()
        _check_stop(stop_event)

        selected_labels = [TASK_LABELS[tid] for tid in selected_ids]
        bot.log(f"本次准备执行功能块: {' / '.join(selected_labels)}")
        option_labels = [
            label
            for key, label in OPTION_LABELS.items()
            if selected_options.get(key)
        ]
        if option_labels:
            bot.log(f"本次附加选项: {' / '.join(option_labels)}")

        if len(selected_ids) == 1:
            direct_task_id = selected_ids[0]
            direct_module_name = DIRECT_RUN_TASK_MODULES.get(direct_task_id)
            if direct_module_name:
                bot.log(
                    f"{TASK_LABELS[direct_task_id]} 单独执行，"
                    "直接进入任务逻辑，跳过任务界面调度。"
                )
                direct_module = importlib.import_module(direct_module_name)
                direct_module = importlib.reload(direct_module)
                _run_task_module(
                    direct_module,
                    bot,
                    stop_event,
                    task_flags=selected_flags,
                    task_options=selected_options,
                )
                bot.log("本次脚本执行完成。")
                return

        # 其它勾选组合仍交给任务界面调度
        import tasks.t000_renwujiemian as renwujiemian
        importlib.reload(renwujiemian)
        renwujiemian.run(
            bot, _check_stop, _wait_or_stop, stop_event,
            task_flags=selected_flags,
            task_options=selected_options,
        )

        bot.log("本次脚本执行完成。")
    except ScriptStopped:
        bot.log("脚本已终止。")
