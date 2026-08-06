"""
窗口后台截图工具 - Windows 11
使用 DWM Thumbnail API 直接从 GPU 合成器获取窗口画面。
即使窗口最小化也能实时渲染，与 Windows 任务栏预览使用相同机制。
零第三方依赖（仅 tkinter + ctypes）。
"""

import ctypes
import ctypes.wintypes as wintypes
import importlib
import base64
import os
import re
import subprocess
import struct
import sys
import threading
import time
import tkinter as tk
import zlib
from tkinter import messagebox, ttk

VIRTUAL_CLICK_LOG_RE = re.compile(
    r"^(?P<action>单击|双击|右击): .*final=\((?P<x>-?\d+),\s*(?P<y>-?\d+)\)"
)
DOUBLE_CLICK_STEP_LOG_RE = re.compile(r"^第\s*(?P<index>\d+)\s*次点击$")
PREVIEW_CLICK_MARKER_VISIBLE_MS = 5000
PREVIEW_VIRTUAL_CLICK_FLASH_MS = 900
LOG_TEXT_MAX_LINES = 2000
LOG_TEXT_TRIM_TO_LINES = 1500

# ─── DPI Awareness（必须在创建任何窗口之前调用）─────────────────────────────

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

# ─── Windows API 句柄 ────────────────────────────────────────────────────────

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
advapi32 = ctypes.windll.advapi32
shell32 = ctypes.windll.shell32

# ─── 常量 ─────────────────────────────────────────────────────────────────────

GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
GW_OWNER = 4
GA_ROOT = 2
DWMWA_CLOAKED = 14

DWM_TNP_RECTDESTINATION = 0x00000001
DWM_TNP_RECTSOURCE = 0x00000002
DWM_TNP_VISIBLE = 0x00000008
DWM_TNP_SOURCECLIENTAREAONLY = 0x00000010
DWM_TNP_OPACITY = 0x00000004
PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002
BI_RGB = 0
DIB_RGB_COLORS = 0
SRCCOPY = 0x00CC0020
HALFTONE = 4

SW_SHOWNOACTIVATE = 4
SW_RESTORE = 9
SW_HIDE = 0
SW_SHOWNA = 8
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
WS_POPUP = 0x80000000
WS_OVERLAPPEDWINDOW = 0x00CF0000
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
PROCESS_QUERY_INFORMATION = 0x0400
TOKEN_QUERY = 0x0008
TokenElevation = 20
KEEPALIVE_VISIBLE_WIDTH = 24
KEEPALIVE_VISIBLE_HEIGHT = 48

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# ─── DWM Thumbnail 结构体 ────────────────────────────────────────────────────

HTHUMBNAIL = ctypes.c_void_p


class DWM_THUMBNAIL_PROPERTIES(ctypes.Structure):
    _fields_ = [
        ("dwFlags", wintypes.DWORD),
        ("rcDestination", wintypes.RECT),
        ("rcSource", wintypes.RECT),
        ("opacity", wintypes.BYTE),
        ("fVisible", wintypes.BOOL),
        ("fSourceClientAreaOnly", wintypes.BOOL),
    ]


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


# ─── DWM API 声明 ────────────────────────────────────────────────────────────

dwmapi.DwmRegisterThumbnail.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.POINTER(HTHUMBNAIL)
]
dwmapi.DwmRegisterThumbnail.restype = ctypes.HRESULT

dwmapi.DwmUnregisterThumbnail.argtypes = [HTHUMBNAIL]
dwmapi.DwmUnregisterThumbnail.restype = ctypes.HRESULT

dwmapi.DwmUpdateThumbnailProperties.argtypes = [
    HTHUMBNAIL, ctypes.POINTER(DWM_THUMBNAIL_PROPERTIES)
]
dwmapi.DwmUpdateThumbnailProperties.restype = ctypes.HRESULT

dwmapi.DwmQueryThumbnailSourceSize.argtypes = [
    HTHUMBNAIL, ctypes.POINTER(wintypes.SIZE)
]
dwmapi.DwmQueryThumbnailSourceSize.restype = ctypes.HRESULT

dwmapi.DwmGetWindowAttribute.argtypes = [
    wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD
]
dwmapi.DwmGetWindowAttribute.restype = ctypes.HRESULT


# ─── 窗口枚举 ────────────────────────────────────────────────────────────────


def _is_alt_tab_window(hwnd: int) -> bool:
    """判断窗口是否会出现在 Alt+Tab 列表中。"""
    if not user32.IsWindowVisible(hwnd):
        return False
    if user32.GetWindowTextLengthW(hwnd) == 0:
        return False

    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if ex_style & WS_EX_TOOLWINDOW:
        return False
    owner = user32.GetWindow(hwnd, GW_OWNER)
    if owner and not (ex_style & WS_EX_APPWINDOW):
        return False

    cloaked = wintypes.DWORD(0)
    dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
    )
    if cloaked.value:
        return False
    return True


def get_window_list() -> list[tuple[int, str]]:
    """枚举所有 Alt+Tab 可见窗口。"""
    windows: list[tuple[int, str]] = []

    def callback(hwnd, _):
        if _is_alt_tab_window(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            windows.append((hwnd, buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return windows


def _get_window_text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def _get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _get_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _get_window_rect(hwnd: int) -> wintypes.RECT:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect


def _get_client_rect(hwnd: int) -> wintypes.RECT:
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return rect


def _get_client_offset_in_window(hwnd: int) -> tuple[int, int]:
    window_rect = _get_window_rect(hwnd)
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x - window_rect.left, pt.y - window_rect.top


def _get_window_outer_size_for_client(hwnd: int, client_width: int, client_height: int) -> tuple[int, int]:
    rect = wintypes.RECT(0, 0, max(client_width, 1), max(client_height, 1))
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    has_menu = bool(user32.GetMenu(hwnd))

    adjusted = False
    if hasattr(user32, "AdjustWindowRectExForDpi"):
        try:
            dpi = user32.GetDpiForWindow(hwnd) if hasattr(user32, "GetDpiForWindow") else 96
            adjusted = bool(
                user32.AdjustWindowRectExForDpi(
                    ctypes.byref(rect),
                    style,
                    has_menu,
                    ex_style,
                    dpi or 96,
                )
            )
        except Exception:
            adjusted = False

    if not adjusted:
        user32.AdjustWindowRectEx(
            ctypes.byref(rect),
            style,
            has_menu,
            ex_style,
        )

    return (
        max(rect.right - rect.left, client_width),
        max(rect.bottom - rect.top, client_height),
    )


def _rect_intersects_virtual_screen(rect: wintypes.RECT) -> bool:
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return not (
        rect.right <= vx
        or rect.left >= vx + vw
        or rect.bottom <= vy
        or rect.top >= vy + vh
    )


def _get_virtual_screen_rect() -> wintypes.RECT:
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return wintypes.RECT(vx, vy, vx + vw, vy + vh)


def _calc_keepalive_rect(width: int, height: int) -> wintypes.RECT:
    """
    把窗口停靠到屏幕右上角，只留下一个很小的可见角。
    这样既尽量不打扰桌面，又避免“完全离屏/完全遮挡”导致游戏停止渲染。
    """
    vr = _get_virtual_screen_rect()
    left = vr.right - KEEPALIVE_VISIBLE_WIDTH
    top = vr.top - height + KEEPALIVE_VISIBLE_HEIGHT
    return wintypes.RECT(left, top, left + width, top + height)


def _is_keepalive_parked(rect: wintypes.RECT) -> bool:
    vr = _get_virtual_screen_rect()
    overlap_left = max(rect.left, vr.left)
    overlap_top = max(rect.top, vr.top)
    overlap_right = min(rect.right, vr.right)
    overlap_bottom = min(rect.bottom, vr.bottom)
    overlap_w = max(overlap_right - overlap_left, 0)
    overlap_h = max(overlap_bottom - overlap_top, 0)
    return overlap_w <= KEEPALIVE_VISIBLE_WIDTH + 4 and overlap_h <= KEEPALIVE_VISIBLE_HEIGHT + 4


def _enum_process_windows(pid: int) -> list[int]:
    windows: list[int] = []

    def callback(hwnd, _lparam):
        if _get_pid(hwnd) != pid:
            return True
        if user32.GetAncestor(hwnd, GA_ROOT) != hwnd:
            return True
        if not user32.IsWindow(hwnd):
            return True
        if not user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            return True
        windows.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return windows


def _rect_area(rect: wintypes.RECT) -> int:
    return max(rect.right - rect.left, 0) * max(rect.bottom - rect.top, 0)


def _resolve_best_process_window(seed_hwnd: int) -> tuple[int, list[tuple[int, int, str, str, wintypes.RECT]]]:
    """
    从同进程顶层窗口里挑一个更像“真正渲染/输入窗口”的目标。
    返回 (best_hwnd, candidates)。
    candidates: [(hwnd, area, class_name, title, rect), ...] 按面积降序。
    """
    pid = _get_pid(seed_hwnd)
    process_windows = _enum_process_windows(pid)
    candidates: list[tuple[int, int, str, str, wintypes.RECT]] = []

    for hwnd in process_windows:
        rect = _get_window_rect(hwnd)
        area = _rect_area(rect)
        if area <= 0:
            continue
        candidates.append((
            hwnd,
            area,
            _get_class_name(hwnd),
            _get_window_text(hwnd),
            rect,
        ))

    candidates.sort(key=lambda item: item[1], reverse=True)
    if not candidates:
        return seed_hwnd, []

    best_hwnd = seed_hwnd
    seed_rect = _get_window_rect(seed_hwnd)
    seed_area = _rect_area(seed_rect)
    best_area = candidates[0][1]

    # 如果当前选中的窗口面积明显偏小（例如只有标题栏），优先切到同进程最大窗口。
    if best_area > max(seed_area * 4, 120000):
        best_hwnd = candidates[0][0]

    return best_hwnd, candidates


def _is_self_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_current_process_as_admin() -> bool:
    if getattr(sys, "frozen", False):
        executable = sys.executable
        params = subprocess.list2cmdline(sys.argv[1:])
    else:
        executable = sys.executable
        exe_dir, exe_name = os.path.split(os.path.abspath(executable))
        if exe_name.lower() == "python.exe":
            pythonw_executable = os.path.join(exe_dir, "pythonw.exe")
            if os.path.isfile(pythonw_executable):
                executable = pythonw_executable
        script_path = os.path.abspath(sys.argv[0] or __file__)
        params = subprocess.list2cmdline([script_path, *sys.argv[1:]])

    result = shell32.ShellExecuteW(
        None,
        "runas",
        executable,
        params,
        os.getcwd(),
        1,
    )
    return result > 32


def _ensure_admin_startup() -> bool:
    if _is_self_admin():
        return True

    if _relaunch_current_process_as_admin():
        return False

    user32.MessageBoxW(
        None,
        "需要管理员权限才能启动本工具。\n\n你取消了 UAC 或管理员启动失败，程序将退出。",
        "需要管理员权限",
        0x00000000 | 0x00000030,
    )
    return False


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


def _format_win32_error(err: int) -> str:
    if not err:
        return "OK"
    buf = ctypes.create_unicode_buffer(512)
    flags = 0x00001000 | 0x00000200  # FROM_SYSTEM | IGNORE_INSERTS
    length = kernel32.FormatMessageW(flags, None, err, 0, buf, len(buf), None)
    if length:
        return buf.value.strip()
    return f"Unknown error {err}"


def _fit_size(src_w: int, src_h: int, max_w: int, max_h: int) -> tuple[int, int]:
    if src_w <= 0 or src_h <= 0:
        return 1, 1
    ratio = min(max_w / src_w, max_h / src_h, 1.0)
    return max(int(src_w * ratio), 1), max(int(src_h * ratio), 1)


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def _bgra_to_png_base64(width: int, height: int, bgra: bytes) -> str:
    # Tk 在当前环境下无法稳定解析 data=PPM，因此改为标准 PNG 数据流。
    row_rgb_size = width * 3
    raw = bytearray(height * (row_rgb_size + 1))
    src = memoryview(bgra)
    dst = memoryview(raw)

    for row in range(height):
        dst_row = row * (row_rgb_size + 1)
        src_row = row * width * 4
        dst[dst_row] = 0  # PNG filter type 0
        rgb_row = dst[dst_row + 1: dst_row + 1 + row_rgb_size]
        bgra_row = src[src_row: src_row + width * 4]
        rgb_row[0::3] = bgra_row[2::4]
        rgb_row[1::3] = bgra_row[1::4]
        rgb_row[2::3] = bgra_row[0::4]

    png = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(
                b"IHDR",
                struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
            ),
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), 1)),
            _png_chunk(b"IEND", b""),
        ]
    )
    return base64.b64encode(png).decode("ascii")


def _capture_window_preview_data(
    hwnd: int,
    client_only: bool,
    max_width: int,
    max_height: int,
) -> tuple[str, int, int, int, int] | None:
    if not user32.IsWindow(hwnd):
        return None

    if client_only:
        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        src_width = rect.right - rect.left
        src_height = rect.bottom - rect.top
        pw_flags_candidates = [PW_CLIENTONLY, PW_RENDERFULLCONTENT, 0]
    else:
        rect = _get_window_rect(hwnd)
        src_width = rect.right - rect.left
        src_height = rect.bottom - rect.top
        pw_flags_candidates = [PW_RENDERFULLCONTENT, 0, PW_CLIENTONLY]

    if src_width <= 0 or src_height <= 0:
        return None

    dst_width, dst_height = _fit_size(src_width, src_height, max_width, max_height)

    screen_dc = user32.GetDC(0)
    src_dc = gdi32.CreateCompatibleDC(screen_dc)
    src_bmp = gdi32.CreateCompatibleBitmap(screen_dc, src_width, src_height)
    src_old = gdi32.SelectObject(src_dc, src_bmp)

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
        # 部分窗口不响应 PrintWindow，退回到窗口 DC 尝试直接位拷贝。
        hwnd_dc = user32.GetWindowDC(hwnd)
        if hwnd_dc:
            gdi32.BitBlt(src_dc, 0, 0, src_width, src_height, hwnd_dc, 0, 0, SRCCOPY)
            user32.ReleaseDC(hwnd, hwnd_dc)

    dst_dc = gdi32.CreateCompatibleDC(screen_dc)
    dst_bmp = gdi32.CreateCompatibleBitmap(screen_dc, dst_width, dst_height)
    dst_old = gdi32.SelectObject(dst_dc, dst_bmp)
    gdi32.SetStretchBltMode(dst_dc, HALFTONE)
    gdi32.StretchBlt(
        dst_dc,
        0,
        0,
        dst_width,
        dst_height,
        src_dc,
        0,
        0,
        src_width,
        src_height,
        SRCCOPY,
    )

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = dst_width
    bmi.biHeight = -dst_height
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = BI_RGB

    buf_size = dst_width * dst_height * 4
    buf = ctypes.create_string_buffer(buf_size)
    got = gdi32.GetDIBits(
        dst_dc,
        dst_bmp,
        0,
        dst_height,
        buf,
        ctypes.byref(bmi),
        DIB_RGB_COLORS,
    )

    gdi32.SelectObject(dst_dc, dst_old)
    gdi32.DeleteObject(dst_bmp)
    gdi32.DeleteDC(dst_dc)

    gdi32.SelectObject(src_dc, src_old)
    gdi32.DeleteObject(src_bmp)
    gdi32.DeleteDC(src_dc)
    user32.ReleaseDC(0, screen_dc)

    if got != dst_height:
        return None

    return (
        _bgra_to_png_base64(dst_width, dst_height, buf.raw),
        dst_width,
        dst_height,
        src_width,
        src_height,
    )


def _capture_screen_region_png(
    screen_x: int,
    screen_y: int,
    width: int,
    height: int,
) -> tuple[str, int, int] | None:
    if width <= 0 or height <= 0:
        return None

    screen_dc = user32.GetDC(0)
    if not screen_dc:
        return None

    src_dc = gdi32.CreateCompatibleDC(screen_dc)
    src_bmp = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    src_old = gdi32.SelectObject(src_dc, src_bmp)

    gdi32.BitBlt(
        src_dc,
        0,
        0,
        width,
        height,
        screen_dc,
        screen_x,
        screen_y,
        SRCCOPY,
    )

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

    gdi32.SelectObject(src_dc, src_old)
    gdi32.DeleteObject(src_bmp)
    gdi32.DeleteDC(src_dc)
    user32.ReleaseDC(0, screen_dc)

    if got != height:
        return None

    return _bgra_to_png_base64(width, height, buf.raw), width, height


# ─── GUI 应用 ─────────────────────────────────────────────────────────────────


class WindowCaptureApp:
    DWM_PREVIEW_SETTLE_MS = 40
    SAMPLE_PREVIEW_INTERVAL_MS = 180
    SAMPLE_PREVIEW_RETRY_INTERVAL_MS = 60
    SAMPLE_PREVIEW_MAX_WIDTH = 960
    SAMPLE_PREVIEW_MAX_HEIGHT = 540

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("窗口后台实时预览 (DWM Thumbnail)")
        self.root.geometry("1000x720")
        self.root.minsize(640, 480)
        self.root.configure(bg="#1e1e2e")

        self.thumbnail_id = HTHUMBNAIL()
        self.selected_hwnd: int | None = None
        self.hwnd_map: dict[str, int] = {}
        self.running = True
        self._configure_debounce_id: str | None = None
        self.debug_register_after_id: str | None = None
        self.saved_window_groups: dict[int, dict[int, WINDOWPLACEMENT]] = {}
        self.saved_window_styles: dict[int, dict[int, tuple[int, int]]] = {}
        self.saved_taskbar_exstyles: dict[int, dict[int, int]] = {}
        self.is_admin = _is_self_admin()
        self.dwm_preview_interval_ms = 0
        self.dwm_preview_interval_var = tk.StringVar(value="0")
        self.dwm_preview_after_id: str | None = None
        self.dwm_preview_capture_after_id: str | None = None
        self.dwm_preview_snapshot_image: tk.PhotoImage | None = None
        self.dwm_preview_live_visible = True
        self.dwm_preview_fail_streak = 0
        self.sample_preview_enabled = False
        self.sample_preview_after_id: str | None = None
        self.sample_preview_busy = False
        self.sample_preview_image: tk.PhotoImage | None = None
        self.sample_preview_fail_streak = 0
        self.sample_preview_interval_ms = self.SAMPLE_PREVIEW_INTERVAL_MS
        self.sample_preview_interval_var = tk.StringVar(
            value=f"{self.sample_preview_interval_ms / 1000:g}"
        )
        self.script_stop_event: threading.Event | None = None
        self.logic_task_specs = [
            ("shi_men", "师门任务", False),
            ("wa_bao_tu", "挖宝图", True),
            ("da_bao_tu", "打宝图", False),
            ("mi_jing_xiang_yao", "秘境降妖", False),
            ("zhua_gui", "抓鬼任务", False),
            ("fu_ben", "副本", False),
            ("yun_biao", "运镖", False),
            ("san_jie_qi_yuan", "三界奇缘", False),
            ("ke_ju_xiang_shi", "科举乡试", False),
            ("bang_pai_ren_wu", "帮派任务", False),
        ]
        self.logic_task_vars = {
            key: tk.BooleanVar(value=default)
            for key, _label, default in self.logic_task_specs
        }
        self.logic_option_specs = [
            ("zhua_gui_over_20", "超20抓鬼", False),
        ]
        self.logic_option_vars = {
            key: tk.BooleanVar(value=default)
            for key, _label, default in self.logic_option_specs
        }
        self.zhua_gui_rounds_var = tk.StringVar(value="0")
        self.logic_task_checkbuttons: list[ttk.Checkbutton] = []
        self.logic_option_checkbuttons: list[ttk.Checkbutton] = []
        self.window_resolution_width_var = tk.StringVar(value="800")
        self.window_resolution_height_var = tk.StringVar(value="600")
        self.preview_mapping: dict[str, int | bool | str] | None = None
        self.preview_marker: dict[str, int | bool] | None = None
        self.preview_marker_after_id: str | None = None
        self.preview_flash_marker: dict[str, int | bool | str] | None = None
        self.preview_flash_after_id: str | None = None
        self.pending_double_click_marker: tuple[int, int] | None = None
        self.preview_overlay_window: tk.Toplevel | None = None
        self.preview_overlay_canvas: tk.Canvas | None = None

        # Debug 放大镜
        self.debug_window: tk.Toplevel | None = None
        self.debug_thumbnail_id = HTHUMBNAIL()
        self.debug_canvas: tk.Canvas | None = None

        self._apply_style()
        self._build_ui()
        self.root.update_idletasks()
        self._refresh_window_list()
        self._sync_preview_overlay()

        self.root.bind("<Configure>", self._on_configure)

    # ── 获取顶层 Win32 HWND ──

    def _get_dest_hwnd(self) -> int:
        inner = self.root.winfo_id()
        top = user32.GetAncestor(inner, GA_ROOT)
        return top if top else inner

    def _ensure_preview_overlay(self):
        if self.preview_overlay_window and self.preview_overlay_window.winfo_exists():
            return

        transparent = "#00ff01"
        overlay = tk.Toplevel(self.root)
        overlay.withdraw()
        overlay.overrideredirect(True)
        overlay.transient(self.root)
        overlay.configure(bg=transparent)
        try:
            overlay.wm_attributes("-transparentcolor", transparent)
        except tk.TclError:
            pass

        canvas = tk.Canvas(
            overlay,
            bg=transparent,
            highlightthickness=0,
            bd=0,
            cursor="crosshair",
        )
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.bind("<Button-1>", self._on_preview_click)

        self.preview_overlay_window = overlay
        self.preview_overlay_canvas = canvas

    def _sync_preview_overlay(self):
        self._ensure_preview_overlay()
        if not self.preview_overlay_window or not self.preview_overlay_canvas:
            return

        if not self.root.winfo_viewable() or self.root.state() == "iconic":
            self.preview_overlay_window.withdraw()
            return

        self.display_area.update_idletasks()
        width = self.display_area.winfo_width()
        height = self.display_area.winfo_height()
        if width <= 1 or height <= 1:
            self.preview_overlay_window.withdraw()
            return

        x = self.display_area.winfo_rootx()
        y = self.display_area.winfo_rooty()
        self.preview_overlay_window.geometry(f"{width}x{height}+{x}+{y}")
        self.preview_overlay_window.deiconify()
        self.preview_overlay_window.lift(self.root)
        self._redraw_preview_marker()

    def _destroy_preview_overlay(self):
        if self.preview_overlay_window and self.preview_overlay_window.winfo_exists():
            self.preview_overlay_window.destroy()
        self.preview_overlay_window = None
        self.preview_overlay_canvas = None

    # ── 样式 ──

    def _apply_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        bg = "#1e1e2e"
        fg = "#cdd6f4"
        accent = "#89b4fa"
        surface = "#313244"
        btn_bg = "#45475a"

        style.configure(".", background=bg, foreground=fg, fieldbackground=surface)
        style.configure("TLabel", background=bg, foreground=fg,
                         font=("Microsoft YaHei UI", 10))
        style.configure("TButton", background=btn_bg, foreground=fg, padding=(12, 6),
                         font=("Microsoft YaHei UI", 9))
        style.map("TButton",
                  background=[("active", accent), ("pressed", accent)],
                  foreground=[("active", "#1e1e2e"), ("pressed", "#1e1e2e")])
        style.configure(
            "Toolbar.TButton",
            background=btn_bg,
            foreground=fg,
            padding=(6, 4),
            font=("Microsoft YaHei UI", 9),
        )
        style.map("Toolbar.TButton",
                  background=[("active", accent), ("pressed", accent)],
                  foreground=[("active", "#1e1e2e"), ("pressed", "#1e1e2e")])
        style.configure("TCombobox", fieldbackground=surface, foreground=fg,
                         selectbackground=accent, selectforeground="#1e1e2e",
                         padding=6)
        style.configure("TCheckbutton", background=bg, foreground=fg,
                         font=("Microsoft YaHei UI", 9))
        style.configure("Status.TLabel", background=surface, foreground=accent,
                         font=("Microsoft YaHei UI", 9), padding=(10, 6))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 13, "bold"),
                         foreground=accent)

    # ── 构建 UI ──

    def _build_ui(self):
        title_frame = ttk.Frame(self.root)
        title_frame.pack(fill=tk.X, padx=16, pady=(14, 4))
        ttk.Label(title_frame, text="窗口后台实时预览",
                  style="Title.TLabel").pack(side=tk.LEFT)
        admin_text = "管理员权限" if self.is_admin else "普通权限"
        admin_color = "#a6e3a1" if self.is_admin else "#f9e2af"
        tk.Label(
            title_frame,
            text=f"当前权限: {admin_text}",
            bg="#1e1e2e",
            fg=admin_color,
            font=("Microsoft YaHei UI", 9),
        ).pack(side=tk.LEFT, padx=(12, 8))
        self.admin_restart_btn = ttk.Button(
            title_frame,
            text="管理员重启",
            command=self._restart_as_admin,
        )
        self.admin_restart_btn.pack(side=tk.RIGHT)
        if self.is_admin:
            self.admin_restart_btn.state(["disabled"])

        select_frame = ttk.Frame(self.root)
        select_frame.pack(fill=tk.X, padx=16, pady=6)
        ttk.Label(select_frame, text="目标窗口:").pack(side=tk.LEFT)
        self.window_combo = ttk.Combobox(select_frame, width=55, state="readonly")
        self.window_combo.pack(side=tk.LEFT, padx=8, expand=True, fill=tk.X)

        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=16, pady=(0, 6))
        ttk.Button(btn_frame, text="刷新列表", style="Toolbar.TButton",
                   command=self._refresh_window_list).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="锚定窗口", style="Toolbar.TButton",
                   command=self._anchor_window).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="取消锚定", style="Toolbar.TButton",
                   command=self._unanchor).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="转后台保活", style="Toolbar.TButton",
                   command=self._move_selected_offscreen).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="强制窗口化", style="Toolbar.TButton",
                   command=self._force_selected_windowed).pack(side=tk.LEFT, padx=(0, 6))
        self.taskbar_toggle_btn_text = tk.StringVar(value="任务栏图标: 隐藏")
        ttk.Button(btn_frame, textvariable=self.taskbar_toggle_btn_text, style="Toolbar.TButton",
                   command=self._toggle_selected_taskbar_icon).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="恢复原位", style="Toolbar.TButton",
                   command=self._restore_selected_window).pack(side=tk.LEFT, padx=(0, 6))
        self.sample_preview_btn_text = tk.StringVar(value="开启采样预览")
        ttk.Button(btn_frame, textvariable=self.sample_preview_btn_text, style="Toolbar.TButton",
                   command=self._toggle_sample_preview).pack(side=tk.LEFT, padx=(12, 0))

        preview_control_frame = ttk.Frame(self.root)
        preview_control_frame.pack(fill=tk.X, padx=16, pady=(0, 6))

        ttk.Label(preview_control_frame, text="主预览间隔").pack(side=tk.LEFT)
        self.dwm_preview_interval_entry = ttk.Entry(
            preview_control_frame,
            textvariable=self.dwm_preview_interval_var,
            width=5,
        )
        self.dwm_preview_interval_entry.pack(side=tk.LEFT, padx=(6, 0))
        self.dwm_preview_interval_entry.bind(
            "<Return>", self._on_dwm_preview_interval_commit
        )
        self.dwm_preview_interval_entry.bind(
            "<FocusOut>", self._on_dwm_preview_interval_commit
        )
        ttk.Label(preview_control_frame, text="秒 (0=实时)").pack(side=tk.LEFT, padx=(2, 14))

        ttk.Label(preview_control_frame, text="采样间隔").pack(side=tk.LEFT, padx=(0, 2))
        self.sample_preview_interval_entry = ttk.Entry(
            preview_control_frame,
            textvariable=self.sample_preview_interval_var,
            width=5,
        )
        self.sample_preview_interval_entry.pack(side=tk.LEFT)
        self.sample_preview_interval_entry.bind(
            "<Return>", self._on_sample_preview_interval_commit
        )
        self.sample_preview_interval_entry.bind(
            "<FocusOut>", self._on_sample_preview_interval_commit
        )
        ttk.Label(preview_control_frame, text="秒").pack(side=tk.LEFT, padx=(2, 12))

        self.client_only_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(preview_control_frame, text="仅客户区 (隐藏标题栏)",
                         variable=self.client_only_var,
                         command=self._on_client_only_toggle).pack(side=tk.LEFT, padx=12)

        resolution_frame = ttk.Frame(self.root)
        resolution_frame.pack(fill=tk.X, padx=16, pady=(0, 6))
        ttk.Label(resolution_frame, text="目标分辨率").pack(side=tk.LEFT)
        ttk.Entry(
            resolution_frame,
            textvariable=self.window_resolution_width_var,
            width=5,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(resolution_frame, text="x").pack(side=tk.LEFT, padx=(4, 4))
        ttk.Entry(
            resolution_frame,
            textvariable=self.window_resolution_height_var,
            width=5,
        ).pack(side=tk.LEFT)
        ttk.Button(
            resolution_frame,
            text="设置分辨率",
            style="Toolbar.TButton",
            command=self._set_selected_window_resolution,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(
            resolution_frame,
            text="← 调整当前锚定窗口的客户区尺寸，默认 800x600",
            font=("Microsoft YaHei UI", 8),
        ).pack(side=tk.LEFT, padx=(8, 0))

        # 脚本执行区域
        script_frame = ttk.Frame(self.root)
        script_frame.pack(fill=tk.X, padx=16, pady=(0, 6))

        self.run_script_btn = ttk.Button(
            script_frame, text="执行脚本", command=self._run_script
        )
        self.run_script_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.stop_script_btn = ttk.Button(
            script_frame, text="终止脚本", command=self._stop_script
        )
        self.stop_script_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.stop_script_btn.state(["disabled"])

        ttk.Label(script_frame, text="← 运行 game_logic.py（每次自动热重载）",
                  font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT)

        logic_frame = ttk.Frame(self.root)
        logic_frame.pack(fill=tk.X, padx=16, pady=(0, 6))
        ttk.Label(logic_frame, text="功能块").pack(side=tk.LEFT)
        for key, label, _default in self.logic_task_specs:
            check = ttk.Checkbutton(
                logic_frame,
                text=label,
                variable=self.logic_task_vars[key],
            )
            check.pack(side=tk.LEFT, padx=(8, 0))
            self.logic_task_checkbuttons.append(check)
        ttk.Label(logic_frame, text=" | 选项").pack(side=tk.LEFT, padx=(12, 0))
        for key, label, _default in self.logic_option_specs:
            check = ttk.Checkbutton(
                logic_frame,
                text=label,
                variable=self.logic_option_vars[key],
            )
            check.pack(side=tk.LEFT, padx=(8, 0))
            self.logic_option_checkbuttons.append(check)
        ttk.Label(logic_frame, text="抓鬼轮数").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Entry(
            logic_frame,
            textvariable=self.zhua_gui_rounds_var,
            width=4,
        ).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(
            logic_frame,
            text="(0=不限)",
            font=("Microsoft YaHei UI", 8),
        ).pack(side=tk.LEFT, padx=(2, 0))

        # Debug 放大镜
        debug_frame = ttk.Frame(self.root)
        debug_frame.pack(fill=tk.X, padx=16, pady=(0, 6))

        ttk.Label(debug_frame, text="Debug 坐标:").pack(side=tk.LEFT)
        ttk.Label(debug_frame, text="X").pack(side=tk.LEFT, padx=(8, 2))
        self.debug_x_var = tk.StringVar(value="350")
        ttk.Entry(debug_frame, textvariable=self.debug_x_var,
                  width=6).pack(side=tk.LEFT)
        ttk.Label(debug_frame, text="Y").pack(side=tk.LEFT, padx=(8, 2))
        self.debug_y_var = tk.StringVar(value="375")
        ttk.Entry(debug_frame, textvariable=self.debug_y_var,
                  width=6).pack(side=tk.LEFT)

        ttk.Label(debug_frame, text="区域").pack(side=tk.LEFT, padx=(8, 2))
        self.debug_size_var = tk.StringVar(value="50")
        ttk.Entry(debug_frame, textvariable=self.debug_size_var,
                  width=4).pack(side=tk.LEFT)
        ttk.Label(debug_frame, text="px").pack(side=tk.LEFT, padx=(0, 8))

        self.debug_click_btn = ttk.Button(
            debug_frame,
            text="Debug 点击",
            command=self._debug_click,
        )
        self.debug_click_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.debug_robust_click_btn = ttk.Button(
            debug_frame,
            text="强力点击回退",
            command=self._debug_robust_click,
        )
        self.debug_robust_click_btn.pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(debug_frame, text="Debug 放大镜",
                   command=self._open_debug_view).pack(side=tk.LEFT, padx=(0, 6))

        # 预览区域 — DWM 会直接在这个区域内合成目标窗口画面
        self.display_border = tk.Frame(self.root, bg="#45475a", padx=2, pady=2)
        self.display_border.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 6))

        self.display_area = tk.Canvas(self.display_border, bg="#181825",
                                       highlightthickness=0, cursor="crosshair")
        self.display_area.pack(fill=tk.BOTH, expand=True)
        self.display_area.bind("<Button-1>", self._on_preview_click)

        # 诊断日志区域（可折叠）
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill=tk.X, padx=16, pady=(0, 4))
        self.log_text = tk.Text(
            log_frame, height=6, bg="#11111b", fg="#a6adc8",
            font=("Consolas", 9), wrap=tk.WORD,
            highlightthickness=1, highlightcolor="#45475a",
            highlightbackground="#313244", insertbackground="#cdd6f4"
        )
        self.log_text.pack(fill=tk.X)
        self.log_text.insert("1.0", "诊断日志将显示在这里...\n")
        self.log_text.configure(state=tk.DISABLED)

        self.status_var = tk.StringVar(value="请选择一个窗口并点击「锚定窗口」")
        ttk.Label(self.root, textvariable=self.status_var,
                  style="Status.TLabel").pack(fill=tk.X, padx=16, pady=(0, 10))

    # ── 窗口列表 ──

    def _refresh_window_list(self):
        windows = get_window_list()
        own_hwnd = self._get_dest_hwnd()

        display_list = []
        self.hwnd_map.clear()
        for hwnd, title in windows:
            if hwnd == own_hwnd:
                continue
            label = f"[{hwnd:#010x}]  {title}"
            display_list.append(label)
            self.hwnd_map[label] = hwnd

        self.window_combo["values"] = display_list
        if display_list and not self.window_combo.get():
            self.window_combo.current(0)
        self.status_var.set(f"已刷新，共找到 {len(display_list)} 个窗口")

    # ── 锚定 / 取消锚定 ──

    def _anchor_window(self):
        selection = self.window_combo.get()
        if not selection:
            self.status_var.set("请先从下拉列表中选择一个窗口")
            return

        seed_hwnd = self.hwnd_map.get(selection)
        if not seed_hwnd or not user32.IsWindow(seed_hwnd):
            self.status_var.set("窗口无效，请刷新列表后重试")
            return

        resolved_hwnd, candidates = _resolve_best_process_window(seed_hwnd)
        self._clear_log()
        self._clear_preview_marker(clear_state=True)
        self._reset_virtual_click_preview_state()
        self._append_log(f"用户选择句柄: {seed_hwnd:#010x}  {selection}")
        if candidates:
            self._append_log("同进程候选窗口（按面积降序）:")
            for index, (hwnd, area, cls, title, rect) in enumerate(candidates[:8], 1):
                self._append_log(
                    f"  [{index}] hwnd={hwnd:#010x} area={area} class={cls!r} "
                    f"title={title!r} rect=({rect.left},{rect.top},{rect.right},{rect.bottom})"
                )
        if resolved_hwnd != seed_hwnd:
            self._append_log(
                f"已自动切换到同进程更大的目标句柄: {resolved_hwnd:#010x} "
                f"class={_get_class_name(resolved_hwnd)!r} title={_get_window_text(resolved_hwnd)!r}"
            )
        else:
            self._append_log("当前选中句柄已被视为最佳候选。")

        self.selected_hwnd = resolved_hwnd

        self._unregister_thumbnail()
        hr = self._register_thumbnail()
        if hr != 0:
            self.status_var.set(
                f"DWM 注册缩略图失败 (HRESULT=0x{hr & 0xFFFFFFFF:08X})")
            self.thumbnail_id = HTHUMBNAIL()
            return

        self._update_thumbnail_layout()

        src_size = wintypes.SIZE()
        dwmapi.DwmQueryThumbnailSourceSize(
            self.thumbnail_id, ctypes.byref(src_size)
        )
        self.status_var.set(
            f"已锚定  |  实际句柄 {resolved_hwnd:#010x}  |  源窗口分辨率 {src_size.cx}×{src_size.cy}"
        )
        self._append_log("如目标是游戏，建议点击“转后台保活”，不要再手动最小化。")
        self._update_taskbar_toggle_button_text()
        self._refresh_sample_preview_now()
        self._restart_dwm_preview_mode(immediate=True)

    def _unanchor(self):
        if self.sample_preview_enabled:
            self._stop_sample_preview("已关闭采样预览（因取消锚定）")
        self._cancel_dwm_preview_jobs()
        self._clear_dwm_preview_snapshot()
        self.dwm_preview_live_visible = True
        self._unregister_thumbnail()
        self.selected_hwnd = None
        self.preview_mapping = None
        self.display_area.delete("all")
        self._clear_preview_marker(clear_state=True)
        self._reset_virtual_click_preview_state()
        self.status_var.set("已取消锚定")
        self._update_taskbar_toggle_button_text()

    def _unregister_thumbnail(self):
        if self.thumbnail_id.value:
            dwmapi.DwmUnregisterThumbnail(self.thumbnail_id)
            self.thumbnail_id = HTHUMBNAIL()

    def _register_thumbnail(self) -> int:
        if self.thumbnail_id.value:
            return 0
        if not self.selected_hwnd or not user32.IsWindow(self.selected_hwnd):
            return 0x80004005

        dest_hwnd = self._get_dest_hwnd()
        hr = dwmapi.DwmRegisterThumbnail(
            dest_hwnd, self.selected_hwnd, ctypes.byref(self.thumbnail_id)
        )
        if hr != 0:
            self.thumbnail_id = HTHUMBNAIL()
        return hr

    def _update_taskbar_toggle_button_text(self):
        if not self.selected_hwnd or not user32.IsWindow(self.selected_hwnd):
            self.taskbar_toggle_btn_text.set("任务栏图标: 隐藏")
            return
        pid = _get_pid(self.selected_hwnd)
        hidden = bool(self.saved_taskbar_exstyles.get(pid))
        self.taskbar_toggle_btn_text.set(
            "任务栏图标: 显示" if hidden else "任务栏图标: 隐藏"
        )

    def _get_preview_source_metrics(self, client_only: bool) -> dict[str, int | bool] | None:
        if not self.selected_hwnd or not user32.IsWindow(self.selected_hwnd):
            return None

        client_rect = _get_client_rect(self.selected_hwnd)
        client_width = client_rect.right - client_rect.left
        client_height = client_rect.bottom - client_rect.top
        client_offset_x, client_offset_y = _get_client_offset_in_window(self.selected_hwnd)

        if client_only:
            source_width = client_width
            source_height = client_height
        else:
            window_rect = _get_window_rect(self.selected_hwnd)
            source_width = window_rect.right - window_rect.left
            source_height = window_rect.bottom - window_rect.top

        if source_width <= 0 or source_height <= 0:
            return None

        return {
            "client_only": client_only,
            "source_width": source_width,
            "source_height": source_height,
            "client_width": client_width,
            "client_height": client_height,
            "client_offset_x": client_offset_x,
            "client_offset_y": client_offset_y,
        }

    def _set_preview_mapping(
        self,
        mode: str,
        dest_left: int,
        dest_top: int,
        dest_width: int,
        dest_height: int,
        source_metrics: dict[str, int | bool] | None,
    ):
        if not source_metrics:
            self.preview_mapping = None
            self._redraw_preview_marker()
            return

        self.preview_mapping = {
            "mode": mode,
            "dest_left": dest_left,
            "dest_top": dest_top,
            "dest_width": dest_width,
            "dest_height": dest_height,
            **source_metrics,
        }
        self._redraw_preview_marker()

    def _clear_preview_marker(
        self,
        clear_state: bool = False,
        *,
        cancel_timer: bool = True,
    ):
        if self.preview_overlay_canvas:
            self.preview_overlay_canvas.delete("preview_marker")
        if cancel_timer and self.preview_marker_after_id:
            try:
                self.root.after_cancel(self.preview_marker_after_id)
            except Exception:
                pass
            self.preview_marker_after_id = None
        if clear_state:
            self.preview_marker = None

    def _clear_preview_flash_marker(
        self,
        clear_state: bool = False,
        *,
        cancel_timer: bool = True,
    ):
        if self.preview_overlay_canvas:
            self.preview_overlay_canvas.delete("preview_flash_marker")
        if cancel_timer and self.preview_flash_after_id:
            try:
                self.root.after_cancel(self.preview_flash_after_id)
            except Exception:
                pass
            self.preview_flash_after_id = None
        if clear_state:
            self.preview_flash_marker = None

    def _reset_virtual_click_preview_state(self):
        self.pending_double_click_marker = None
        self._clear_preview_flash_marker(clear_state=True)

    def _expire_preview_flash_marker(self):
        self.preview_flash_after_id = None
        self._clear_preview_flash_marker(clear_state=True, cancel_timer=False)

    def _expire_preview_marker(self):
        self.preview_marker_after_id = None
        self._clear_preview_marker(clear_state=True, cancel_timer=False)

    def _copy_coords_to_clipboard(self, label: str, x: int, y: int) -> bool:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(f"{label}_X = {x}\n{label}_Y = {y}")
            return True
        except tk.TclError:
            return False

    def _redraw_preview_marker(self):
        self._clear_preview_marker(clear_state=False, cancel_timer=False)
        self._clear_preview_flash_marker(clear_state=False, cancel_timer=False)
        if not self.preview_overlay_canvas or not self.preview_mapping:
            return

        if self.preview_marker:
            self._draw_preview_marker(
                self.preview_marker,
                tag="preview_marker",
                line_color="#f38ba8",
                accent_color="#fab387",
                text_color="#cdd6f4",
            )
        if self.preview_flash_marker:
            self._draw_preview_marker(
                self.preview_flash_marker,
                tag="preview_flash_marker",
                line_color="#94e2d5",
                accent_color="#a6e3a1",
                text_color="#cdd6f4",
            )

    def _draw_preview_marker(
        self,
        marker: dict[str, int | bool | str],
        *,
        tag: str,
        line_color: str,
        accent_color: str,
        text_color: str,
    ):
        if not self.preview_overlay_canvas or not self.preview_mapping:
            return

        mapping = self.preview_mapping
        dest_left = int(mapping["dest_left"])
        dest_top = int(mapping["dest_top"])
        dest_width = max(int(mapping["dest_width"]), 1)
        dest_height = max(int(mapping["dest_height"]), 1)
        dest_right = dest_left + dest_width
        dest_bottom = dest_top + dest_height

        if bool(mapping["client_only"]):
            if not bool(marker["inside_client"]):
                return
            source_x = int(marker["client_x"])
            source_y = int(marker["client_y"])
        else:
            source_x = int(marker["window_x"])
            source_y = int(marker["window_y"])

        source_width = max(int(mapping["source_width"]), 1)
        source_height = max(int(mapping["source_height"]), 1)

        canvas_x = dest_left + round((source_x + 0.5) * dest_width / source_width)
        canvas_y = dest_top + round((source_y + 0.5) * dest_height / source_height)
        canvas_x = min(max(canvas_x, dest_left), dest_right - 1)
        canvas_y = min(max(canvas_y, dest_top), dest_bottom - 1)

        canvas = self.preview_overlay_canvas
        canvas.create_line(
            dest_left,
            canvas_y,
            dest_right,
            canvas_y,
            fill=line_color,
            width=1,
            dash=(6, 4),
            tags=tag,
        )
        canvas.create_line(
            canvas_x,
            dest_top,
            canvas_x,
            dest_bottom,
            fill=line_color,
            width=1,
            dash=(6, 4),
            tags=tag,
        )
        canvas.create_oval(
            canvas_x - 5,
            canvas_y - 5,
            canvas_x + 5,
            canvas_y + 5,
            outline=accent_color,
            width=2,
            tags=tag,
        )

        label_prefix = str(
            marker.get("label_prefix")
            or ("C" if bool(marker["inside_client"]) else "W")
        )
        if bool(marker["inside_client"]):
            label = f"{label_prefix}({int(marker['client_x'])}, {int(marker['client_y'])})"
        else:
            label = f"{label_prefix}({int(marker['window_x'])}, {int(marker['window_y'])})"

        text_id = canvas.create_text(
            canvas_x + 12,
            canvas_y + 12,
            text=label,
            fill=text_color,
            font=("Consolas", 9, "bold"),
            anchor="nw",
            tags=tag,
        )
        bbox = canvas.bbox(text_id)
        if bbox:
            shift_x = 0
            shift_y = 0
            if bbox[2] > dest_right - 4:
                shift_x = (dest_right - 4) - bbox[2]
            if bbox[3] > dest_bottom - 4:
                shift_y = (dest_bottom - 4) - bbox[3]
            if bbox[0] + shift_x < dest_left + 4:
                shift_x = (dest_left + 4) - bbox[0]
            if bbox[1] + shift_y < dest_top + 4:
                shift_y = (dest_top + 4) - bbox[1]
            if shift_x or shift_y:
                canvas.move(text_id, shift_x, shift_y)
                bbox = canvas.bbox(text_id)
        if bbox:
            rect_id = canvas.create_rectangle(
                bbox[0] - 4,
                bbox[1] - 2,
                bbox[2] + 4,
                bbox[3] + 2,
                fill="#11111b",
                outline=line_color,
                width=1,
                tags=tag,
            )
            canvas.tag_raise(text_id, rect_id)

    def _show_virtual_click_marker(self, client_x: int, client_y: int, *, label_prefix: str):
        if not self.preview_mapping:
            return

        client_offset_x = int(self.preview_mapping["client_offset_x"])
        client_offset_y = int(self.preview_mapping["client_offset_y"])
        self._clear_preview_flash_marker(clear_state=False)
        self.preview_flash_marker = {
            "window_x": client_x + client_offset_x,
            "window_y": client_y + client_offset_y,
            "client_x": client_x,
            "client_y": client_y,
            "inside_client": True,
            "label_prefix": label_prefix,
        }
        self._redraw_preview_marker()
        self.preview_flash_after_id = self.root.after(
            PREVIEW_VIRTUAL_CLICK_FLASH_MS,
            self._expire_preview_flash_marker,
        )

    def _handle_virtual_click_log(self, msg: str):
        text = msg.strip()
        click_match = VIRTUAL_CLICK_LOG_RE.match(text)
        if click_match:
            action = click_match.group("action")
            client_x = int(click_match.group("x"))
            client_y = int(click_match.group("y"))
            if action == "双击":
                self.pending_double_click_marker = (client_x, client_y)
                return

            self.pending_double_click_marker = None
            label_prefix = "L" if action == "单击" else "R"
            self._show_virtual_click_marker(
                client_x,
                client_y,
                label_prefix=label_prefix,
            )
            return

        step_match = DOUBLE_CLICK_STEP_LOG_RE.match(text)
        if step_match and self.pending_double_click_marker:
            client_x, client_y = self.pending_double_click_marker
            step_index = int(step_match.group("index"))
            self._show_virtual_click_marker(
                client_x,
                client_y,
                label_prefix=f"D{step_index}",
            )
            if step_index >= 2:
                self.pending_double_click_marker = None

    def _handle_preview_click_result(self, mapping: dict[str, int | bool | str], px: int, py: int):
        dest_left = int(mapping["dest_left"])
        dest_top = int(mapping["dest_top"])
        dest_width = max(int(mapping["dest_width"]), 1)
        dest_height = max(int(mapping["dest_height"]), 1)

        if not (dest_left <= px < dest_left + dest_width and dest_top <= py < dest_top + dest_height):
            self.status_var.set("点击位置不在预览画面内")
            return

        rel_x = (px - dest_left) / dest_width
        rel_y = (py - dest_top) / dest_height
        source_width = max(int(mapping["source_width"]), 1)
        source_height = max(int(mapping["source_height"]), 1)
        source_x = min(max(int(rel_x * source_width), 0), source_width - 1)
        source_y = min(max(int(rel_y * source_height), 0), source_height - 1)
        client_offset_x = int(mapping["client_offset_x"])
        client_offset_y = int(mapping["client_offset_y"])
        client_width = int(mapping["client_width"])
        client_height = int(mapping["client_height"])

        if bool(mapping["client_only"]):
            client_x = source_x
            client_y = source_y
            window_x = client_x + client_offset_x
            window_y = client_y + client_offset_y
            inside_client = True
        else:
            window_x = source_x
            window_y = source_y
            client_x = source_x - client_offset_x
            client_y = source_y - client_offset_y
            inside_client = 0 <= client_x < client_width and 0 <= client_y < client_height

        self.preview_marker = {
            "window_x": window_x,
            "window_y": window_y,
            "client_x": client_x,
            "client_y": client_y,
            "inside_client": inside_client,
        }
        self._redraw_preview_marker()
        if self.preview_marker_after_id:
            try:
                self.root.after_cancel(self.preview_marker_after_id)
            except Exception:
                pass
        self.preview_marker_after_id = self.root.after(
            PREVIEW_CLICK_MARKER_VISIBLE_MS,
            self._expire_preview_marker,
        )

        if inside_client:
            self.debug_x_var.set(str(client_x))
            self.debug_y_var.set(str(client_y))
            copied = self._copy_coords_to_clipboard("TARGET", client_x, client_y)
            if bool(mapping["client_only"]):
                message = (
                    f"预览点击 -> 客户区坐标 ({client_x}, {client_y})，"
                    f"已回填到 Debug 输入框{'，并已复制到剪贴板' if copied else '，但复制到剪贴板失败'}"
                )
            else:
                message = (
                    f"预览点击 -> 窗口坐标 ({window_x}, {window_y})，客户区坐标 ({client_x}, {client_y})，"
                    f"已回填到 Debug 输入框{'，并已复制到剪贴板' if copied else '，但复制到剪贴板失败'}"
                )
            self._append_log(message)
            self.status_var.set(message)
            return

        message = (
            f"预览点击 -> 窗口坐标 ({window_x}, {window_y})；该点不在客户区内，"
            "未回填 Debug，也未复制脚本坐标"
        )
        self._append_log(message)
        self.status_var.set(
            f"点击位于非客户区：窗口({window_x}, {window_y})，客户区({client_x}, {client_y})"
        )

    def _on_preview_click(self, event):
        if not self.selected_hwnd:
            self.status_var.set("请先锚定一个窗口")
            return
        if not self.preview_mapping:
            self.status_var.set("当前没有可用的预览映射信息")
            return
        self._handle_preview_click_result(self.preview_mapping, event.x, event.y)
        self.root.focus_force()

    # ── 目标窗口后台运行模式 ──

    def _clone_placement(self, placement: WINDOWPLACEMENT) -> WINDOWPLACEMENT:
        cloned = WINDOWPLACEMENT()
        ctypes.memmove(
            ctypes.byref(cloned),
            ctypes.byref(placement),
            ctypes.sizeof(WINDOWPLACEMENT),
        )
        return cloned

    def _get_window_placement(self, hwnd: int) -> WINDOWPLACEMENT | None:
        placement = WINDOWPLACEMENT()
        placement.length = ctypes.sizeof(WINDOWPLACEMENT)
        if not user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
            return None
        return placement

    def _set_selected_window_resolution(self):
        if not self.selected_hwnd:
            self.status_var.set("请先锚定一个窗口")
            return
        if not user32.IsWindow(self.selected_hwnd):
            self.status_var.set("目标窗口已关闭，请重新选择")
            self.selected_hwnd = None
            return

        raw_width = self.window_resolution_width_var.get().strip()
        raw_height = self.window_resolution_height_var.get().strip()
        try:
            target_client_width = int(raw_width)
            target_client_height = int(raw_height)
        except ValueError:
            self.status_var.set("分辨率无效，请输入整数，例如 800 x 600")
            return

        if target_client_width <= 0 or target_client_height <= 0:
            self.status_var.set("分辨率必须大于 0")
            return

        self.window_resolution_width_var.set(str(target_client_width))
        self.window_resolution_height_var.set(str(target_client_height))

        hwnd = self.selected_hwnd
        pid = _get_pid(hwnd)
        self_admin = _is_self_admin()
        target_admin = _is_process_elevated(pid)
        self._append_log(
            f"设置分辨率诊断: self_admin={'是' if self_admin else '否'} "
            f"target_admin={'是' if target_admin else '否' if target_admin is not None else '未知'} "
            f"pid={pid}"
        )
        if target_admin and not self_admin:
            self._append_log("⚠ 当前程序不是管理员，而目标进程是管理员。尺寸调整可能被 UIPI 拒绝。")

        placement = self._get_window_placement(hwnd)
        saved_group = self.saved_window_groups.setdefault(pid, {})
        if placement and hwnd not in saved_group:
            saved_group[hwnd] = self._clone_placement(placement)

        before_window = _get_window_rect(hwnd)
        before_client = _get_client_rect(hwnd)
        before_client_width = before_client.right - before_client.left
        before_client_height = before_client.bottom - before_client.top

        target_window_width, target_window_height = _get_window_outer_size_for_client(
            hwnd,
            target_client_width,
            target_client_height,
        )

        target_left = before_window.left
        target_top = before_window.top
        if placement:
            normal = placement.rcNormalPosition
            if normal.right > normal.left and normal.bottom > normal.top:
                target_left = normal.left
                target_top = normal.top

        kernel32.SetLastError(0)
        show_res = user32.ShowWindow(hwnd, SW_RESTORE)
        show_err = kernel32.GetLastError()

        kernel32.SetLastError(0)
        pos_res = user32.SetWindowPos(
            hwnd,
            0,
            target_left,
            target_top,
            target_window_width,
            target_window_height,
            SWP_NOZORDER | SWP_NOACTIVATE,
        )
        pos_err = kernel32.GetLastError()

        after_window = _get_window_rect(hwnd)
        after_client = _get_client_rect(hwnd)
        after_window_width = after_window.right - after_window.left
        after_window_height = after_window.bottom - after_window.top
        after_client_width = after_client.right - after_client.left
        after_client_height = after_client.bottom - after_client.top

        self._append_log(
            f"设置分辨率 hwnd={hwnd:#010x} "
            f"request_client={target_client_width}x{target_client_height} "
            f"target_window={target_window_width}x{target_window_height} "
            f"before_client={before_client_width}x{before_client_height} "
            f"after_client={after_client_width}x{after_client_height} "
            f"after_window={after_window_width}x{after_window_height} "
            f"show={show_res}/err={show_err} setpos={pos_res}/err={pos_err}"
        )
        if show_err:
            self._append_log(f"  ShowWindow error: {_format_win32_error(show_err)}")
        if pos_err:
            self._append_log(f"  SetWindowPos error: {_format_win32_error(pos_err)}")

        client_matched = (
            abs(after_client_width - target_client_width) <= 2
            and abs(after_client_height - target_client_height) <= 2
        )
        if pos_res and client_matched:
            self.status_var.set(
                f"已设置目标客户区为 {after_client_width}x{after_client_height}"
            )
        elif pos_res:
            self.status_var.set(
                f"已尝试设置为 {target_client_width}x{target_client_height}，"
                f"实际客户区 {after_client_width}x{after_client_height}"
            )
        else:
            self.status_var.set("设置分辨率未生效")

        if self.sample_preview_enabled:
            self._refresh_sample_preview_now()
        else:
            self._restart_dwm_preview_mode(immediate=True)

    def _move_selected_offscreen(self):
        if not self.selected_hwnd:
            self.status_var.set("请先锚定一个窗口")
            return
        if not user32.IsWindow(self.selected_hwnd):
            self.status_var.set("目标窗口已关闭，请重新选择")
            self.selected_hwnd = None
            return

        hwnd = self.selected_hwnd
        pid = _get_pid(hwnd)
        self_admin = _is_self_admin()
        target_admin = _is_process_elevated(pid)
        self._append_log(
            f"后台运行诊断: self_admin={'是' if self_admin else '否'} "
            f"target_admin={'是' if target_admin else '否' if target_admin is not None else '未知'} "
            f"pid={pid}"
        )
        if target_admin and not self_admin:
            self._append_log("⚠ 当前程序不是管理员，而目标进程是管理员。窗口管理与输入注入都可能被 UIPI 拒绝。")

        targets = _enum_process_windows(pid)
        if hwnd not in targets:
            targets.insert(0, hwnd)

        group: dict[int, WINDOWPLACEMENT] = {}
        parked_count = 0

        if not targets:
            self.status_var.set("未找到可移动的目标窗口")
            return

        for index, target in enumerate(targets, 1):
            placement = self._get_window_placement(target)
            if not placement:
                continue

            group[target] = self._clone_placement(placement)

            before_rect = _get_window_rect(target)
            normal = placement.rcNormalPosition
            width = max(before_rect.right - before_rect.left, normal.right - normal.left, 200)
            height = max(before_rect.bottom - before_rect.top, normal.bottom - normal.top, 200)

            parked_rect = _calc_keepalive_rect(width, height)
            offscreen = self._clone_placement(placement)
            offscreen.showCmd = SW_SHOWNOACTIVATE
            offscreen.rcNormalPosition.left = parked_rect.left
            offscreen.rcNormalPosition.top = parked_rect.top
            offscreen.rcNormalPosition.right = parked_rect.right
            offscreen.rcNormalPosition.bottom = parked_rect.bottom

            kernel32.SetLastError(0)
            show_res = user32.ShowWindow(target, SW_RESTORE)
            show_err = kernel32.GetLastError()

            kernel32.SetLastError(0)
            placement_res = user32.SetWindowPlacement(target, ctypes.byref(offscreen))
            placement_err = kernel32.GetLastError()

            kernel32.SetLastError(0)
            pos_res = user32.SetWindowPos(
                target,
                0,
                parked_rect.left,
                parked_rect.top,
                width,
                height,
                SWP_NOZORDER | SWP_NOACTIVATE,
            )
            pos_err = kernel32.GetLastError()

            after_rect = _get_window_rect(target)
            parked = _is_keepalive_parked(after_rect)
            if parked:
                parked_count += 1

            title = _get_window_text(target) or "<无标题>"
            self._append_log(
                f"后台运行[{index}] hwnd={target:#010x} title={title!r} "
                f"before=({before_rect.left},{before_rect.top},{before_rect.right},{before_rect.bottom}) "
                f"after=({after_rect.left},{after_rect.top},{after_rect.right},{after_rect.bottom}) "
                f"show={show_res}/err={show_err} "
                f"placement={placement_res}/err={placement_err} "
                f"setpos={pos_res}/err={pos_err} "
                f"{'已停靠到边缘保活位置' if parked else '未到达保活位置'}"
            )
            if show_err:
                self._append_log(f"  ShowWindow error: {_format_win32_error(show_err)}")
            if placement_err:
                self._append_log(f"  SetWindowPlacement error: {_format_win32_error(placement_err)}")
            if pos_err:
                self._append_log(f"  SetWindowPos error: {_format_win32_error(pos_err)}")

        if not self_admin and parked_count == 0:
            self._append_log("检测到普通权限下的窗口操作失败；请先点击右上角“管理员重启”再重试。")

        if group:
            self.saved_window_groups[pid] = group

        if parked_count > 0:
            self._append_log(
                f"已尝试停靠同进程窗口 {len(targets)} 个，成功进入边缘保活位置 {parked_count} 个。"
            )
            self._append_log(
                "已改为边缘保活模式：窗口仍有极小可见区域，实时预览通常会比完全离屏更稳定。"
            )
            self.status_var.set("已转入边缘保活模式；如目标是游戏，请不要再手动最小化。")
        else:
            self._append_log(
                "未能把任何同进程窗口停靠到边缘保活位置。该目标很可能是独占全屏或自管理窗口，"
                "标准 Win32 移动对它无效。建议尝试“强制窗口化”。"
            )
            self.status_var.set("转后台运行失败：目标窗口未进入保活位置。")

    def _force_selected_windowed(self):
        if not self.selected_hwnd:
            self.status_var.set("请先锚定一个窗口")
            return
        if not user32.IsWindow(self.selected_hwnd):
            self.status_var.set("目标窗口已关闭，请重新选择")
            self.selected_hwnd = None
            return

        hwnd = self.selected_hwnd
        pid = _get_pid(hwnd)
        self_admin = _is_self_admin()
        target_admin = _is_process_elevated(pid)
        self._append_log(
            f"强制窗口化诊断: self_admin={'是' if self_admin else '否'} "
            f"target_admin={'是' if target_admin else '否' if target_admin is not None else '未知'} "
            f"pid={pid}"
        )
        if target_admin and not self_admin:
            self._append_log("⚠ 当前程序不是管理员，而目标进程是管理员。样式修改大概率会被拒绝。")

        targets = _enum_process_windows(pid)
        if hwnd not in targets:
            targets.insert(0, hwnd)

        group_styles = self.saved_window_styles.setdefault(pid, {})
        changed_count = 0

        for index, target in enumerate(targets, 1):
            style_before = user32.GetWindowLongW(target, GWL_STYLE)
            ex_before = user32.GetWindowLongW(target, GWL_EXSTYLE)
            if target not in group_styles:
                group_styles[target] = (style_before, ex_before)

            before_rect = _get_window_rect(target)
            width = max(before_rect.right - before_rect.left, 800)
            height = max(before_rect.bottom - before_rect.top, 600)

            # 尝试把 popup/独占式窗口改成普通 overlapped window，便于后续移出屏幕。
            style_after_target = (style_before | WS_OVERLAPPEDWINDOW) & ~WS_POPUP
            kernel32.SetLastError(0)
            setstyle_res = user32.SetWindowLongW(target, GWL_STYLE, style_after_target)
            setstyle_err = kernel32.GetLastError()

            kernel32.SetLastError(0)
            show_res = user32.ShowWindow(target, SW_RESTORE)
            show_err = kernel32.GetLastError()

            kernel32.SetLastError(0)
            pos_res = user32.SetWindowPos(
                target,
                0,
                80 + index * 20,
                80 + index * 20,
                width,
                height,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
            pos_err = kernel32.GetLastError()

            style_after = user32.GetWindowLongW(target, GWL_STYLE)
            after_rect = _get_window_rect(target)
            changed = style_after != style_before or _rect_intersects_virtual_screen(after_rect)
            if changed:
                changed_count += 1

            title = _get_window_text(target) or "<无标题>"
            self._append_log(
                f"强制窗口化[{index}] hwnd={target:#010x} title={title!r} "
                f"style_before=0x{style_before & 0xFFFFFFFF:08X} "
                f"style_after=0x{style_after & 0xFFFFFFFF:08X} "
                f"setstyle={setstyle_res}/err={setstyle_err} "
                f"show={show_res}/err={show_err} "
                f"setpos={pos_res}/err={pos_err} "
                f"rect_after=({after_rect.left},{after_rect.top},{after_rect.right},{after_rect.bottom})"
            )
            if setstyle_err:
                self._append_log(f"  SetWindowLongW error: {_format_win32_error(setstyle_err)}")
            if show_err:
                self._append_log(f"  ShowWindow error: {_format_win32_error(show_err)}")
            if pos_err:
                self._append_log(f"  SetWindowPos error: {_format_win32_error(pos_err)}")

        if not self_admin and changed_count == 0:
            self._append_log("检测到普通权限下的样式/移动操作失败；请先点击右上角“管理员重启”再重试。")

        if changed_count > 0:
            self._append_log("已尝试强制窗口化。若画面已能脱离独占态，请再点击“转后台运行”。")
            self.status_var.set("已尝试强制窗口化，请观察游戏是否切为窗口化。")
        else:
            self._append_log(
                "强制窗口化没有产生可见变化。该目标可能并非标准 Win32 窗口，"
                "或需要游戏内部设置/快捷键切换窗口模式。"
            )
            self.status_var.set("强制窗口化未生效。")

    def _toggle_selected_taskbar_icon(self):
        if not self.selected_hwnd:
            self.status_var.set("请先锚定一个窗口")
            return
        if not user32.IsWindow(self.selected_hwnd):
            self.status_var.set("目标窗口已关闭，请重新选择")
            self.selected_hwnd = None
            self._update_taskbar_toggle_button_text()
            return

        pid = _get_pid(self.selected_hwnd)
        if self.saved_taskbar_exstyles.get(pid):
            self._restore_selected_taskbar_icon()
        else:
            self._hide_selected_taskbar_icon()

    def _hide_selected_taskbar_icon(self):
        if not self.selected_hwnd:
            self.status_var.set("请先锚定一个窗口")
            return
        if not user32.IsWindow(self.selected_hwnd):
            self.status_var.set("目标窗口已关闭，请重新选择")
            self.selected_hwnd = None
            return

        hwnd = self.selected_hwnd
        pid = _get_pid(hwnd)
        self_admin = _is_self_admin()
        target_admin = _is_process_elevated(pid)
        self._append_log(
            f"隐藏任务栏图标诊断: self_admin={'是' if self_admin else '否'} "
            f"target_admin={'是' if target_admin else '否' if target_admin is not None else '未知'} "
            f"pid={pid}"
        )

        targets = _enum_process_windows(pid)
        if hwnd not in targets:
            targets.insert(0, hwnd)

        saved_group = self.saved_taskbar_exstyles.setdefault(pid, {})
        changed_count = 0

        for index, target in enumerate(targets, 1):
            ex_before = user32.GetWindowLongW(target, GWL_EXSTYLE)
            if target not in saved_group:
                saved_group[target] = ex_before

            # 从任务栏应用窗口切成工具窗口，通常会让任务栏按钮消失。
            ex_after_target = (ex_before | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW

            kernel32.SetLastError(0)
            setstyle_res = user32.SetWindowLongW(target, GWL_EXSTYLE, ex_after_target)
            setstyle_err = kernel32.GetLastError()

            kernel32.SetLastError(0)
            frame_res = user32.SetWindowPos(
                target,
                0,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
            frame_err = kernel32.GetLastError()

            # 用 hide/show 刷新 shell 对任务栏按钮的判断。
            kernel32.SetLastError(0)
            hide_res = user32.ShowWindow(target, SW_HIDE)
            hide_err = kernel32.GetLastError()

            kernel32.SetLastError(0)
            show_res = user32.ShowWindow(target, SW_SHOWNA)
            show_err = kernel32.GetLastError()

            ex_after = user32.GetWindowLongW(target, GWL_EXSTYLE)
            title = _get_window_text(target) or "<无标题>"
            changed = ex_after != ex_before
            if changed:
                changed_count += 1

            self._append_log(
                f"隐藏任务栏图标[{index}] hwnd={target:#010x} title={title!r} "
                f"ex_before=0x{ex_before & 0xFFFFFFFF:08X} "
                f"ex_after=0x{ex_after & 0xFFFFFFFF:08X} "
                f"setstyle={setstyle_res}/err={setstyle_err} "
                f"frame={frame_res}/err={frame_err} "
                f"hide={hide_res}/err={hide_err} show={show_res}/err={show_err}"
            )
            if setstyle_err:
                self._append_log(f"  SetWindowLongW(EXSTYLE) error: {_format_win32_error(setstyle_err)}")
            if frame_err:
                self._append_log(f"  SetWindowPos(FRAMECHANGED) error: {_format_win32_error(frame_err)}")
            if hide_err:
                self._append_log(f"  ShowWindow(HIDE) error: {_format_win32_error(hide_err)}")
            if show_err:
                self._append_log(f"  ShowWindow(SHOWNA) error: {_format_win32_error(show_err)}")

        if not self_admin and changed_count == 0:
            self._append_log("检测到普通权限下的 EXSTYLE 修改失败；请先点击右上角“管理员重启”再重试。")

        if changed_count > 0:
            self._append_log("已尝试隐藏任务栏图标。注意：这通常也会影响 Alt+Tab 显示。")
            self.status_var.set("已尝试隐藏任务栏图标")
        else:
            self._append_log("未观察到 EXSTYLE 变化，任务栏图标可能仍然可见。")
            self.status_var.set("隐藏任务栏图标未生效")
        self._update_taskbar_toggle_button_text()

    def _restore_selected_taskbar_icon(self):
        if not self.selected_hwnd:
            self.status_var.set("请先锚定一个窗口")
            return

        pid = _get_pid(self.selected_hwnd)
        saved_group = self.saved_taskbar_exstyles.pop(pid, None)
        if not saved_group:
            self.status_var.set("没有可恢复的任务栏图标状态")
            return

        restored = 0
        for target, ex_before in saved_group.items():
            if not user32.IsWindow(target):
                continue
            user32.SetWindowLongW(target, GWL_EXSTYLE, ex_before)
            user32.SetWindowPos(
                target,
                0,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
            user32.ShowWindow(target, SW_HIDE)
            user32.ShowWindow(target, SW_SHOWNA)
            restored += 1

        self._append_log(f"已恢复 {restored} 个窗口的任务栏图标/EXSTYLE。")
        self.status_var.set("已恢复任务栏图标")
        self._update_taskbar_toggle_button_text()

    def _toggle_sample_preview(self):
        if self.sample_preview_enabled:
            self._stop_sample_preview("已关闭采样预览")
            return

        if not self.selected_hwnd:
            self.status_var.set("请先锚定一个窗口")
            return
        if not user32.IsWindow(self.selected_hwnd):
            self.status_var.set("目标窗口已关闭，请重新选择")
            self.selected_hwnd = None
            return

        if not self._apply_sample_preview_interval_setting(show_feedback=False):
            return

        self._cancel_dwm_preview_jobs()
        self._clear_dwm_preview_snapshot()
        self.sample_preview_enabled = True
        self.sample_preview_btn_text.set("停止采样预览")
        self._update_thumbnail_layout()
        self._append_log(
            "已开启采样预览：将主动调用 PrintWindow/位图抓取刷新画面，不再只依赖 DWM 缩略图。"
            f" 当前采样间隔 {self._format_sample_preview_interval(self.sample_preview_interval_ms)} 秒。"
            " DWM/GPU 预览已暂时隐藏，当前显示的是采样帧。"
        )
        self.status_var.set("采样预览已开启")
        self._schedule_sample_preview(initial=True)

    def _stop_sample_preview(self, status: str = "已关闭采样预览"):
        self.sample_preview_enabled = False
        self.sample_preview_btn_text.set("开启采样预览")
        if self.sample_preview_after_id:
            self.root.after_cancel(self.sample_preview_after_id)
            self.sample_preview_after_id = None
        self.sample_preview_busy = False
        self.sample_preview_fail_streak = 0
        self.sample_preview_image = None
        self.display_area.delete("sample_preview")
        if self.thumbnail_id.value:
            self._update_thumbnail_layout()
        if self.running:
            self._restart_dwm_preview_mode(immediate=True)
        if status == "已关闭采样预览":
            self._append_log("已关闭采样预览，已恢复 DWM/GPU 预览。")
        self.status_var.set(status)

    def _schedule_sample_preview(self, initial: bool = False):
        if not self.sample_preview_enabled or not self.running:
            return
        delay = 40 if initial else self.sample_preview_interval_ms
        self.sample_preview_after_id = self.root.after(delay, self._sample_preview_tick)

    def _sample_preview_tick(self):
        self.sample_preview_after_id = None
        if not self.sample_preview_enabled or not self.running:
            return
        if not self.selected_hwnd or not user32.IsWindow(self.selected_hwnd):
            self._stop_sample_preview("采样预览已停止：目标窗口无效")
            return
        if self.sample_preview_busy:
            self._schedule_sample_preview()
            return

        self.sample_preview_busy = True

        self.display_area.update_idletasks()
        max_w = max(self.display_area.winfo_width(), 200)
        max_h = max(self.display_area.winfo_height(), 200)
        hwnd = self.selected_hwnd
        client_only = self.client_only_var.get()

        def worker():
            result = _capture_window_preview_data(hwnd, client_only, max_w, max_h)

            def finalize():
                self.sample_preview_busy = False
                if not self.sample_preview_enabled or not self.running:
                    return
                if result is None:
                    self.sample_preview_fail_streak += 1
                    if self.sample_preview_fail_streak in (1, 10) or self.sample_preview_fail_streak % 30 == 0:
                        self._append_log("采样预览抓帧失败：目标窗口暂时没有返回可用帧，已自动快速重试。")
                    self.sample_preview_after_id = self.root.after(
                        self._get_sample_preview_retry_delay_ms(),
                        self._sample_preview_tick,
                    )
                else:
                    self.sample_preview_fail_streak = 0
                    self._display_sample_preview(result)
                    self._schedule_sample_preview()

            self.root.after(0, finalize)

        threading.Thread(target=worker, daemon=True).start()

    def _display_sample_preview(self, capture_result: tuple[str, int, int, int, int]):
        encoded_image, img_w, img_h, src_w, src_h = capture_result
        try:
            image = tk.PhotoImage(data=encoded_image, format="PNG")
        except tk.TclError:
            self._append_log(
                f"采样预览显示失败：Tk 无法解析 PNG 抓取结果。size={img_w}x{img_h}"
            )
            return

        self.sample_preview_image = image
        self.display_area.delete("sample_preview")
        cw = max(self.display_area.winfo_width(), 200)
        ch = max(self.display_area.winfo_height(), 200)
        dx = (cw - img_w) // 2
        dy = (ch - img_h) // 2
        self.display_area.create_image(
            cw // 2,
            ch // 2,
            image=self.sample_preview_image,
            anchor=tk.CENTER,
            tags="sample_preview",
        )
        source_metrics = self._get_preview_source_metrics(self.client_only_var.get())
        if source_metrics:
            source_metrics["source_width"] = src_w
            source_metrics["source_height"] = src_h
        self._set_preview_mapping("sample", dx, dy, img_w, img_h, source_metrics)

    def _restore_saved_window_group(self, pid: int) -> int:
        group = self.saved_window_groups.pop(pid, None)
        style_group = self.saved_window_styles.pop(pid, {})
        taskbar_group = self.saved_taskbar_exstyles.pop(pid, {})
        if not group and not taskbar_group and not style_group:
            return 0

        restored = 0
        targets = set()
        if group:
            targets.update(group.keys())
        targets.update(style_group.keys())
        targets.update(taskbar_group.keys())

        for target in targets:
            if not user32.IsWindow(target):
                continue
            style_saved = style_group.get(target)
            if style_saved:
                style_before, ex_before = style_saved
                user32.SetWindowLongW(target, GWL_STYLE, style_before)
                user32.SetWindowLongW(target, GWL_EXSTYLE, ex_before)
                user32.SetWindowPos(
                    target,
                    0,
                    0,
                    0,
                    0,
                    0,
                    SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
                )
            taskbar_exstyle = taskbar_group.get(target)
            if taskbar_exstyle is not None:
                user32.SetWindowLongW(target, GWL_EXSTYLE, taskbar_exstyle)
                user32.SetWindowPos(
                    target,
                    0,
                    0,
                    0,
                    0,
                    0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
                )
            placement = group.get(target) if group else None
            if placement is not None:
                user32.SetWindowPlacement(target, ctypes.byref(placement))
            restored += 1
        return restored

    def _restore_all_saved_windows(self) -> tuple[int, int]:
        pids = set(self.saved_window_groups)
        pids.update(self.saved_window_styles)
        pids.update(self.saved_taskbar_exstyles)
        restored_total = 0
        for pid in list(pids):
            restored_total += self._restore_saved_window_group(pid)
        return restored_total, len(pids)

    def _restore_selected_window(self):
        if not self.selected_hwnd:
            self.status_var.set("请先锚定一个窗口")
            return

        pid = _get_pid(self.selected_hwnd)
        restored = self._restore_saved_window_group(pid)
        if restored <= 0:
            self.status_var.set("没有可恢复的原始窗口位置")
            return

        self._append_log(f"已恢复同进程窗口 {restored} 个到原始位置/样式/任务栏状态。")
        self.status_var.set("已恢复目标窗口")
        self._update_taskbar_toggle_button_text()

    # ── DWM Thumbnail 布局更新 ──

    def _clear_dwm_preview_snapshot(self):
        self.dwm_preview_snapshot_image = None
        self.display_area.delete("dwm_preview_snapshot")

    def _cancel_dwm_preview_jobs(self):
        if self.dwm_preview_after_id:
            self.root.after_cancel(self.dwm_preview_after_id)
            self.dwm_preview_after_id = None
        if self.dwm_preview_capture_after_id:
            self.root.after_cancel(self.dwm_preview_capture_after_id)
            self.dwm_preview_capture_after_id = None

    def _is_dwm_preview_throttled(self) -> bool:
        return bool(
            self.selected_hwnd
            and not self.sample_preview_enabled
            and self.dwm_preview_interval_ms > 0
        )

    def _restore_live_dwm_preview(self):
        self._cancel_dwm_preview_jobs()
        self.dwm_preview_live_visible = True
        self.dwm_preview_fail_streak = 0
        self._clear_dwm_preview_snapshot()
        if not self.selected_hwnd or not user32.IsWindow(self.selected_hwnd):
            return
        hr = self._register_thumbnail()
        if hr == 0:
            self._update_thumbnail_layout()

    def _schedule_dwm_preview_cycle(self, initial: bool = False):
        if not self._is_dwm_preview_throttled():
            return
        delay = 0 if initial else self.dwm_preview_interval_ms
        self.dwm_preview_after_id = self.root.after(delay, self._begin_dwm_preview_cycle)

    def _begin_dwm_preview_cycle(self):
        self.dwm_preview_after_id = None
        if not self._is_dwm_preview_throttled():
            return
        hr = self._register_thumbnail()
        if hr != 0:
            self.dwm_preview_fail_streak += 1
            if self.dwm_preview_fail_streak in (1, 10) or self.dwm_preview_fail_streak % 30 == 0:
                self._append_log(
                    f"主预览限帧注册失败：DWM 缩略图无法建立 "
                    f"(0x{hr & 0xFFFFFFFF:08X})，已等待下一轮。"
                )
            self._schedule_dwm_preview_cycle()
            return
        self.dwm_preview_live_visible = True
        self._update_thumbnail_layout()
        self.dwm_preview_capture_after_id = self.root.after(
            self.DWM_PREVIEW_SETTLE_MS,
            self._capture_dwm_preview_snapshot,
        )

    def _capture_dwm_preview_snapshot(self):
        self.dwm_preview_capture_after_id = None
        if not self._is_dwm_preview_throttled():
            return

        self.display_area.update_idletasks()
        screen_x = self.display_area.winfo_rootx()
        screen_y = self.display_area.winfo_rooty()
        width = self.display_area.winfo_width()
        height = self.display_area.winfo_height()

        overlay_was_visible = bool(
            self.preview_overlay_window
            and self.preview_overlay_window.winfo_exists()
            and self.preview_overlay_window.state() != "withdrawn"
        )
        if overlay_was_visible:
            self.preview_overlay_window.withdraw()

        try:
            capture_result = _capture_screen_region_png(screen_x, screen_y, width, height)
        finally:
            if overlay_was_visible:
                self._sync_preview_overlay()
        if capture_result is None:
            self.dwm_preview_fail_streak += 1
            if self.dwm_preview_fail_streak in (1, 10) or self.dwm_preview_fail_streak % 30 == 0:
                self._append_log("主预览限帧抓帧失败：未拿到可用 DWM 快照，已等待下一轮。")
            if self.dwm_preview_snapshot_image is not None:
                self._unregister_thumbnail()
                self.dwm_preview_live_visible = False
            else:
                self.dwm_preview_live_visible = True
                self._update_thumbnail_layout()
            self._schedule_dwm_preview_cycle()
            return

        encoded_image, _, _ = capture_result
        try:
            image = tk.PhotoImage(data=encoded_image, format="PNG")
        except tk.TclError:
            self.dwm_preview_fail_streak += 1
            if self.dwm_preview_fail_streak in (1, 10) or self.dwm_preview_fail_streak % 30 == 0:
                self._append_log("主预览限帧显示失败：Tk 无法解析当前 DWM/GPU 快照。")
            if self.dwm_preview_snapshot_image is not None:
                self._unregister_thumbnail()
                self.dwm_preview_live_visible = False
            else:
                self.dwm_preview_live_visible = True
                self._update_thumbnail_layout()
            self._schedule_dwm_preview_cycle()
            return

        self.dwm_preview_fail_streak = 0
        self.dwm_preview_snapshot_image = image
        self.display_area.delete("dwm_preview_snapshot")
        self.display_area.create_image(
            width // 2,
            height // 2,
            image=self.dwm_preview_snapshot_image,
            anchor=tk.CENTER,
            tags="dwm_preview_snapshot",
        )
        self._unregister_thumbnail()
        self.dwm_preview_live_visible = False
        self._schedule_dwm_preview_cycle()

    def _restart_dwm_preview_mode(self, immediate: bool = False):
        self._cancel_dwm_preview_jobs()
        if not self._is_dwm_preview_throttled():
            self._restore_live_dwm_preview()
            return
        self._clear_dwm_preview_snapshot()
        if immediate:
            self._begin_dwm_preview_cycle()
        else:
            self._schedule_dwm_preview_cycle(initial=True)

    def _format_dwm_preview_interval(self, interval_ms: int) -> str:
        if interval_ms <= 0:
            return "0"
        return f"{interval_ms / 1000:g}"

    def _apply_dwm_preview_interval_setting(self, show_feedback: bool = False) -> bool:
        raw_value = self.dwm_preview_interval_var.get().strip()
        if not raw_value:
            self.status_var.set("主预览间隔无效，请输入秒数，例如 0 / 0.5 / 1 / 2")
            return False

        try:
            seconds = float(raw_value)
        except ValueError:
            self.status_var.set("主预览间隔无效，请输入秒数，例如 0 / 0.5 / 1 / 2")
            return False

        if seconds < 0:
            self.status_var.set("主预览间隔不能小于 0 秒")
            return False

        previous_interval = self.dwm_preview_interval_ms
        interval_ms = 0 if seconds == 0 else max(int(round(seconds * 1000)), 50)
        normalized = self._format_dwm_preview_interval(interval_ms)
        self.dwm_preview_interval_ms = interval_ms
        if raw_value != normalized:
            self.dwm_preview_interval_var.set(normalized)

        if show_feedback and interval_ms != previous_interval:
            label = "实时" if interval_ms == 0 else f"{normalized} 秒"
            message = f"主预览间隔已设置为 {label}"
            if self.sample_preview_enabled:
                self.status_var.set(message)
            else:
                self._append_log(message)
        return True

    def _on_dwm_preview_interval_commit(self, _event=None):
        previous_interval = self.dwm_preview_interval_ms
        if not self._apply_dwm_preview_interval_setting(show_feedback=True):
            return
        if self.sample_preview_enabled or self.dwm_preview_interval_ms == previous_interval:
            return
        self._restart_dwm_preview_mode(immediate=True)

    def _format_sample_preview_interval(self, interval_ms: int) -> str:
        return f"{interval_ms / 1000:g}"

    def _apply_sample_preview_interval_setting(self, show_feedback: bool = False) -> bool:
        raw_value = self.sample_preview_interval_var.get().strip()
        if not raw_value:
            self.status_var.set("采样间隔无效，请输入秒数，例如 0.2 / 1 / 2")
            return False

        try:
            seconds = float(raw_value)
        except ValueError:
            self.status_var.set("采样间隔无效，请输入秒数，例如 0.2 / 1 / 2")
            return False

        if seconds <= 0:
            self.status_var.set("采样间隔必须大于 0 秒")
            return False

        previous_interval = self.sample_preview_interval_ms
        interval_ms = max(int(round(seconds * 1000)), 50)
        normalized = self._format_sample_preview_interval(interval_ms)
        self.sample_preview_interval_ms = interval_ms
        if raw_value != normalized:
            self.sample_preview_interval_var.set(normalized)

        if show_feedback and interval_ms != previous_interval:
            message = f"采样间隔已设置为 {normalized} 秒"
            if self.sample_preview_enabled:
                self._append_log(message)
            else:
                self.status_var.set(message)
        return True

    def _get_sample_preview_retry_delay_ms(self) -> int:
        if self.sample_preview_interval_ms > self.SAMPLE_PREVIEW_INTERVAL_MS:
            return self.sample_preview_interval_ms
        return self.SAMPLE_PREVIEW_RETRY_INTERVAL_MS

    def _on_sample_preview_interval_commit(self, _event=None):
        previous_interval = self.sample_preview_interval_ms
        if not self._apply_sample_preview_interval_setting(show_feedback=True):
            return
        if not self.sample_preview_enabled or self.sample_preview_interval_ms == previous_interval:
            return
        if self.sample_preview_after_id:
            self.root.after_cancel(self.sample_preview_after_id)
            self.sample_preview_after_id = self.root.after(
                self.sample_preview_interval_ms,
                self._sample_preview_tick,
            )
        elif not self.sample_preview_busy:
            self.sample_preview_after_id = self.root.after(
                self.sample_preview_interval_ms,
                self._sample_preview_tick,
            )

    def _refresh_sample_preview_now(self):
        if not self.sample_preview_enabled:
            return
        if self.sample_preview_after_id:
            self.root.after_cancel(self.sample_preview_after_id)
            self.sample_preview_after_id = None
        self._sample_preview_tick()

    def _on_client_only_toggle(self):
        self._update_thumbnail_layout()
        if self.sample_preview_enabled:
            self._refresh_sample_preview_now()
        else:
            self._restart_dwm_preview_mode(immediate=True)

    def _update_thumbnail_layout(self):
        self._sync_preview_overlay()
        if not self.thumbnail_id.value:
            return

        self.display_area.update_idletasks()
        dest_hwnd = self._get_dest_hwnd()

        # 将 tkinter 坐标转换为 Win32 客户区坐标
        screen_x = self.display_area.winfo_rootx()
        screen_y = self.display_area.winfo_rooty()
        area_w = self.display_area.winfo_width()
        area_h = self.display_area.winfo_height()

        pt = wintypes.POINT(screen_x, screen_y)
        user32.ScreenToClient(dest_hwnd, ctypes.byref(pt))
        x, y = pt.x, pt.y

        source_metrics = self._get_preview_source_metrics(self.client_only_var.get())
        if source_metrics:
            src_width = int(source_metrics["source_width"])
            src_height = int(source_metrics["source_height"])
            ratio = min(area_w / src_width, area_h / src_height)
            dw = int(src_width * ratio)
            dh = int(src_height * ratio)
            canvas_dx = (area_w - dw) // 2
            canvas_dy = (area_h - dh) // 2
            dx = x + (area_w - dw) // 2
            dy = y + (area_h - dh) // 2
        else:
            canvas_dx, canvas_dy = 0, 0
            dx, dy, dw, dh = x, y, area_w, area_h

        props = DWM_THUMBNAIL_PROPERTIES()
        props.dwFlags = (DWM_TNP_RECTDESTINATION | DWM_TNP_VISIBLE
                         | DWM_TNP_SOURCECLIENTAREAONLY | DWM_TNP_OPACITY)
        props.rcDestination = wintypes.RECT(dx, dy, dx + dw, dy + dh)
        props.fVisible = bool(not self.sample_preview_enabled and self.dwm_preview_live_visible)
        props.fSourceClientAreaOnly = self.client_only_var.get()
        props.opacity = 255

        dwmapi.DwmUpdateThumbnailProperties(
            self.thumbnail_id, ctypes.byref(props)
        )
        if not self.sample_preview_enabled:
            self._set_preview_mapping("dwm", canvas_dx, canvas_dy, dw, dh, source_metrics)

    # ── 日志输出 ──

    def _trim_log_buffer(self):
        try:
            line_count = int(self.log_text.index("end-1c").split(".")[0])
        except Exception:
            return
        if line_count <= LOG_TEXT_MAX_LINES:
            return

        trim_before_line = max(line_count - LOG_TEXT_TRIM_TO_LINES, 1)
        self.log_text.delete("1.0", f"{trim_before_line}.0")

    def _append_log(self, msg: str):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self._trim_log_buffer()
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self._handle_virtual_click_log(msg)
        self.status_var.set(f"[脚本] {msg}")

    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _restart_as_admin(self):
        if self.is_admin:
            self.status_var.set("当前已经是管理员权限")
            return

        if not messagebox.askyesno(
            "管理员重启",
            "将使用 UAC 重新启动本程序为管理员权限。\n\n是否继续？",
        ):
            return

        if not _relaunch_current_process_as_admin():
            self._append_log("管理员重启失败：UAC 被取消或系统拒绝启动管理员实例。")
            self.status_var.set("管理员重启失败")
            return

        self._append_log("已拉起管理员实例，请在新窗口中继续操作。当前窗口即将关闭。")
        self.status_var.set("已启动管理员实例")
        self.root.after(400, self._on_close)

    # ── 执行外部脚本 ──

    def _get_valid_selected_hwnd(self) -> int | None:
        if not self.selected_hwnd:
            self.status_var.set("请先锚定一个窗口")
            return None
        if not user32.IsWindow(self.selected_hwnd):
            self.status_var.set("目标窗口已关闭，请重新选择")
            self.selected_hwnd = None
            return None
        return self.selected_hwnd

    def _set_script_running_state(self, running: bool):
        if running:
            self.run_script_btn.state(["disabled"])
            self.stop_script_btn.state(["!disabled"])
            for check in self.logic_task_checkbuttons:
                check.state(["disabled"])
            for check in self.logic_option_checkbuttons:
                check.state(["disabled"])
            return

        self.run_script_btn.state(["!disabled"])
        self.stop_script_btn.state(["disabled"])
        for check in self.logic_task_checkbuttons:
            check.state(["!disabled"])
        for check in self.logic_option_checkbuttons:
            check.state(["!disabled"])

    def _get_selected_logic_task_flags(self) -> dict[str, bool]:
        return {
            key: bool(self.logic_task_vars[key].get())
            for key, _label, _default in self.logic_task_specs
        }

    def _get_selected_logic_option_flags(self) -> dict[str, bool]:
        flags = {
            key: bool(self.logic_option_vars[key].get())
            for key, _label, _default in self.logic_option_specs
        }
        try:
            flags["zhua_gui_rounds"] = int(self.zhua_gui_rounds_var.get())
        except (ValueError, TypeError):
            flags["zhua_gui_rounds"] = 0
        return flags

    def _run_script_action_task(
        self,
        runner,
        *,
        clear_log: bool,
        buttons: list[ttk.Button],
        module_name: str = "script_action",
    ):
        hwnd = self._get_valid_selected_hwnd()
        if not hwnd:
            return

        for button in buttons:
            button.state(["disabled"])
        if clear_log:
            self._clear_log()

        def _worker():
            try:
                module = importlib.import_module(module_name)
                module = importlib.reload(module)

                def log(msg: str):
                    self.root.after(0, self._append_log, msg)

                runner(module, hwnd, log)
            except Exception as e:
                self.root.after(
                    0, self._append_log, f"[错误] {e}"
                )
            finally:
                for button in buttons:
                    self.root.after(0, button.state, ["!disabled"])

        threading.Thread(target=_worker, daemon=True).start()

    def _run_script(self):
        hwnd = self._get_valid_selected_hwnd()
        if not hwnd:
            return
        if self.script_stop_event is not None:
            self.status_var.set("脚本正在运行或等待终止，请稍后再试")
            return

        task_flags = self._get_selected_logic_task_flags()
        task_options = self._get_selected_logic_option_flags()
        selected_labels = [
            label
            for key, label, _default in self.logic_task_specs
            if task_flags.get(key)
        ]
        if not selected_labels:
            self.status_var.set("请先勾选至少一个功能块")
            return

        self._clear_log()
        self.script_stop_event = threading.Event()
        self._set_script_running_state(True)
        self._append_log(f"已启动脚本，当前勾选功能块: {' / '.join(selected_labels)}")
        selected_option_labels = [
            label
            for key, label, _default in self.logic_option_specs
            if task_options.get(key)
        ]
        if selected_option_labels:
            self._append_log(f"已启用附加选项: {' / '.join(selected_option_labels)}")

        def _ui_call(func, *args):
            try:
                self.root.after(0, func, *args)
            except Exception:
                pass

        def _worker():
            try:
                module = importlib.import_module("game_logic")
                module = importlib.reload(module)

                def log(msg: str):
                    _ui_call(self._append_log, msg)

                module.run(
                    hwnd,
                    log,
                    stop_event=self.script_stop_event,
                    task_flags=task_flags,
                    task_options=task_options,
                )
            except Exception as e:
                _ui_call(self._append_log, f"[错误] {e}")
            finally:
                def _finalize():
                    self.script_stop_event = None
                    self._set_script_running_state(False)

                _ui_call(_finalize)

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_script(self):
        if self.script_stop_event is None:
            self.status_var.set("当前没有正在运行的脚本")
            return
        if self.script_stop_event.is_set():
            self.status_var.set("已发送终止请求，等待当前步骤结束")
            return

        self.script_stop_event.set()
        self.stop_script_btn.state(["disabled"])
        self._append_log("已请求终止脚本，等待当前步骤安全结束...")

    def _debug_click(self):
        hwnd = self._get_valid_selected_hwnd()
        if not hwnd:
            return

        try:
            x = int(self.debug_x_var.get())
            y = int(self.debug_y_var.get())
        except ValueError:
            self.status_var.set("请输入有效的 Debug 整数坐标")
            return

        def _runner(script_action, hwnd: int, log):
            log(f"开始 Debug 点击：({x}, {y})")
            bot = script_action.WindowAutomation(hwnd, log)
            bot.prepare()
            bot.click(x, y)

        self._run_script_action_task(
            _runner,
            clear_log=False,
            buttons=[self.debug_click_btn, self.debug_robust_click_btn],
        )

    def _debug_robust_click(self):
        hwnd = self._get_valid_selected_hwnd()
        if not hwnd:
            return

        try:
            x = int(self.debug_x_var.get())
            y = int(self.debug_y_var.get())
        except ValueError:
            self.status_var.set("请输入有效的 Debug 整数坐标")
            return

        def _runner(script_action, hwnd: int, log):
            log(f"开始强力点击回退：({x}, {y})")
            bot = script_action.WindowAutomation(hwnd, log)
            bot.prepare()
            bot.click_robust(x, y)

        self._run_script_action_task(
            _runner,
            clear_log=False,
            buttons=[self.debug_click_btn, self.debug_robust_click_btn],
        )

    # ── Debug 放大镜 ──

    def _open_debug_view(self):
        if not self.selected_hwnd:
            self.status_var.set("请先锚定一个窗口")
            return
        if not user32.IsWindow(self.selected_hwnd):
            self.status_var.set("目标窗口已关闭，请重新选择")
            return

        try:
            cx = int(self.debug_x_var.get())
            cy = int(self.debug_y_var.get())
            size = int(self.debug_size_var.get())
        except ValueError:
            self.status_var.set("请输入有效的整数坐标和区域大小")
            return

        half = max(size // 2, 1)
        src_left = max(cx - half, 0)
        src_top = max(cy - half, 0)
        src_right = src_left + size
        src_bottom = src_top + size

        zoom = 300
        is_new = self._ensure_debug_window(zoom)
        # 新窗口需要等待 Win32 窗口完全就位后再注册 thumbnail
        delay = 100 if is_new else 0
        if self.debug_register_after_id:
            try:
                self.root.after_cancel(self.debug_register_after_id)
            except Exception:
                pass
        self.debug_register_after_id = self.root.after(delay, lambda: self._register_debug_thumbnail(
            src_left, src_top, src_right, src_bottom, zoom
        ))

        self.status_var.set(
            f"Debug 放大镜  |  中心({cx},{cy})  区域 {size}×{size}px  →  {zoom}×{zoom} 渲染"
        )

    def _ensure_debug_window(self, view_size: int) -> bool:
        """确保 Debug 窗口存在，返回 True 表示新建了窗口。"""
        if self.debug_window and self.debug_window.winfo_exists():
            return False

        self.debug_window = tk.Toplevel(self.root)
        self.debug_window.title("Debug 放大镜")
        self.debug_window.geometry(f"{view_size}x{view_size}")
        self.debug_window.resizable(False, False)
        self.debug_window.configure(bg="#181825")
        self.debug_window.attributes("-topmost", True)
        self.debug_window.protocol("WM_DELETE_WINDOW", self._close_debug_view)

        self.debug_canvas = tk.Canvas(
            self.debug_window, bg="#181825", highlightthickness=0,
            width=view_size, height=view_size
        )
        self.debug_canvas.pack(fill=tk.BOTH, expand=True)
        return True

    def _register_debug_thumbnail(self, sl, st, sr, sb, view_size):
        self.debug_register_after_id = None
        self._unregister_debug_thumbnail()

        if not self.debug_window or not self.debug_window.winfo_exists():
            return

        self.debug_window.update_idletasks()
        debug_hwnd_inner = self.debug_window.winfo_id()
        debug_hwnd = user32.GetAncestor(debug_hwnd_inner, GA_ROOT)
        if not debug_hwnd:
            debug_hwnd = debug_hwnd_inner

        hr = dwmapi.DwmRegisterThumbnail(
            debug_hwnd, self.selected_hwnd,
            ctypes.byref(self.debug_thumbnail_id)
        )
        if hr != 0:
            self.status_var.set(
                f"Debug DWM 注册失败 (0x{hr & 0xFFFFFFFF:08X})")
            self.debug_thumbnail_id = HTHUMBNAIL()
            return

        # 直接用 GetClientRect 获取客户区尺寸，rcDestination 从 (0,0) 开始
        client_rect = wintypes.RECT()
        user32.GetClientRect(debug_hwnd, ctypes.byref(client_rect))

        props = DWM_THUMBNAIL_PROPERTIES()
        props.dwFlags = (DWM_TNP_RECTDESTINATION | DWM_TNP_RECTSOURCE
                         | DWM_TNP_VISIBLE | DWM_TNP_SOURCECLIENTAREAONLY
                         | DWM_TNP_OPACITY)
        props.rcDestination = wintypes.RECT(
            0, 0, client_rect.right, client_rect.bottom
        )
        props.rcSource = wintypes.RECT(sl, st, sr, sb)
        props.fVisible = True
        props.fSourceClientAreaOnly = True
        props.opacity = 255

        dwmapi.DwmUpdateThumbnailProperties(
            self.debug_thumbnail_id, ctypes.byref(props)
        )

        # DWM thumbnail 渲染在所有 GDI 内容之上，十字线需要用独立窗口叠加
        # 这里用 canvas 画十字线（会在 thumbnail 下方，但在深色背景边缘仍可见）
        self.debug_canvas.delete("all")
        c = view_size // 2
        line_color = "#f38ba8"
        self.debug_canvas.create_line(c, 0, c, view_size, fill=line_color, dash=(4, 4))
        self.debug_canvas.create_line(0, c, view_size, c, fill=line_color, dash=(4, 4))

    def _unregister_debug_thumbnail(self):
        if self.debug_thumbnail_id.value:
            dwmapi.DwmUnregisterThumbnail(self.debug_thumbnail_id)
            self.debug_thumbnail_id = HTHUMBNAIL()

    def _close_debug_view(self):
        if self.debug_register_after_id:
            try:
                self.root.after_cancel(self.debug_register_after_id)
            except Exception:
                pass
            self.debug_register_after_id = None
        self._unregister_debug_thumbnail()
        if self.debug_window:
            self.debug_window.destroy()
            self.debug_window = None
            self.debug_canvas = None

    def _on_configure_debounced(self):
        self._update_thumbnail_layout()
        if self.sample_preview_enabled:
            return
        if self.dwm_preview_interval_ms > 0:
            self._restart_dwm_preview_mode(immediate=True)

    # ── 窗口大小变化时重新布局（防抖） ──

    def _on_configure(self, _event):
        if self._configure_debounce_id:
            self.root.after_cancel(self._configure_debounce_id)
        self._configure_debounce_id = self.root.after(
            30, self._on_configure_debounced
        )

    # ── 运行 ──

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        if self.script_stop_event is not None and not self.script_stop_event.is_set():
            self.script_stop_event.set()
        self.running = False
        if self._configure_debounce_id:
            try:
                self.root.after_cancel(self._configure_debounce_id)
            except Exception:
                pass
            self._configure_debounce_id = None
        self._cancel_dwm_preview_jobs()
        if self.sample_preview_enabled:
            self._stop_sample_preview()
        restored_total, _ = self._restore_all_saved_windows()
        if restored_total > 0:
            self._append_log(
                f"程序关闭前已自动恢复 {restored_total} 个窗口到原始位置/样式/任务栏状态。"
            )
            self._update_taskbar_toggle_button_text()
        self._clear_dwm_preview_snapshot()
        self._clear_preview_marker(clear_state=True)
        self._reset_virtual_click_preview_state()
        self._destroy_preview_overlay()
        self._close_debug_view()
        self._unregister_thumbnail()
        self.root.destroy()


if __name__ == "__main__":
    if not _ensure_admin_startup():
        sys.exit(0)
    app = WindowCaptureApp()
    app.run()
