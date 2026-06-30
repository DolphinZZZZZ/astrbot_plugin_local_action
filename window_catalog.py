from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    process_name: str = ""
    process_path: str = ""
    title: str = ""
    class_name: str = ""
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0
    is_visible: bool = False
    is_foreground: bool = False
    is_minimized: bool = False

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "hwnd_hex": hex(self.hwnd),
            "pid": self.pid,
            "process_name": self.process_name,
            "process_path": self.process_path,
            "title": self.title,
            "class_name": self.class_name,
            "rect": {
                "left": self.left,
                "top": self.top,
                "right": self.right,
                "bottom": self.bottom,
                "width": self.width,
                "height": self.height,
            },
            "is_visible": self.is_visible,
            "is_foreground": self.is_foreground,
            "is_minimized": self.is_minimized,
            "selector": {
                "process": self.process_name,
                "title_contains": self.title,
                "class": self.class_name,
            },
            "selector_by_hwnd": {
                "hwnd": self.hwnd,
                "pid": self.pid,
            },
        }


class LocalWindowManager:
    def __init__(self) -> None:
        self._process_cache: dict[int, tuple[str, str]] = {}

    @staticmethod
    def is_supported() -> bool:
        return os.name == "nt"

    def list_windows(
        self,
        *,
        include_hidden: bool = False,
        include_minimized: bool = True,
        include_untitled: bool = False,
    ) -> list[WindowInfo]:
        if not self.is_supported():
            return []

        user32 = ctypes.windll.user32
        hwnds: list[int] = []

        enum_proc = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            wintypes.HWND,
            wintypes.LPARAM,
        )

        def _collect(hwnd, _lparam):
            hwnds.append(int(hwnd))
            return True

        user32.EnumWindows(enum_proc(_collect), 0)
        windows: list[WindowInfo] = []
        for hwnd in hwnds:
            info = self.get_window_info(hwnd)
            if not info:
                continue
            if not include_hidden and not info.is_visible:
                continue
            if not include_minimized and info.is_minimized:
                continue
            if not include_untitled and not info.title:
                continue
            if info.width <= 0 or info.height <= 0:
                continue
            windows.append(info)
        return sorted(
            windows,
            key=lambda item: (not item.is_foreground, item.process_name.lower(), item.title.lower()),
        )

    def get_foreground_window(self) -> WindowInfo | None:
        if not self.is_supported():
            return None
        hwnd = int(ctypes.windll.user32.GetForegroundWindow())
        if not hwnd:
            return None
        return self.get_window_info(hwnd)

    def get_window_info(self, hwnd: int) -> WindowInfo | None:
        if not self.is_supported() or not hwnd:
            return None

        user32 = ctypes.windll.user32
        length = int(user32.GetWindowTextLengthW(hwnd))
        title_buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, length + 1)

        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, 256)

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None

        process_name, process_path = self._process_identity(int(pid.value))
        foreground = int(user32.GetForegroundWindow())
        return WindowInfo(
            hwnd=int(hwnd),
            pid=int(pid.value),
            process_name=process_name,
            process_path=process_path,
            title=title_buffer.value,
            class_name=class_buffer.value,
            left=int(rect.left),
            top=int(rect.top),
            right=int(rect.right),
            bottom=int(rect.bottom),
            is_visible=bool(user32.IsWindowVisible(hwnd)),
            is_foreground=int(hwnd) == foreground,
            is_minimized=bool(user32.IsIconic(hwnd)),
        )

    def find_windows(
        self,
        selector: dict[str, Any] | None,
        *,
        limit: int = 20,
        windows: list[WindowInfo] | None = None,
    ) -> list[WindowInfo]:
        selector = selector or {}
        limit = max(1, min(int(limit or 20), 200))
        if selector.get("foreground"):
            foreground = self.get_foreground_window()
            if foreground and window_matches_selector(foreground, selector):
                return [foreground]
            return []

        hwnd = parse_int(selector.get("hwnd"))
        if hwnd is not None:
            info = self.get_window_info(hwnd)
            if info and window_matches_selector(info, selector):
                return [info]
            return []

        if not selector_has_matcher(selector):
            return []

        source = windows
        if source is None:
            source = self.list_windows(
                include_hidden=bool(selector.get("include_hidden", False)),
                include_minimized=bool(selector.get("include_minimized", True)),
                include_untitled=bool(selector.get("include_untitled", False)),
            )
        return [item for item in source if window_matches_selector(item, selector)][:limit]

    def find_one_window(self, selector: dict[str, Any] | None) -> WindowInfo | None:
        matches = self.find_windows(selector, limit=1)
        return matches[0] if matches else None

    def _process_identity(self, pid: int) -> tuple[str, str]:
        if pid in self._process_cache:
            return self._process_cache[pid]

        process_path, process_name = query_process_identity(pid)
        self._process_cache[pid] = (process_name, process_path)
        return self._process_cache[pid]


def selector_has_matcher(selector: dict[str, Any] | None) -> bool:
    selector = selector or {}
    keys = {
        "hwnd",
        "pid",
        "process",
        "process_name",
        "process_regex",
        "title",
        "title_contains",
        "title_regex",
        "class",
        "class_name",
        "class_regex",
        "foreground",
    }
    return any(selector.get(key) not in (None, "", False) for key in keys)


def window_matches_selector(info: WindowInfo, selector: dict[str, Any] | None) -> bool:
    selector = selector or {}

    hwnd = parse_int(selector.get("hwnd"))
    if hwnd is not None and info.hwnd != hwnd:
        return False

    pid = parse_int(selector.get("pid"))
    if pid is not None and info.pid != pid:
        return False

    if selector.get("foreground") and not info.is_foreground:
        return False

    if not bool(selector.get("include_hidden", False)) and not info.is_visible:
        return False

    if not bool(selector.get("include_minimized", True)) and info.is_minimized:
        return False

    expected_process = first_text(
        selector.get("process"),
        selector.get("process_name"),
        selector.get("exe"),
        selector.get("exe_name"),
    )
    if expected_process and not process_name_matches(info.process_name, expected_process):
        return False

    process_regex = first_text(selector.get("process_regex"), selector.get("exe_regex"))
    if process_regex and not safe_regex_search(info.process_name, process_regex):
        return False

    expected_class = first_text(selector.get("class"), selector.get("class_name"))
    if expected_class and not equals_ci(info.class_name, expected_class):
        return False

    class_regex = first_text(selector.get("class_regex"))
    if class_regex and not safe_regex_search(info.class_name, class_regex):
        return False

    title_exact = first_text(selector.get("title"))
    if title_exact and not equals_ci(info.title, title_exact):
        return False

    title_contains = first_text(selector.get("title_contains"), selector.get("title_part"))
    if title_contains and title_contains.lower() not in info.title.lower():
        return False

    title_regex = first_text(selector.get("title_regex"))
    if title_regex and not safe_regex_search(info.title, title_regex):
        return False

    condition = str(selector.get("condition") or "").strip()
    if condition and not condition_matches(info, selector, condition):
        return False

    return True


def condition_matches(
    info: WindowInfo,
    selector: dict[str, Any],
    condition: str,
) -> bool:
    condition = condition.lower()
    class_pattern = first_text(selector.get("condition_class"), selector.get("class_regex"), selector.get("class"))
    title_pattern = first_text(selector.get("condition_title"), selector.get("title_regex"), selector.get("title_contains"), selector.get("title"))
    if condition in {"class", "classname"}:
        return bool(class_pattern) and safe_regex_or_contains(info.class_name, class_pattern)
    if condition in {"title", "windowtitle"}:
        return bool(title_pattern) and safe_regex_or_contains(info.title, title_pattern)
    if condition in {"classandtitle", "class_and_title"}:
        return (
            bool(class_pattern)
            and bool(title_pattern)
            and safe_regex_or_contains(info.class_name, class_pattern)
            and safe_regex_or_contains(info.title, title_pattern)
        )
    return True


def format_window_info(info: WindowInfo) -> str:
    marker = "前台" if info.is_foreground else "窗口"
    return (
        f"[{marker}] {info.process_name or 'unknown'} PID={info.pid} "
        f"HWND={hex(info.hwnd)}\n"
        f"标题：{info.title or '(无标题)'}\n"
        f"类名：{info.class_name or '(未知)'}\n"
        f"区域：{info.left},{info.top},{info.width}x{info.height}"
    )


def format_window_list(windows: list[WindowInfo], *, limit: int = 20) -> str:
    if not windows:
        return "未找到匹配窗口。"
    lines: list[str] = []
    for index, info in enumerate(windows[:limit], start=1):
        prefix = "前台" if info.is_foreground else "窗口"
        title = info.title or "(无标题)"
        lines.append(
            f"{index}. [{prefix}] {info.process_name or 'unknown'} "
            f"PID={info.pid} HWND={hex(info.hwnd)} 标题={title}"
        )
    return "\n".join(lines)


def process_name_matches(actual: str, expected: str) -> bool:
    actual = (actual or "").strip().lower()
    expected = (expected or "").strip().lower()
    if not actual or not expected:
        return False
    if actual == expected:
        return True
    if "." not in expected and Path(actual).stem.lower() == expected:
        return True
    return False


def safe_regex_or_contains(value: str, pattern: str) -> bool:
    if not pattern:
        return True
    return safe_regex_search(value, pattern) or pattern.lower() in (value or "").lower()


def safe_regex_search(value: str, pattern: str) -> bool:
    try:
        return re.search(str(pattern), value or "", flags=re.IGNORECASE) is not None
    except re.error:
        return False


def equals_ci(left: str, right: str) -> bool:
    return (left or "").strip().lower() == (right or "").strip().lower()


def first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text)
    except ValueError:
        return None


def query_process_identity(pid: int) -> tuple[str, str]:
    process_path = query_process_path(pid)
    process_name = Path(process_path).name if process_path else ""
    if process_name:
        return process_path, process_name

    try:
        import psutil

        proc = psutil.Process(pid)
        process_name = proc.name()
        try:
            process_path = proc.exe()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            process_path = ""
    except Exception:
        pass
    return process_path, process_name


def query_process_path(pid: int) -> str:
    if os.name != "nt" or not pid:
        return ""
    kernel32 = ctypes.windll.kernel32
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        return buffer.value if ok else ""
    finally:
        kernel32.CloseHandle(handle)
