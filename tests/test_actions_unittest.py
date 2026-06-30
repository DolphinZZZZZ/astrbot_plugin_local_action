import asyncio
import unittest
from pathlib import Path
from unittest import mock

import plugin_test_bootstrap  # noqa: F401
import astrbot_plugin_local_action.actions as actions_mod
from astrbot_plugin_local_action.actions import (
    ActionError,
    ActionResult,
    LocalActionExecutor,
    build_shell_argv,
    discover_available_shells,
)
from astrbot_plugin_local_action.core import normalize_config
from astrbot_plugin_local_action.window_catalog import WindowInfo


class FakeWindowManager:
    def __init__(self, windows):
        self.windows = windows

    def find_one_window(self, selector):
        matches = self.find_windows(selector, limit=1)
        return matches[0] if matches else None

    def find_windows(self, selector, limit=20):
        process = str(selector.get("process") or "").lower()
        return [
            window
            for window in self.windows
            if not process or window.process_name.lower() == process
        ][:limit]

    def list_windows(self):
        return self.windows


class FakeImage:
    def __init__(self):
        self.saved_path = None

    def save(self, path):
        self.saved_path = str(path)
        Path(path).write_bytes(b"fakepng")


class FakeImageGrabber:
    def __init__(self):
        self.calls = []
        self.image = FakeImage()

    def grab(self, bbox=None):
        self.calls.append(bbox)
        return self.image


def make_window(**overrides):
    data = {
        "hwnd": 123,
        "pid": 456,
        "process_name": "Code.exe",
        "process_path": r"C:\Program Files\Code.exe",
        "title": "demo",
        "class_name": "Chrome_WidgetWin_1",
        "left": 10,
        "top": 20,
        "right": 410,
        "bottom": 320,
        "is_visible": True,
        "is_foreground": True,
        "is_minimized": False,
    }
    data.update(overrides)
    return WindowInfo(**data)


class LocalActionExecutorTests(unittest.TestCase):
    def test_read_file_allows_empty_allowed_paths(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.txt"
            target.write_text("hello", encoding="utf-8")
            config = normalize_config(
                {
                    "advanced_settings_enabled": True,
                    "quickaction": {"allowed_paths": [""]},
                }
            )
            executor = LocalActionExecutor(config, temp_dir=tmp)

            result = executor._read_file(str(target), "quickaction")

            self.assertTrue(result.ok)
            self.assertEqual(result.text, "hello")

    def test_read_file_allows_whitelisted_path(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.txt"
            target.write_text("hello", encoding="utf-8")
            config = normalize_config(
                {
                    "advanced_settings_enabled": True,
                    "quickaction": {"allowed_paths": [str(tmp)]},
                }
            )
            executor = LocalActionExecutor(config, temp_dir=tmp)

            result = executor._read_file(str(target), "quickaction")

            self.assertTrue(result.ok)
            self.assertEqual(result.text, "hello")

    def test_read_file_blocks_non_whitelisted_path_when_allowed_paths_is_set(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            allowed_dir = root / "allowed"
            blocked_dir = root / "blocked"
            allowed_dir.mkdir()
            blocked_dir.mkdir()
            target = blocked_dir / "note.txt"
            target.write_text("hello", encoding="utf-8")
            config = normalize_config(
                {
                    "advanced_settings_enabled": True,
                    "quickaction": {"allowed_paths": [str(allowed_dir)]},
                }
            )
            executor = LocalActionExecutor(config, temp_dir=tmp)

            with self.assertRaisesRegex(ActionError, "allowed_paths"):
                executor._read_file(str(target), "quickaction")

    def test_read_file_ignores_allowed_paths_when_advanced_settings_disabled(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            allowed_dir = root / "allowed"
            blocked_dir = root / "blocked"
            allowed_dir.mkdir()
            blocked_dir.mkdir()
            target = blocked_dir / "note.txt"
            target.write_text("hello", encoding="utf-8")
            config = normalize_config(
                {
                    "advanced_settings_enabled": False,
                    "quickaction": {"allowed_paths": [str(allowed_dir)]},
                }
            )
            executor = LocalActionExecutor(config, temp_dir=tmp)

            result = executor._read_file(str(target), "quickaction")

            self.assertTrue(result.ok)
            self.assertEqual(result.text, "hello")

    def test_read_file_allows_sensitive_looking_filename(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "secret.txt"
            target.write_text("hidden", encoding="utf-8")
            config = normalize_config(
                {
                    "advanced_settings_enabled": True,
                    "quickaction": {"allowed_paths": [str(tmp)]},
                }
            )
            executor = LocalActionExecutor(config, temp_dir=tmp)

            result = executor._read_file(str(target), "quickaction")

            self.assertTrue(result.ok)
            self.assertEqual(result.text, "hidden")

    def test_tail_file_limits_to_requested_lines(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "app.log"
            target.write_text("\n".join(str(i) for i in range(10)), encoding="utf-8")
            config = normalize_config(
                {
                    "advanced_settings_enabled": True,
                    "quickaction": {"allowed_paths": [str(tmp)]},
                }
            )
            executor = LocalActionExecutor(config, temp_dir=tmp)

            result = executor._tail_file(str(target), 3, "quickaction")

            self.assertEqual(result.text, "7\n8\n9")

    def test_read_file_uses_global_file_size_limit(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "large.txt"
            target.write_text("ab", encoding="utf-8")
            config = normalize_config(
                {
                    "advanced_settings": {
                        "enabled": True,
                        "max_file_size_mb": 0.000001,
                    },
                    "quickaction": {"allowed_paths": [str(tmp)]},
                }
            )
            executor = LocalActionExecutor(config, temp_dir=tmp)

            with self.assertRaisesRegex(ActionError, "文件超过大小限制：0.001024 KB"):
                executor._read_file(str(target), "quickaction")

    def test_read_file_ignores_file_size_limit_when_advanced_settings_disabled(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "large.txt"
            target.write_text("ab", encoding="utf-8")
            config = normalize_config(
                {
                    "advanced_settings_enabled": False,
                    "max_file_size_mb": 0,
                    "quickaction": {"allowed_paths": [str(tmp)]},
                }
            )
            executor = LocalActionExecutor(config, temp_dir=tmp)

            result = executor._read_file(str(target), "quickaction")

            self.assertTrue(result.ok)
            self.assertEqual(result.text, "ab")

    def test_zero_file_size_limit_blocks_all_files(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.txt"
            target.write_text("a", encoding="utf-8")
            config = normalize_config(
                {
                    "advanced_settings": {
                        "enabled": True,
                        "max_file_size_mb": 0,
                    },
                    "quickaction": {"allowed_paths": [str(tmp)]},
                }
            )
            executor = LocalActionExecutor(config, temp_dir=tmp)

            with self.assertRaisesRegex(ActionError, "文件大小上限为 0，已阻止所有文件。"):
                executor._read_file(str(target), "quickaction")

    def test_negative_file_size_limit_disables_limit(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.txt"
            target.write_text("hello", encoding="utf-8")
            config = normalize_config(
                {
                    "advanced_settings": {
                        "enabled": True,
                        "max_file_size_mb": -1,
                    },
                    "quickaction": {"allowed_paths": [str(tmp)]},
                }
            )
            executor = LocalActionExecutor(config, temp_dir=tmp)

            result = executor._read_file(str(target), "quickaction")

            self.assertEqual(result.text, "hello")

    def test_blank_file_size_limit_disables_limit(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.txt"
            target.write_text("hello", encoding="utf-8")
            config = normalize_config(
                {
                    "advanced_settings": {
                        "enabled": True,
                        "max_file_size_mb": "",
                    },
                    "quickaction": {"allowed_paths": [str(tmp)]},
                }
            )
            executor = LocalActionExecutor(config, temp_dir=tmp)

            result = executor._read_file(str(target), "quickaction")

            self.assertEqual(result.text, "hello")

    def test_dash_file_size_limit_disables_limit(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.txt"
            target.write_text("hello", encoding="utf-8")
            config = normalize_config(
                {
                    "advanced_settings": {
                        "enabled": True,
                        "max_file_size_mb": "-",
                    },
                    "quickaction": {"allowed_paths": [str(tmp)]},
                }
            )
            executor = LocalActionExecutor(config, temp_dir=tmp)

            result = executor._read_file(str(target), "quickaction")

            self.assertEqual(result.text, "hello")

    def test_command_runner_receives_dangerous_looking_command(self):
        calls = []

        async def runner(shell_name, command, timeout):
            calls.append((shell_name, command, timeout))
            return ActionResult(ok=True, text="done")

        config = normalize_config(
            {
                "advanced_settings_enabled": True,
                "quickcommand": {
                    "enabled": True,
                },
            }
        )
        executor = LocalActionExecutor(config, command_runner=runner)

        result = asyncio.run(
            executor._run_command_action(
                {
                    "type": "run_command",
                    "shell": "pwsh",
                    "command": "Remove-Item -Recurse C:\\temp",
                    "timeout": 1,
                }
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(calls, [("pwsh", "Remove-Item -Recurse C:\\temp", 1)])

    def test_command_runner_receives_rule_command(self):
        calls = []

        async def runner(shell_name, command, timeout):
            calls.append((shell_name, command, timeout))
            return ActionResult(ok=True, text="done")

        config = normalize_config(
            {
                "advanced_settings_enabled": True,
                "quickcommand": {
                    "enabled": True,
                },
            }
        )
        executor = LocalActionExecutor(config, command_runner=runner)

        result = asyncio.run(
            executor._run_command_action(
                {
                    "type": "run_command",
                    "shell": "pwsh",
                    "command": "Write-Output ok",
                    "timeout": 5,
                }
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(calls, [("pwsh", "Write-Output ok", 5)])

    def test_command_runner_receives_shell_input_command(self):
        calls = []

        async def runner(shell_name, command, timeout):
            calls.append((shell_name, command, timeout))
            return ActionResult(ok=True, text="done")

        executor = LocalActionExecutor({}, command_runner=runner)

        result = asyncio.run(
            executor.execute(
                "quickcommand",
                {
                    "action": {
                        "type": "run_shell_input",
                        "shell": "cmd",
                        "command": "dir",
                        "timeout": 7,
                    }
                },
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(calls, [("cmd", "dir", 7)])

    def test_build_shell_argv_uses_noninteractive_pwsh(self):
        argv = build_shell_argv("pwsh", "Write-Output ok")

        self.assertEqual(argv[:4], ["pwsh", "-NoProfile", "-NonInteractive", "-ExecutionPolicy"])
        self.assertEqual(argv[-1], "Write-Output ok")

    def test_build_shell_argv_supports_wsl(self):
        argv = build_shell_argv("wsl", "echo ok")

        self.assertEqual(argv, ["wsl", "bash", "-lc", "echo ok"])

    def test_discover_available_shells_returns_shell_metadata(self):
        shells = discover_available_shells()

        self.assertIsInstance(shells, list)
        for item in shells:
            self.assertIn("value", item)
            self.assertIn("label", item)
            self.assertIn("path", item)

    def test_discover_available_shells_uses_known_windows_paths(self):
        def fake_exists(self):
            return str(self) == r"C:\Windows\System32\cmd.exe"

        with mock.patch.object(actions_mod, "os") as os_mock, mock.patch.object(
            actions_mod.shutil, "which", return_value=None
        ), mock.patch.object(actions_mod.Path, "exists", fake_exists):
            os_mock.name = "nt"
            os_mock.environ.get.return_value = None

            shells = discover_available_shells()

        self.assertIn(
            {
                "value": "cmd",
                "label": "Command Prompt",
                "path": r"C:\Windows\System32\cmd.exe",
            },
            shells,
        )

    def test_window_screenshot_uses_matched_window_rect(self):
        import tempfile

        grabber = FakeImageGrabber()
        manager = FakeWindowManager([make_window()])
        with tempfile.TemporaryDirectory() as tmp:
            executor = LocalActionExecutor(
                normalize_config({}),
                temp_dir=tmp,
                window_manager=manager,
                image_grabber=grabber,
            )

            result = executor._screenshot_window({"process": "Code.exe"})

            self.assertTrue(result.ok)
            self.assertEqual(grabber.calls, [(10, 20, 410, 320)])
            self.assertEqual(len(result.images), 1)
            self.assertTrue(Path(result.images[0]).exists())

    def test_window_screenshot_rejects_minimized_window(self):
        grabber = FakeImageGrabber()
        manager = FakeWindowManager([make_window(is_minimized=True)])
        executor = LocalActionExecutor(
            normalize_config({}),
            window_manager=manager,
            image_grabber=grabber,
        )

        result = executor._screenshot_window({"process": "Code.exe"})

        self.assertFalse(result.ok)
        self.assertIn("最小化", result.text)
        self.assertEqual(grabber.calls, [])

    def test_close_process_uses_selector_and_terminator(self):
        calls = []

        def terminator(window, force, include_children):
            calls.append((window.pid, force, include_children))
            return ActionResult(ok=True, text="closed")

        manager = FakeWindowManager([make_window()])
        executor = LocalActionExecutor(
            normalize_config({}),
            window_manager=manager,
            process_terminator=terminator,
        )

        result = executor._close_process({"process": "Code.exe"}, True, True)

        self.assertTrue(result.ok)
        self.assertEqual(calls, [(456, True, True)])

    def test_close_process_does_not_apply_removed_process_protection_list(self):
        calls = []

        def terminator(window, force, include_children):
            calls.append((window.process_name, force, include_children))
            return ActionResult(ok=True, text="closed")

        manager = FakeWindowManager([make_window(process_name="lsass.exe")])
        executor = LocalActionExecutor(
            normalize_config({}),
            window_manager=manager,
            process_terminator=terminator,
        )

        result = executor._close_process({"process": "lsass.exe"}, True, True)

        self.assertTrue(result.ok)
        self.assertEqual(calls, [("lsass.exe", True, True)])


if __name__ == "__main__":
    unittest.main()
