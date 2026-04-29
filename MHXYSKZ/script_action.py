"""
后台自动化动作库。

主界面的「执行脚本」当前会热重载 `game_logic.py`；
本文件主要提供可复用的动作方法给 `game_logic.py` 和 Debug 按钮调用。
所有坐标均为目标窗口客户区坐标（左上角为 0, 0）。

推荐写法：

def run(hwnd, log):
    bot = WindowAutomation(hwnd, log)
    bot.diagnose()
    bot.prepare()
    bot.click(517, 525)
    bot.wait(0.2)
    bot.right_click(640, 360, 3)
    bot.press_key("enter")
    bot.hotkey("ctrl", "a")
    bot.send_text("hello")
    bot.double_click(640, 360, 4)
    bot.drag(820, 610, 1040, 610, 3)
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import random
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
advapi32 = ctypes.windll.advapi32
shell32 = ctypes.windll.shell32
gdi32 = ctypes.windll.gdi32
dwmapi = ctypes.windll.dwmapi

try:
    import cv2
    import numpy as np
except Exception:
    cv2 = None
    np = None

_TEMPLATE_IMAGE_CACHE: dict[tuple[str, bool], tuple[int, int, object]] = {}
_TEMPLATE_IMAGE_CACHE_LOCK = threading.RLock()

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102

FORCE_CLEAR_UI_X = 407
FORCE_CLEAR_UI_Y = 267
FORCE_CLEAR_UI_REPEAT = 5
FORCE_CLEAR_UI_INTERVAL_SEC = 1.0

MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002

SW_SHOWNOACTIVATE = 4
SW_RESTORE = 9
SW_SHOW = 5

SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

PROCESS_QUERY_INFORMATION = 0x0400
TOKEN_QUERY = 0x0008
TokenElevation = 20
MAPVK_VK_TO_VSC = 0
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002
BI_RGB = 0
DIB_RGB_COLORS = 0
SRCCOPY = 0x00CC0020

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

KEEPALIVE_VISIBLE_WIDTH = 24
KEEPALIVE_VISIBLE_HEIGHT = 48
BACKGROUND_BOOT_WAIT_SEC = 1.2

DEFAULT_CLICK_HOLD_SEC = 0.05
DEFAULT_DOUBLE_CLICK_INTERVAL_SEC = 0.12
DEFAULT_DRAG_STEPS = 12
DEFAULT_DRAG_DURATION_SEC = 1.0
DEFAULT_DRAG_HOLD_BEFORE_SEC = 0.05
DEFAULT_DRAG_STEP_DELAY_SEC = 0.015
DEFAULT_DRAG_HOLD_AFTER_SEC = 0.03
DEFAULT_KEY_HOLD_SEC = 0.05
DEFAULT_KEY_INTERVAL_SEC = 0.05
DEFAULT_TEXT_INTERVAL_SEC = 0.03
DEFAULT_TEMPLATE_THRESHOLD = 0.9
DEFAULT_TEMPLATE_POLL_INTERVAL_SEC = 0.3
TARGET_X = 590
TARGET_Y = 111
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_INSERT = 0x2D
VK_DELETE = 0x2E

SPECIAL_KEYS = {
    "backspace": VK_BACK,
    "tab": VK_TAB,
    "enter": VK_RETURN,
    "return": VK_RETURN,
    "esc": VK_ESCAPE,
    "escape": VK_ESCAPE,
    "space": VK_SPACE,
    "pageup": VK_PRIOR,
    "pagedown": VK_NEXT,
    "home": VK_HOME,
    "end": VK_END,
    "left": VK_LEFT,
    "up": VK_UP,
    "right": VK_RIGHT,
    "down": VK_DOWN,
    "insert": VK_INSERT,
    "delete": VK_DELETE,
    "shift": VK_SHIFT,
    "ctrl": VK_CONTROL,
    "control": VK_CONTROL,
    "alt": VK_MENU,
}
SPECIAL_KEYS.update({f"f{i}": 0x6F + i for i in range(1, 13)})

EXTENDED_KEYS = {
    VK_PRIOR,
    VK_NEXT,
    VK_END,
    VK_HOME,
    VK_LEFT,
    VK_UP,
    VK_RIGHT,
    VK_DOWN,
    VK_INSERT,
    VK_DELETE,
}



class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


class TOKEN_ELEVATION_STRUCT(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _UNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    _anonymous_ = ("union",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _UNION),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


Logger = Callable[[str], None]
SearchRect = tuple[int, int, int, int]


# 默认空日志函数，用于未传入日志回调时兜底。
def _noop_log(_msg: str):
    pass


# 把客户区坐标打包成 Win32 鼠标消息需要的 LPARAM。
def _make_lparam(x: int, y: int) -> int:
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


# 读取窗口所属进程的 PID。
def _get_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


# 读取窗口类名，便于诊断和日志输出。
def _get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


# 读取窗口标题文本。
def _get_window_text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


# 获取窗口客户区矩形。
def _get_client_rect(hwnd: int) -> wintypes.RECT:
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return rect


# 获取窗口外框矩形。
def _get_window_rect(hwnd: int) -> wintypes.RECT:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect


# 获取窗口外框宽高，并提供最小兜底尺寸。
def _get_window_size(hwnd: int) -> tuple[int, int]:
    rect = _get_window_rect(hwnd)
    return max(rect.right - rect.left, 200), max(rect.bottom - rect.top, 200)


# 复制 WINDOWPLACEMENT 结构，避免直接复用原对象。
def _clone_placement(placement: WINDOWPLACEMENT) -> WINDOWPLACEMENT:
    cloned = WINDOWPLACEMENT()
    ctypes.memmove(
        ctypes.byref(cloned),
        ctypes.byref(placement),
        ctypes.sizeof(WINDOWPLACEMENT),
    )
    return cloned


# 读取窗口当前的放置状态和位置。
def _get_window_placement(hwnd: int) -> WINDOWPLACEMENT | None:
    placement = WINDOWPLACEMENT()
    placement.length = ctypes.sizeof(WINDOWPLACEMENT)
    if not user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
        return None
    return placement


# 判断矩形是否仍落在当前虚拟桌面范围内。
def _rect_intersects_virtual_screen(rect: wintypes.RECT) -> bool:
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    vr = wintypes.RECT(vx, vy, vx + vw, vy + vh)
    return not (
        rect.right <= vr.left
        or rect.left >= vr.right
        or rect.bottom <= vr.top
        or rect.top >= vr.bottom
    )


# 获取整块虚拟桌面的矩形范围。
def _get_virtual_screen_rect() -> wintypes.RECT:
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return wintypes.RECT(vx, vy, vx + vw, vy + vh)


# 根据窗口尺寸计算后台保活时的停靠位置。
def _calc_keepalive_rect(width: int, height: int) -> wintypes.RECT:
    vr = _get_virtual_screen_rect()
    left = vr.right - KEEPALIVE_VISIBLE_WIDTH
    top = vr.top - height + KEEPALIVE_VISIBLE_HEIGHT
    return wintypes.RECT(left, top, left + width, top + height)


# 把一个窗口客户区坐标映射到另一个窗口客户区。
def _map_point_between_clients(src_hwnd: int, dst_hwnd: int, x: int, y: int) -> tuple[int, int]:
    pt = wintypes.POINT(x, y)
    user32.ClientToScreen(src_hwnd, ctypes.byref(pt))
    user32.ScreenToClient(dst_hwnd, ctypes.byref(pt))
    return pt.x, pt.y


# 判断坐标是否位于目标窗口客户区内。
def _point_inside_client(hwnd: int, x: int, y: int) -> bool:
    rect = _get_client_rect(hwnd)
    return 0 <= x < rect.right and 0 <= y < rect.bottom


# 把坐标限制在目标窗口客户区范围内。
def _clamp_point_to_client(hwnd: int, x: int, y: int) -> tuple[int, int]:
    rect = _get_client_rect(hwnd)
    max_x = max(rect.right - 1, 0)
    max_y = max(rect.bottom - 1, 0)
    return min(max(x, 0), max_x), min(max(y, 0), max_y)


# 给坐标加随机偏移，并确保结果仍落在客户区内。
def _apply_random_offset(hwnd: int, x: int, y: int, offset: int) -> tuple[int, int]:
    if offset <= 0:
        return _clamp_point_to_client(hwnd, x, y)
    nx = x + random.randint(-offset, offset)
    ny = y + random.randint(-offset, offset)
    return _clamp_point_to_client(hwnd, nx, ny)


# 把按键名字或整数转换成可发送的虚拟键码。
def _resolve_vk(key: str | int) -> int:
    if isinstance(key, int):
        return key & 0xFF

    normalized = key.strip().lower()
    if normalized in SPECIAL_KEYS:
        return SPECIAL_KEYS[normalized]

    if len(key) == 1:
        scan = user32.VkKeyScanW(ord(key))
        if scan != -1:
            return scan & 0xFF
        upper = key.upper()
        if upper.isalnum():
            return ord(upper)

    raise ValueError(f"不支持的按键: {key!r}")


# 把客户区坐标转换成屏幕坐标。
def _client_to_screen(hwnd: int, x: int, y: int) -> tuple[int, int]:
    pt = wintypes.POINT(x, y)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


# 构造键盘消息需要的 LPARAM。
def _make_key_lparam(vk: int, is_keyup: bool) -> int:
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    lparam = 1 | ((scan & 0xFF) << 16)
    if vk in EXTENDED_KEYS:
        lparam |= 1 << 24
    if is_keyup:
        lparam |= (1 << 30) | (1 << 31)
    return lparam


# 向窗口发送按下或抬起的键盘消息。
def _send_key(hwnd: int, vk: int, is_keyup: bool):
    user32.SendMessageW(
        hwnd,
        WM_KEYUP if is_keyup else WM_KEYDOWN,
        vk,
        _make_key_lparam(vk, is_keyup),
    )


# 向窗口发送单个字符输入。
def _send_char(hwnd: int, char: str):
    code = 13 if char == "\n" else ord(char)
    user32.SendMessageW(hwnd, WM_CHAR, code, 1)


# 向窗口发送鼠标移动消息。
def _send_mouse_move(hwnd: int, x: int, y: int, wparam: int = 0):
    user32.SendMessageW(hwnd, WM_MOUSEMOVE, wparam, _make_lparam(x, y))


# 向窗口发送左键按下消息。
def _send_left_down(hwnd: int, x: int, y: int):
    user32.SendMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _make_lparam(x, y))


# 向窗口发送左键抬起消息。
def _send_left_up(hwnd: int, x: int, y: int):
    user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, _make_lparam(x, y))


# 向窗口发送右键按下消息。
def _send_right_down(hwnd: int, x: int, y: int):
    user32.SendMessageW(hwnd, WM_RBUTTONDOWN, MK_RBUTTON, _make_lparam(x, y))


# 向窗口发送右键抬起消息。
def _send_right_up(hwnd: int, x: int, y: int):
    user32.SendMessageW(hwnd, WM_RBUTTONUP, 0, _make_lparam(x, y))


# 枚举主窗口下的可用子窗口，供点击映射使用。
def _enum_child_windows(hwnd: int) -> list[tuple[int, str, str]]:
    children: list[tuple[int, str, str]] = []

    # 收集遍历到的子窗口句柄、类名和标题。
    def cb(child, _):
        children.append((child, _get_class_name(child), _get_window_text(child)))
        return True

    user32.EnumChildWindows(hwnd, WNDENUMPROC(cb), 0)
    return children


# 判断当前脚本进程是否拥有管理员权限。
def is_self_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


# 判断目标进程是否以管理员权限运行。
def _is_process_elevated(pid: int) -> bool | None:
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(handle, TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            elev = TOKEN_ELEVATION_STRUCT()
            size = wintypes.DWORD(ctypes.sizeof(elev))
            if not advapi32.GetTokenInformation(
                token,
                TokenElevation,
                ctypes.byref(elev),
                ctypes.sizeof(elev),
                ctypes.byref(size),
            ):
                return None
            return bool(elev.TokenIsElevated)
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(handle)


# 输出当前窗口、进程和子窗口的诊断信息。
def diagnose(hwnd: int, log: Logger):
    log("─── 开始诊断 ───")
    log(f"本脚本管理员权限: {'是' if is_self_admin() else '否'}")

    pid = _get_pid(hwnd)
    log(f"目标进程 PID: {pid}")
    target_elevated = _is_process_elevated(pid)
    if target_elevated is None:
        log("目标进程管理员权限: 无法判断")
    else:
        log(f"目标进程管理员权限: {'是' if target_elevated else '否'}")

    log(f"窗口类名: {_get_class_name(hwnd)}")
    log(f"窗口标题: {_get_window_text(hwnd)}")

    client_rect = _get_client_rect(hwnd)
    log(f"客户区大小: {client_rect.right}x{client_rect.bottom}")

    window_rect = _get_window_rect(hwnd)
    log(
        "窗口矩形: "
        f"({window_rect.left}, {window_rect.top}) - "
        f"({window_rect.right}, {window_rect.bottom})"
    )

    is_iconic = bool(user32.IsIconic(hwnd))
    log(f"是否最小化: {'是' if is_iconic else '否'}")
    if is_iconic:
        log("⚠ 目标窗口已最小化。建议先进入后台保活状态，不要直接最小化。")
    elif _rect_intersects_virtual_screen(window_rect):
        log("目标窗口仍在虚拟桌面范围内。")
    else:
        log("目标窗口当前已停靠到屏幕边缘/屏幕外。")

    children = _enum_child_windows(hwnd)
    log(f"子窗口数量: {len(children)}")
    for index, (child_hwnd, cls, title) in enumerate(children[:10], 1):
        rect = _get_client_rect(child_hwnd)
        log(
            f"  子窗口[{index}] hwnd={child_hwnd:#010x} "
            f"class={cls!r} size={rect.right}x{rect.bottom} title={title!r}"
        )
    if len(children) > 10:
        log(f"  ...还有 {len(children) - 10} 个子窗口未显示")

    log("─── 诊断完成 ───")


# 确保目标窗口处于可渲染的后台保活状态。
def ensure_window_running_offscreen(hwnd: int, log: Logger, wait_sec: float = BACKGROUND_BOOT_WAIT_SEC):
    placement = _get_window_placement(hwnd)
    if not placement:
        log("读取窗口位置失败，无法切换后台保活状态。")
        return

    if bool(user32.IsIconic(hwnd)):
        normal = placement.rcNormalPosition
        width = max(normal.right - normal.left, 200)
        height = max(normal.bottom - normal.top, 200)

        parked_rect = _calc_keepalive_rect(width, height)
        offscreen = _clone_placement(placement)
        offscreen.showCmd = SW_SHOWNOACTIVATE
        offscreen.rcNormalPosition.left = parked_rect.left
        offscreen.rcNormalPosition.top = parked_rect.top
        offscreen.rcNormalPosition.right = parked_rect.right
        offscreen.rcNormalPosition.bottom = parked_rect.bottom

        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetWindowPlacement(hwnd, ctypes.byref(offscreen))
        user32.SetWindowPos(
            hwnd,
            0,
            parked_rect.left,
            parked_rect.top,
            width,
            height,
            SWP_NOZORDER | SWP_NOACTIVATE,
        )

        log("检测到目标窗口已最小化，已改为后台保活状态。")
        if wait_sec > 0:
            log(f"等待 {wait_sec:.2f}s，让目标窗口恢复渲染/界面逻辑...")
            time.sleep(wait_sec)
        return

    rect = _get_window_rect(hwnd)
    if _rect_intersects_virtual_screen(rect):
        log("目标窗口当前未最小化。若需要持续渲染，建议先在主界面点击“转后台保活”。")
    else:
        log("目标窗口当前已处于后台保活状态。")


# 按完整消息链发送一次左键点击。
def _send_click(hwnd: int, x: int, y: int, hold_sec: float):
    _send_mouse_move(hwnd, x, y)
    time.sleep(0.02)
    _send_left_down(hwnd, x, y)
    time.sleep(hold_sec)
    _send_left_up(hwnd, x, y)


# 按完整消息链发送一次右键点击。
def _send_right_click(hwnd: int, x: int, y: int, hold_sec: float):
    _send_mouse_move(hwnd, x, y)
    time.sleep(0.02)
    _send_right_down(hwnd, x, y)
    time.sleep(hold_sec)
    _send_right_up(hwnd, x, y)


# 用 SendInput 在屏幕坐标执行一次硬件级左键点击。
def _send_input_click_screen(screen_x: int, screen_y: int, hold_sec: float):
    screen_w = max(user32.GetSystemMetrics(0), 1)
    screen_h = max(user32.GetSystemMetrics(1), 1)
    abs_x = int(screen_x * 65535 / max(screen_w - 1, 1))
    abs_y = int(screen_y * 65535 / max(screen_h - 1, 1))

    inputs = (INPUT * 3)()
    inputs[0].type = INPUT_MOUSE
    inputs[0].mi.dx = abs_x
    inputs[0].mi.dy = abs_y
    inputs[0].mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE

    inputs[1].type = INPUT_MOUSE
    inputs[1].mi.dx = abs_x
    inputs[1].mi.dy = abs_y
    inputs[1].mi.dwFlags = MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE

    inputs[2].type = INPUT_MOUSE
    inputs[2].mi.dx = abs_x
    inputs[2].mi.dy = abs_y
    inputs[2].mi.dwFlags = MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE

    user32.SendInput(1, ctypes.byref(inputs[0]), ctypes.sizeof(INPUT))
    time.sleep(max(hold_sec, 0))
    user32.SendInput(2, ctypes.byref(inputs[1]), ctypes.sizeof(INPUT))


# 临时把目标窗口拉到前台，并在退出时恢复原状态。
@contextmanager
def _temporary_foreground_window(hwnd: int):
    prev_fg = user32.GetForegroundWindow()
    saved = _get_window_placement(hwnd)
    saved_clone = _clone_placement(saved) if saved else None
    width, height = _get_window_size(hwnd)

    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetWindowPos(hwnd, 0, 80, 80, width, height, SWP_NOZORDER)
    time.sleep(0.2)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.12)

    try:
        yield
    finally:
        if saved_clone:
            user32.SetWindowPlacement(hwnd, ctypes.byref(saved_clone))
        else:
            user32.ShowWindow(hwnd, SW_SHOW)
        if prev_fg and user32.IsWindow(prev_fg):
            user32.SetForegroundWindow(prev_fg)


# 临时前台化窗口后执行一次硬件级点击。
def _foreground_hardware_click(hwnd: int, x: int, y: int, hold_sec: float):
    with _temporary_foreground_window(hwnd):
        screen_x, screen_y = _client_to_screen(hwnd, x, y)
        _send_input_click_screen(screen_x, screen_y, hold_sec)


# 确认模板识别依赖的 OpenCV 和 numpy 已安装。
def _ensure_cv2_available():
    if cv2 is None or np is None:
        raise RuntimeError("未安装 OpenCV。请先执行 requirements.txt 中的依赖安装。")


# 解析模板名并定位到实际可读的模板文件路径。
def _resolve_template_path(name: str | Path) -> Path:
    raw = Path(name)
    candidates: list[Path] = []

    # 向候选列表追加不重复的模板路径。
    def add_candidate(path: Path):
        if path not in candidates:
            candidates.append(path)

    if raw.is_absolute():
        add_candidate(raw)
    else:
        add_candidate(raw)
        add_candidate(TEMPLATE_DIR / raw)

    if not raw.suffix:
        expanded: list[Path] = []
        for candidate in candidates:
            expanded.append(candidate)
            for ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
                expanded.append(candidate.with_suffix(ext))
        candidates = []
        for candidate in expanded:
            add_candidate(candidate)

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        f"未找到模板图: {name!r}。可把模板放到 {TEMPLATE_DIR}，文件名如 start_button.png"
    )


# 抓取窗口画面并转换为 BGR 图像。
def _capture_window_bgr(hwnd: int, client_only: bool = True):
    _ensure_cv2_available()
    if not user32.IsWindow(hwnd):
        return None

    if client_only:
        rect = _get_client_rect(hwnd)
        width = rect.right
        height = rect.bottom
        pw_flags_candidates = [PW_CLIENTONLY, PW_RENDERFULLCONTENT, 0]
        fallback_dc_getter = user32.GetDC
    else:
        rect = _get_window_rect(hwnd)
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        pw_flags_candidates = [PW_RENDERFULLCONTENT, 0, PW_CLIENTONLY]
        fallback_dc_getter = user32.GetWindowDC

    if width <= 0 or height <= 0:
        return None

    screen_dc = user32.GetDC(0)
    if not screen_dc:
        return None

    src_dc = gdi32.CreateCompatibleDC(screen_dc)
    src_bmp = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    src_old = gdi32.SelectObject(src_dc, src_bmp)

    try:
        ok = False
        for flags in pw_flags_candidates:
            try:
                dwmapi.DwmFlush()
            except Exception:
                pass
            ok = bool(user32.PrintWindow(hwnd, src_dc, flags))
            if ok:
                break

        if not ok:
            hwnd_dc = fallback_dc_getter(hwnd)
            if hwnd_dc:
                try:
                    gdi32.BitBlt(src_dc, 0, 0, width, height, hwnd_dc, 0, 0, SRCCOPY)
                    ok = True
                finally:
                    user32.ReleaseDC(hwnd, hwnd_dc)

        if not ok:
            return None

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = width
        bmi.biHeight = -height
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = BI_RGB

        buf_size = width * height * 4
        buf = ctypes.create_string_buffer(buf_size)
        got = gdi32.GetDIBits(
            src_dc,
            src_bmp,
            0,
            height,
            buf,
            ctypes.byref(bmi),
            DIB_RGB_COLORS,
        )
        if got != height:
            return None

        bgra = np.frombuffer(buf, dtype=np.uint8).reshape((height, width, 4)).copy()
        return bgra[:, :, :3]
    finally:
        gdi32.SelectObject(src_dc, src_old)
        gdi32.DeleteObject(src_bmp)
        gdi32.DeleteDC(src_dc)
        user32.ReleaseDC(0, screen_dc)


# 加载模板图片，并按路径和修改时间缓存结果。
def _load_template_image(name: str | Path, grayscale: bool):
    _ensure_cv2_available()
    path = _resolve_template_path(name)
    flag = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
    resolved_path = path.resolve()
    stat = resolved_path.stat()
    cache_key = (str(resolved_path), grayscale)

    with _TEMPLATE_IMAGE_CACHE_LOCK:
        cached = _TEMPLATE_IMAGE_CACHE.get(cache_key)
        if cached:
            cached_mtime_ns, cached_size, cached_template = cached
            if cached_mtime_ns == stat.st_mtime_ns and cached_size == stat.st_size:
                return cached_template, path

    # Windows 下 cv2.imread() 可能无法读取带中文目录名的路径，
    # 先用 np.fromfile + cv2.imdecode 兼容这类模板目录。
    template = None
    try:
        encoded = np.fromfile(str(resolved_path), dtype=np.uint8)
        if encoded.size > 0:
            template = cv2.imdecode(encoded, flag)
    except Exception:
        template = None

    if template is None:
        template = cv2.imread(str(resolved_path), flag)
    if template is None:
        raise RuntimeError(f"模板图读取失败: {path}")

    with _TEMPLATE_IMAGE_CACHE_LOCK:
        _TEMPLATE_IMAGE_CACHE[cache_key] = (
            stat.st_mtime_ns,
            stat.st_size,
            template,
        )
    return template, path


# 执行模板匹配并返回命中位置与分数。
def _match_template(frame, template, threshold: float):
    _ensure_cv2_available()
    fh, fw = frame.shape[:2]
    th, tw = template.shape[:2]
    if fw < tw or fh < th:
        return None

    result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
    score = float(max_val)
    if score < threshold:
        return None

    center_x = max_loc[0] + tw // 2
    center_y = max_loc[1] + th // 2
    return center_x, center_y, score, max_loc[0], max_loc[1], tw, th


# 按匹配模式把待搜索图像预处理成灰度或彩色。
def _prepare_match_frame(frame, grayscale: bool):
    _ensure_cv2_available()
    if grayscale:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return frame


# 规范化搜索区域并裁剪到当前图像范围内。
def _normalize_search_rect(
    search_rect: SearchRect,
    frame_width: int,
    frame_height: int,
) -> SearchRect | None:
    left, top, right, bottom = (int(value) for value in search_rect)
    left = min(max(left, 0), frame_width)
    top = min(max(top, 0), frame_height)
    right = min(max(right, 0), frame_width)
    bottom = min(max(bottom, 0), frame_height)
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


# 按搜索区域裁剪当前帧，并返回偏移信息。
def _crop_frame_to_search_rect(frame, search_rect: SearchRect | None):
    if search_rect is None:
        return frame, 0, 0, None
    frame_height, frame_width = frame.shape[:2]
    normalized = _normalize_search_rect(search_rect, frame_width, frame_height)
    if normalized is None:
        return None, 0, 0, None
    left, top, right, bottom = normalized
    return frame[top:bottom, left:right], left, top, normalized


# 根据坐标自动决定点击主窗口还是命中的子窗口。
def _resolve_click_target(
    main_hwnd: int,
    x: int,
    y: int,
    search_children: bool = True,
) -> tuple[int, int, int, str]:
    if not search_children:
        return main_hwnd, x, y, "主窗口"

    candidates = []
    for child_hwnd, cls, title in _enum_child_windows(main_hwnd):
        if not user32.IsWindowVisible(child_hwnd):
            continue
        cx, cy = _map_point_between_clients(main_hwnd, child_hwnd, x, y)
        if not _point_inside_client(child_hwnd, cx, cy):
            continue
        rect = _get_client_rect(child_hwnd)
        area = max(rect.right, 1) * max(rect.bottom, 1)
        candidates.append((area, child_hwnd, cls, title, cx, cy))

    if not candidates:
        return main_hwnd, x, y, "主窗口"

    candidates.sort(key=lambda item: item[0])
    _area, child_hwnd, cls, title, cx, cy = candidates[0]
    label = f"子窗口 class={cls!r} title={title!r}"
    return child_hwnd, cx, cy, label


# 根据起止坐标自动决定拖拽目标窗口和映射坐标。
def _resolve_drag_target(
    main_hwnd: int,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    search_children: bool = True,
) -> tuple[int, int, int, int, int, str]:
    if not search_children:
        return main_hwnd, start_x, start_y, end_x, end_y, "主窗口"

    candidates = []
    for child_hwnd, cls, title in _enum_child_windows(main_hwnd):
        if not user32.IsWindowVisible(child_hwnd):
            continue
        sx, sy = _map_point_between_clients(main_hwnd, child_hwnd, start_x, start_y)
        ex, ey = _map_point_between_clients(main_hwnd, child_hwnd, end_x, end_y)
        if not _point_inside_client(child_hwnd, sx, sy):
            continue
        if not _point_inside_client(child_hwnd, ex, ey):
            continue
        rect = _get_client_rect(child_hwnd)
        area = max(rect.right, 1) * max(rect.bottom, 1)
        candidates.append((area, child_hwnd, cls, title, sx, sy, ex, ey))

    if not candidates:
        return main_hwnd, start_x, start_y, end_x, end_y, "主窗口"

    candidates.sort(key=lambda item: item[0])
    _area, child_hwnd, cls, title, sx, sy, ex, ey = candidates[0]
    label = f"子窗口 class={cls!r} title={title!r}"
    return child_hwnd, sx, sy, ex, ey, label


# 按完整鼠标消息链执行一次拖拽。
def _send_drag(
    hwnd: int,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    steps: int,
    hold_before_sec: float,
    step_delay_sec: float,
    hold_after_sec: float,
):
    steps = max(steps, 1)
    start_lp = _make_lparam(start_x, start_y)
    end_lp = _make_lparam(end_x, end_y)

    user32.SendMessageW(hwnd, WM_MOUSEMOVE, 0, start_lp)
    time.sleep(0.02)
    user32.SendMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, start_lp)
    time.sleep(max(hold_before_sec, 0))

    for step in range(1, steps):
        ratio = step / steps
        ix = round(start_x + (end_x - start_x) * ratio)
        iy = round(start_y + (end_y - start_y) * ratio)
        user32.SendMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, _make_lparam(ix, iy))
        time.sleep(max(step_delay_sec, 0))

    user32.SendMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, end_lp)
    time.sleep(max(hold_after_sec, 0))
    user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, end_lp)


class WindowAutomation:
    # 保存目标窗口句柄和日志回调，初始化自动化对象。
    def __init__(self, hwnd: int, log: Logger | None = None):
        self.hwnd = hwnd
        self.log = log if callable(log) else _noop_log

    # 调用诊断逻辑并返回自身，便于链式调用。
    def diagnose(self):
        diagnose(self.hwnd, self.log)
        return self

    # 确保目标窗口进入可用的后台保活状态。
    def prepare(self, wait_sec: float = BACKGROUND_BOOT_WAIT_SEC):
        ensure_window_running_offscreen(self.hwnd, self.log, wait_sec=wait_sec)
        return self

    # 执行一次简单等待并记录日志。
    def wait(self, seconds: float):
        self.log(f"等待 {seconds:.2f}s")
        time.sleep(max(seconds, 0))
        return self

    # 在窗口画面中查找模板并返回中心坐标。
    def find_image(
        self,
        name: str | Path,
        *,
        threshold: float = DEFAULT_TEMPLATE_THRESHOLD,
        grayscale: bool = True,
        client_only: bool = True,
        search_rect: SearchRect | None = None,
        log_miss: bool = True,
    ) -> tuple[int, int, float] | None:
        template, path = _load_template_image(name, grayscale)
        frame = _capture_window_bgr(self.hwnd, client_only=client_only)
        if frame is None:
            if log_miss:
                self.log("模板识别抓帧失败：当前未拿到可用窗口图像。")
            return None

        search_frame, offset_x, offset_y, normalized_rect = _crop_frame_to_search_rect(
            frame,
            search_rect,
        )
        if search_frame is None:
            if log_miss:
                self.log(f"搜索区域无效或超出当前窗口范围: {search_rect}")
            return None

        match = _match_template(
            _prepare_match_frame(search_frame, grayscale),
            template,
            threshold,
        )
        search_rect_text = f" search_rect={normalized_rect}" if normalized_rect else ""
        if not match:
            if log_miss:
                self.log(
                    f"未识别到模板: {path.name} threshold={threshold:.2f}{search_rect_text}"
                )
            return None

        center_x, center_y, score, left, top, width, height = match
        center_x += offset_x
        center_y += offset_y
        left += offset_x
        top += offset_y
        self.log(
            f"识别到模板: {path.name} score={score:.4f} "
            f"center=({center_x}, {center_y}) rect=({left}, {top}, {width}, {height})"
            f"{search_rect_text}"
        )
        return center_x, center_y, score

    # 轮询等待模板出现，直到超时或命中。
    def wait_image(
        self,
        name: str | Path,
        *,
        timeout_sec: float = 5.0,
        interval_sec: float = DEFAULT_TEMPLATE_POLL_INTERVAL_SEC,
        threshold: float = DEFAULT_TEMPLATE_THRESHOLD,
        grayscale: bool = True,
        client_only: bool = True,
        search_rect: SearchRect | None = None,
    ) -> tuple[int, int, float] | None:
        template, path = _load_template_image(name, grayscale)
        deadline = time.monotonic() + max(timeout_sec, 0)
        search_rect_text = f" search_rect={search_rect}" if search_rect else ""
        self.log(
            f"等待模板出现: {path.name} timeout={timeout_sec:.2f}s "
            f"threshold={threshold:.2f}{search_rect_text}"
        )
        while True:
            frame = _capture_window_bgr(self.hwnd, client_only=client_only)
            if frame is not None:
                search_frame, offset_x, offset_y, normalized_rect = _crop_frame_to_search_rect(
                    frame,
                    search_rect,
                )
                if search_frame is None:
                    self.log(f"等待失败：搜索区域无效或超出当前窗口范围: {search_rect}")
                    return None
                match = _match_template(
                    _prepare_match_frame(search_frame, grayscale),
                    template,
                    threshold,
                )
                if match:
                    center_x, center_y, score, left, top, width, height = match
                    center_x += offset_x
                    center_y += offset_y
                    left += offset_x
                    top += offset_y
                    normalized_text = (
                        f" search_rect={normalized_rect}" if normalized_rect else ""
                    )
                    self.log(
                        f"等待成功: {path.name} score={score:.4f} "
                        f"center=({center_x}, {center_y}) rect=({left}, {top}, {width}, {height})"
                        f"{normalized_text}"
                    )
                    return center_x, center_y, score

            if time.monotonic() >= deadline:
                self.log(f"等待超时: 未识别到模板 {path.name}{search_rect_text}")
                return None
            time.sleep(max(interval_sec, 0))

    # 识别模板后执行一次普通点击。
    def click_image(
        self,
        name: str | Path,
        *,
        threshold: float = DEFAULT_TEMPLATE_THRESHOLD,
        grayscale: bool = True,
        client_only: bool = True,
        search_rect: SearchRect | None = None,
        offset: int = 0,
        search_children: bool = True,
        hold_sec: float = DEFAULT_CLICK_HOLD_SEC,
    ) -> tuple[int, int, float] | None:
        match = self.find_image(
            name,
            threshold=threshold,
            grayscale=grayscale,
            client_only=client_only,
            search_rect=search_rect,
        )
        if not match:
            return None
        x, y, score = match
        self.click(
            x,
            y,
            offset=offset,
            search_children=search_children,
            hold_sec=hold_sec,
        )
        return x, y, score

    # 识别模板后执行一次带前台回退的强力点击。
    def click_image_robust(
        self,
        name: str | Path,
        *,
        threshold: float = DEFAULT_TEMPLATE_THRESHOLD,
        grayscale: bool = True,
        client_only: bool = True,
        search_rect: SearchRect | None = None,
        offset: int = 0,
        search_children: bool = True,
        hold_sec: float = DEFAULT_CLICK_HOLD_SEC,
    ) -> tuple[int, int, float] | None:
        match = self.find_image(
            name,
            threshold=threshold,
            grayscale=grayscale,
            client_only=client_only,
            search_rect=search_rect,
        )
        if not match:
            return None
        x, y, score = match
        self.click_robust(
            x,
            y,
            offset=offset,
            search_children=search_children,
            hold_sec=hold_sec,
        )
        return x, y, score

    # 向目标窗口发送一次鼠标移动。
    def move_to(
        self,
        x: int,
        y: int,
        offset: int = 0,
        *,
        search_children: bool = True,
    ) -> tuple[int, int]:
        final_x, final_y = _apply_random_offset(self.hwnd, x, y, offset)
        target_hwnd, target_x, target_y, target_label = _resolve_click_target(
            self.hwnd,
            final_x,
            final_y,
            search_children=search_children,
        )
        self.log(
            f"移动: base=({x}, {y}) final=({final_x}, {final_y}) "
            f"offset={offset} target={target_label} mapped=({target_x}, {target_y})"
        )
        _send_mouse_move(target_hwnd, target_x, target_y)
        return final_x, final_y

    # 在目标坐标执行一次普通左键点击。
    def click(
        self,
        x: int,
        y: int,
        offset: int = 0,
        *,
        search_children: bool = True,
        hold_sec: float = DEFAULT_CLICK_HOLD_SEC,
    ) -> tuple[int, int]:
        final_x, final_y = _apply_random_offset(self.hwnd, x, y, offset)
        target_hwnd, target_x, target_y, target_label = _resolve_click_target(
            self.hwnd,
            final_x,
            final_y,
            search_children=search_children,
        )
        self.log(
            f"单击: base=({x}, {y}) final=({final_x}, {final_y}) "
            f"offset={offset} target={target_label} mapped=({target_x}, {target_y})"
        )
        _send_click(target_hwnd, target_x, target_y, hold_sec)
        return final_x, final_y

    # 在目标坐标执行一次双击。
    def double_click(
        self,
        x: int,
        y: int,
        offset: int = 0,
        *,
        search_children: bool = True,
        hold_sec: float = DEFAULT_CLICK_HOLD_SEC,
        interval_sec: float = DEFAULT_DOUBLE_CLICK_INTERVAL_SEC,
    ) -> tuple[int, int]:
        final_x, final_y = _apply_random_offset(self.hwnd, x, y, offset)
        target_hwnd, target_x, target_y, target_label = _resolve_click_target(
            self.hwnd,
            final_x,
            final_y,
            search_children=search_children,
        )
        self.log(
            f"双击: base=({x}, {y}) final=({final_x}, {final_y}) "
            f"offset={offset} target={target_label} mapped=({target_x}, {target_y})"
        )

        for click_index in range(1, 3):
            self.log(f"  第 {click_index} 次点击")
            _send_click(target_hwnd, target_x, target_y, hold_sec)
            if click_index == 1:
                time.sleep(max(interval_sec, 0))
        return final_x, final_y

    # 在目标坐标执行一次右键点击。
    def right_click(
        self,
        x: int,
        y: int,
        offset: int = 0,
        *,
        search_children: bool = True,
        hold_sec: float = DEFAULT_CLICK_HOLD_SEC,
    ) -> tuple[int, int]:
        final_x, final_y = _apply_random_offset(self.hwnd, x, y, offset)
        target_hwnd, target_x, target_y, target_label = _resolve_click_target(
            self.hwnd,
            final_x,
            final_y,
            search_children=search_children,
        )
        self.log(
            f"右击: base=({x}, {y}) final=({final_x}, {final_y}) "
            f"offset={offset} target={target_label} mapped=({target_x}, {target_y})"
        )
        _send_right_click(target_hwnd, target_x, target_y, hold_sec)
        return final_x, final_y

    # 先普通点击，再按需补一次前台硬件点击。
    def click_robust(
        self,
        x: int,
        y: int,
        offset: int = 0,
        *,
        search_children: bool = True,
        hold_sec: float = DEFAULT_CLICK_HOLD_SEC,
        foreground_fallback: bool = True,
    ) -> tuple[int, int]:
        final_x, final_y = self.click(
            x,
            y,
            offset,
            search_children=search_children,
            hold_sec=hold_sec,
        )
        if foreground_fallback:
            self.log(
                "强力点击回退：将短暂把目标窗口拉到前台，并用硬件级鼠标再点击一次。"
            )
            _foreground_hardware_click(self.hwnd, final_x, final_y, hold_sec)
        return final_x, final_y

    # 向窗口发送按键按下消息。
    def key_down(self, key: str | int):
        vk = _resolve_vk(key)
        self.log(f"按下按键: {key!r} vk=0x{vk:02X}")
        _send_key(self.hwnd, vk, is_keyup=False)
        return self

    # 向窗口发送按键抬起消息。
    def key_up(self, key: str | int):
        vk = _resolve_vk(key)
        self.log(f"抬起按键: {key!r} vk=0x{vk:02X}")
        _send_key(self.hwnd, vk, is_keyup=True)
        return self

    # 按指定次数执行完整的按键点击。
    def press_key(
        self,
        key: str | int,
        repeat: int = 1,
        *,
        hold_sec: float = DEFAULT_KEY_HOLD_SEC,
        interval_sec: float = DEFAULT_KEY_INTERVAL_SEC,
    ):
        vk = _resolve_vk(key)
        repeat = max(repeat, 1)
        self.log(f"按键点击: {key!r} vk=0x{vk:02X} repeat={repeat}")
        for index in range(repeat):
            _send_key(self.hwnd, vk, is_keyup=False)
            time.sleep(max(hold_sec, 0))
            _send_key(self.hwnd, vk, is_keyup=True)
            if index < repeat - 1:
                time.sleep(max(interval_sec, 0))
        return self

    # 按顺序按下并释放一组组合键。
    def hotkey(self, *keys: str | int, hold_sec: float = DEFAULT_KEY_HOLD_SEC):
        if not keys:
            return self
        vk_keys = [_resolve_vk(key) for key in keys]
        joined = " + ".join(str(key) for key in keys)
        self.log(f"组合键: {joined}")
        for vk in vk_keys:
            _send_key(self.hwnd, vk, is_keyup=False)
        time.sleep(max(hold_sec, 0))
        for vk in reversed(vk_keys):
            _send_key(self.hwnd, vk, is_keyup=True)
        return self

    # 按字符逐个向窗口发送文本。
    def send_text(self, text: str, interval_sec: float = DEFAULT_TEXT_INTERVAL_SEC):
        self.log(f"发送文本: {text!r}")
        for index, char in enumerate(text):
            _send_char(self.hwnd, char)
            if index < len(text) - 1:
                time.sleep(max(interval_sec, 0))
        return self

    # 按固定次数连续右键清理指定位置的界面内容。
    def force_clear_ui(
        self,
        x: int = FORCE_CLEAR_UI_X,
        y: int = FORCE_CLEAR_UI_Y,
        *,
        repeat: int = FORCE_CLEAR_UI_REPEAT,
        interval_sec: float = FORCE_CLEAR_UI_INTERVAL_SEC,
        offset: int = 0,
        search_children: bool = True,
        hold_sec: float = DEFAULT_CLICK_HOLD_SEC,
    ):
        repeat = max(repeat, 1)
        self.log(
            f"强制清除界面内容: point=({x}, {y}) repeat={repeat} "
            f"interval_sec={interval_sec:.2f} offset={offset}"
        )
        for index in range(repeat):
            self.log(f"  第 {index + 1} 次右键清除")
            self.right_click(
                x,
                y,
                offset=offset,
                search_children=search_children,
                hold_sec=hold_sec,
            )
            if index < repeat - 1:
                time.sleep(max(interval_sec, 0))
        return self

    # 在目标窗口内执行一次拖拽操作。
    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        offset: int = 0,
        *,
        search_children: bool = True,
        steps: int = DEFAULT_DRAG_STEPS,
        duration_sec: float | None = DEFAULT_DRAG_DURATION_SEC,
        hold_before_sec: float = DEFAULT_DRAG_HOLD_BEFORE_SEC,
        step_delay_sec: float = DEFAULT_DRAG_STEP_DELAY_SEC,
        hold_after_sec: float = DEFAULT_DRAG_HOLD_AFTER_SEC,
    ) -> tuple[int, int, int, int]:
        final_start_x, final_start_y = _apply_random_offset(self.hwnd, start_x, start_y, offset)
        final_end_x, final_end_y = _apply_random_offset(self.hwnd, end_x, end_y, offset)
        (
            target_hwnd,
            target_start_x,
            target_start_y,
            target_end_x,
            target_end_y,
            target_label,
        ) = _resolve_drag_target(
            self.hwnd,
            final_start_x,
            final_start_y,
            final_end_x,
            final_end_y,
            search_children=search_children,
        )

        self.log(
            "拖动: "
            f"base_start=({start_x}, {start_y}) final_start=({final_start_x}, {final_start_y}) "
            f"base_end=({end_x}, {end_y}) final_end=({final_end_x}, {final_end_y}) "
            f"offset={offset} target={target_label} "
            f"mapped_start=({target_start_x}, {target_start_y}) "
            f"mapped_end=({target_end_x}, {target_end_y}) steps={max(steps, 1)} "
            f"duration_sec={'manual' if duration_sec is None else f'{max(duration_sec, 0):.2f}'}"
        )
        effective_step_delay_sec = step_delay_sec
        if duration_sec is not None:
            movement_intervals = max(max(steps, 1) - 1, 1)
            effective_step_delay_sec = max(duration_sec, 0) / movement_intervals
        _send_drag(
            target_hwnd,
            target_start_x,
            target_start_y,
            target_end_x,
            target_end_y,
            steps=steps,
            hold_before_sec=hold_before_sec,
            step_delay_sec=effective_step_delay_sec,
            hold_after_sec=hold_after_sec,
        )
        return final_start_x, final_start_y, final_end_x, final_end_y


# 提供一个最小示例入口，便于直接验证动作链路。
def run(hwnd: int, log: Logger):
    bot = WindowAutomation(hwnd, log)
    bot.diagnose()
    bot.prepare()
    bot.click(TARGET_X, TARGET_Y)
