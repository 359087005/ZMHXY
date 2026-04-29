---
name: window-automation-maintainer
description: 维护这个 Windows 窗口后台预览与自动化项目。处理 window_capture.py、script_action.py、README.md、模板识别、Win32 窗口管理、后台点击、DWM 预览、采样预览等需求时使用。
---

# Window Automation Maintainer

## Quick Start

1. 先读 `README.md`，确认当前推荐工作流、用户可见行为和最近变更。
2. 识别改动归属：
   - GUI / 预览 / 窗口状态管理 -> `window_capture.py`
   - 自动化动作 / 模板识别 / 脚本 API -> `script_action.py`
   - 任务模块 -> `task\`
   - 模板素材说明 -> `templates/README.txt`
   - 用户文档和变更摘要 -> `README.md`
3. 默认做最小可行修改，避免把 GUI、自动化 API、文档耦在一起大改。

## Project Defaults

- 这是 Windows-first 工具，优先保持 `tkinter` + `ctypes` + Win32 API 方案。
- `window_capture.py` 更像编排层；可复用行为优先沉到 `script_action.py`。
- 与窗口移动、尺寸、样式、任务栏图标相关的功能，必须考虑恢复路径。
- 与输入注入、抓帧、窗口管理相关的功能，日志里尽量保留 `hwnd`、`pid`、返回值和错误文本。
- 若用户没有明确要求，不要同时保留多套重复输入策略。
- 用户习惯要求：功能改动后同步更新 `README.md` 的说明和变更日志,同一天的变更更新在一个版本内即可,不需要每次变更都加版本号。

## Change Workflow

### 做 GUI / 预览改动时

- 在 `window_capture.py` 增加控件、状态变量和回调。
- 如改动影响预览行为，检查 `DWM` 预览、采样预览、坐标映射、恢复流程是否仍一致。
- 如改动影响窗口状态，检查关闭程序前的自动恢复是否仍有效。

### 做自动化 / 识别改动时

- 优先在 `script_action.py` 的 `WindowAutomation` 上新增方法。
- 方法命名保持动作导向，例如 `click_image()`、`drag()`、`press_key()`。
- `run()` 或 GUI 按钮只做调用，不堆复杂业务逻辑。

### 做文档改动时

- 用户能看到的按钮、参数、推荐流程变化，要更新 `README.md`。
- 追加一条简短变更日志，说明这次新增/修正了什么。

## Verification

- 对受影响的 Python 文件运行 `python -m py_compile`
- 读取修改文件的 lints
- 若改动涉及游戏窗口、UIPI、DWM、`PrintWindow` 等运行时差异，在最终说明里明确残余风险

## Additional Resources

- 详细项目地图与约束见 [reference.md](reference.md)

## 代码中涉及到要用wait_or_stop做等待的状态时,默认是等待2秒