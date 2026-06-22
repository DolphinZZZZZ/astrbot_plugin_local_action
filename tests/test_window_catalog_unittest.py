import unittest

from astrbot_plugin_local_action.window_catalog import (
    LocalWindowManager,
    WindowInfo,
    format_window_list,
    process_name_matches,
    window_matches_selector,
)


def make_window(**overrides):
    data = {
        "hwnd": 100,
        "pid": 200,
        "process_name": "Code.exe",
        "process_path": r"C:\Program Files\Code.exe",
        "title": "main.py - Visual Studio Code",
        "class_name": "Chrome_WidgetWin_1",
        "left": 10,
        "top": 20,
        "right": 810,
        "bottom": 620,
        "is_visible": True,
        "is_foreground": False,
        "is_minimized": False,
    }
    data.update(overrides)
    return WindowInfo(**data)


class WindowCatalogTests(unittest.TestCase):
    def test_process_name_matches_exe_or_stem(self):
        self.assertTrue(process_name_matches("Code.exe", "Code.exe"))
        self.assertTrue(process_name_matches("Code.exe", "code"))
        self.assertFalse(process_name_matches("Code.exe", "Codex"))

    def test_selector_matches_process_title_and_class(self):
        window = make_window()

        self.assertTrue(
            window_matches_selector(
                window,
                {
                    "process": "code",
                    "title_contains": "Visual Studio",
                    "class": "Chrome_WidgetWin_1",
                },
            )
        )

    def test_selector_rejects_hidden_by_default(self):
        window = make_window(is_visible=False)

        self.assertFalse(window_matches_selector(window, {"process": "Code.exe"}))
        self.assertTrue(
            window_matches_selector(
                window,
                {"process": "Code.exe", "include_hidden": True},
            )
        )

    def test_condition_class_and_title_uses_regex_or_contains(self):
        window = make_window()

        self.assertTrue(
            window_matches_selector(
                window,
                {
                    "process": "Code.exe",
                    "condition": "classAndTitle",
                    "condition_class": "Chrome_WidgetWin_\\d",
                    "condition_title": "main\\.py",
                },
            )
        )

    def test_find_windows_returns_limited_matches(self):
        manager = LocalWindowManager()
        windows = [
            make_window(hwnd=1, process_name="Code.exe"),
            make_window(hwnd=2, process_name="notepad.exe", title="notes"),
            make_window(hwnd=3, process_name="Code.exe", title="settings"),
        ]

        matches = manager.find_windows({"process": "Code.exe"}, windows=windows, limit=1)

        self.assertEqual([item.hwnd for item in matches], [1])

    def test_format_window_list_exposes_process_pid_hwnd_and_title(self):
        text = format_window_list([make_window(hwnd=255)], limit=5)

        self.assertIn("Code.exe", text)
        self.assertIn("PID=200", text)
        self.assertIn("HWND=0xff", text)
        self.assertIn("main.py - Visual Studio Code", text)


if __name__ == "__main__":
    unittest.main()
