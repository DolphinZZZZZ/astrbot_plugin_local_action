from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .window_catalog import (
    LocalWindowManager,
    WindowInfo,
    format_window_info,
    format_window_list,
)


@dataclass
class ActionResult:
    ok: bool
    text: str = ""
    images: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


class ActionError(Exception):
    pass


SHELL_CANDIDATES = (
    ("pwsh", "PowerShell 7"),
    ("powershell", "Windows PowerShell"),
    ("cmd", "Command Prompt"),
    ("bash", "Bash"),
    ("sh", "sh"),
    ("wsl", "WSL"),
)

WINDOWS_SHELL_PATHS = {
    "powershell": (
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        r"C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe",
    ),
    "cmd": (
        r"C:\Windows\System32\cmd.exe",
        r"C:\Windows\SysWOW64\cmd.exe",
    ),
    "wsl": (
        r"C:\Windows\System32\wsl.exe",
    ),
}


def format_file_size_limit(max_file_size_mb: float) -> str:
    if max_file_size_mb >= 1024 and (max_file_size_mb / 1024).is_integer():
        return f"{max_file_size_mb / 1024:g} GB"
    if max_file_size_mb >= 1:
        return f"{max_file_size_mb:g} MB"
    return f"{max_file_size_mb * 1024:g} KB"


class LocalActionExecutor:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        temp_dir: str | Path | None = None,
        command_runner=None,
        window_manager: LocalWindowManager | None = None,
        image_grabber=None,
        process_terminator=None,
    ) -> None:
        self.config = config
        self.temp_dir = Path(temp_dir or Path.cwd() / ".localaction_tmp")
        self.command_runner = command_runner
        self.window_manager = window_manager or LocalWindowManager()
        self.image_grabber = image_grabber
        self.process_terminator = process_terminator

    async def execute(self, mode: str, rule: dict[str, Any]) -> ActionResult:
        action = rule.get("action") or {}
        action_type = str(action.get("type") or "")
        if action_type == "screenshot_fullscreen":
            return await asyncio.to_thread(self._screenshot_fullscreen)
        if action_type == "screenshot_window":
            selector = action.get("selector") or {}
            return await asyncio.to_thread(self._screenshot_window, selector)
        if action_type == "list_windows":
            selector = action.get("selector") or {}
            limit = int(action.get("limit") or 20)
            return await asyncio.to_thread(self._list_windows, selector, limit)
        if action_type == "read_file":
            path = str(action.get("path") or "")
            return await asyncio.to_thread(self._read_file, path, mode)
        if action_type == "tail_file":
            path = str(action.get("path") or "")
            lines = int(action.get("lines") or 100)
            return await asyncio.to_thread(self._tail_file, path, lines, mode)
        if action_type == "send_file":
            path = str(action.get("path") or "")
            self._check_file_safe(path, mode)
            return ActionResult(ok=True, files=[str(Path(path).resolve())])
        if action_type == "run_command":
            return await self._run_command_action(action)
        if action_type == "run_shell_input":
            return await self._run_shell_command(action)
        if action_type == "run_predefined_command":
            command_id = str(action.get("command_id") or "")
            return await self._run_predefined_command(command_id)
        if action_type == "close_process":
            selector = action.get("selector") or {}
            force = bool(action.get("force", True))
            include_children = bool(action.get("include_children", True))
            return await asyncio.to_thread(
                self._close_process,
                selector,
                force,
                include_children,
            )
        return ActionResult(ok=False, text=f"LocalAction 不支持的动作类型：{action_type}")

    def _screenshot_fullscreen(self) -> ActionResult:
        image_grabber = self._get_image_grabber()
        if isinstance(image_grabber, ActionResult):
            return image_grabber

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        path = self.temp_dir / f"localaction_screenshot_{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
        try:
            image = image_grabber.grab()
            image.save(path)
        except Exception as exc:  # pragma: no cover - depends on desktop session
            return ActionResult(ok=False, text=f"截图失败：{exc}")
        return ActionResult(ok=True, images=[str(path.resolve())])

    def _screenshot_window(self, selector: dict[str, Any]) -> ActionResult:
        image_grabber = self._get_image_grabber()
        if isinstance(image_grabber, ActionResult):
            return image_grabber

        window = self.window_manager.find_one_window(selector)
        if not window:
            return ActionResult(ok=False, text="未找到匹配窗口，无法截图。")
        if window.is_minimized:
            return ActionResult(ok=False, text=f"窗口已最小化，无法截图：{format_window_info(window)}")
        if window.width <= 0 or window.height <= 0:
            return ActionResult(ok=False, text=f"窗口区域无效，无法截图：{format_window_info(window)}")

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        path = self.temp_dir / f"localaction_window_{window.pid}_{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
        try:
            image = image_grabber.grab(bbox=window.rect)
            image.save(path)
        except Exception as exc:  # pragma: no cover - depends on desktop session
            return ActionResult(ok=False, text=f"窗口截图失败：{exc}\n{format_window_info(window)}")
        return ActionResult(
            ok=True,
            text=f"已截图匹配窗口：\n{format_window_info(window)}",
            images=[str(path.resolve())],
        )

    def _list_windows(self, selector: dict[str, Any], limit: int) -> ActionResult:
        if selector:
            windows = self.window_manager.find_windows(selector, limit=limit)
        else:
            windows = self.window_manager.list_windows()
        return ActionResult(ok=True, text=format_window_list(windows, limit=limit))

    def _read_file(self, path: str, mode: str) -> ActionResult:
        self._check_file_safe(path, mode)
        data = Path(path).read_text(encoding="utf-8", errors="replace")
        return ActionResult(ok=True, text=data)

    def _tail_file(self, path: str, lines: int, mode: str) -> ActionResult:
        self._check_file_safe(path, mode)
        lines = max(1, min(lines, 2000))
        content = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        return ActionResult(ok=True, text="\n".join(content[-lines:]))

    def _check_file_safe(self, path: str, mode: str) -> None:
        mode_conf = self.config.get(mode, {})
        allowed_paths = []
        if self.config.get("advanced_settings_enabled", False):
            allowed_paths = [
                str(value).strip()
                for value in mode_conf.get("allowed_paths", []) or []
            ]
            allowed_paths = [value for value in allowed_paths if value]

        target = Path(path).expanduser().resolve()
        if not target.exists() or not target.is_file():
            raise ActionError(f"文件不存在：{target}")

        if allowed_paths:
            allowed = False
            for allowed_path in allowed_paths:
                root = Path(allowed_path).expanduser().resolve()
                try:
                    target.relative_to(root)
                    allowed = True
                    break
                except ValueError:
                    continue
            if not allowed:
                raise ActionError(f"文件不在 allowed_paths 白名单内：{target}")

        max_file_size_mb = self._file_size_limit_mb(mode_conf)
        if max_file_size_mb is None:
            return
        max_bytes = int(max_file_size_mb * 1024 * 1024)
        if target.stat().st_size > max_bytes:
            if max_file_size_mb == 0:
                raise ActionError("文件大小上限为 0，已阻止所有文件。")
            raise ActionError(
                f"文件超过大小限制：{format_file_size_limit(max_file_size_mb)}"
            )

    def _file_size_limit_mb(self, mode_conf: dict[str, Any]) -> float | None:
        if not self.config.get("advanced_settings_enabled", False):
            return None
        if "max_file_size_mb" in self.config:
            value = self.config.get("max_file_size_mb")
        else:
            value = mode_conf.get("max_file_size_mb", 50)
        if value is None:
            return None
        text = str(value).strip()
        if not text or text == "-":
            return None
        try:
            limit = float(text)
        except (TypeError, ValueError):
            return 50
        if limit < 0:
            return None
        return limit

    def _close_process(
        self,
        selector: dict[str, Any],
        force: bool,
        include_children: bool,
    ) -> ActionResult:
        window = self.window_manager.find_one_window(selector)
        if not window:
            return ActionResult(ok=False, text="未找到匹配窗口，未关闭进程。")
        if window.pid == os.getpid():
            return ActionResult(ok=False, text="拒绝关闭当前 AstrBot 插件进程。")

        if self.process_terminator:
            return self.process_terminator(window, force, include_children)

        argv = ["taskkill", "/PID", str(window.pid)]
        if include_children:
            argv.append("/T")
        if force:
            argv.append("/F")
        try:
            proc = subprocess.run(
                argv,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
            )
        except FileNotFoundError as exc:
            return ActionResult(ok=False, text=f"taskkill 不可用：{exc}")
        except subprocess.TimeoutExpired:
            return ActionResult(ok=False, text=f"关闭进程超时：PID={window.pid}")
        except Exception as exc:
            return ActionResult(ok=False, text=f"关闭进程失败：{exc}")

        stdout_text = decode_output(proc.stdout)
        stderr_text = decode_output(proc.stderr)
        text_parts = [
            f"已请求关闭进程：{window.process_name or 'unknown'} PID={window.pid}",
            f"返回码：{proc.returncode}",
            format_window_info(window),
        ]
        if stdout_text:
            text_parts.append(f"输出：\n{trim_output(stdout_text)}")
        if stderr_text:
            text_parts.append(f"错误：\n{trim_output(stderr_text)}")
        return ActionResult(ok=proc.returncode == 0, text="\n".join(text_parts))

    async def _run_predefined_command(self, command_id: str) -> ActionResult:
        quickcommand = self.config.get("quickcommand", {})
        commands = quickcommand.get("commands", {}) or {}
        command_conf = commands.get(command_id)
        if not command_conf:
            return ActionResult(ok=False, text=f"未找到预定义 command_id：{command_id}")

        if not str(command_conf.get("command") or "").strip():
            return ActionResult(ok=False, text=f"旧预定义命令为空：{command_id}")
        return await self._run_shell_command(command_conf)

    async def _run_command_action(self, action: dict[str, Any]) -> ActionResult:
        return await self._run_shell_command(action)

    async def _run_shell_command(self, source: dict[str, Any]) -> ActionResult:
        command = str(source.get("command") or "").strip()
        shell_name = str(source.get("shell") or "pwsh").strip() or "pwsh"
        timeout = max(1, int(source.get("timeout") or 10))
        if not command:
            return ActionResult(ok=False, text="执行命令为空。")

        if self.command_runner:
            return await self.command_runner(shell_name, command, timeout)

        argv = build_shell_argv(shell_name, command)
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            return ActionResult(ok=False, text=f"命令执行超时：{timeout} 秒")
        except FileNotFoundError as exc:
            return ActionResult(ok=False, text=f"命令 shell 不存在：{exc}")
        except Exception as exc:
            return ActionResult(ok=False, text=f"命令执行失败：{exc}")

        stdout_text = decode_output(stdout)
        stderr_text = decode_output(stderr)
        text_parts = [f"命令执行完成，返回码：{proc.returncode}"]
        if stdout_text:
            text_parts.append(f"输出：\n{trim_output(stdout_text)}")
        if stderr_text:
            text_parts.append(f"错误：\n{trim_output(stderr_text)}")
        return ActionResult(ok=proc.returncode == 0, text="\n".join(text_parts))

    def _get_image_grabber(self):
        if self.image_grabber:
            return self.image_grabber
        try:
            from PIL import ImageGrab
        except Exception as exc:  # pragma: no cover - depends on runtime packages
            return ActionResult(
                ok=False,
                text=f"截图失败：当前环境无法导入 PIL.ImageGrab（{exc}）。",
            )
        return ImageGrab


def build_shell_argv(shell_name: str, command: str) -> list[str]:
    shell_name = shell_name.lower()
    if shell_name in {"pwsh", "powershell"}:
        executable = "pwsh" if shell_name == "pwsh" else "powershell"
        return [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ]
    if shell_name in {"bash", "sh"}:
        return [shell_name, "-lc", command]
    if shell_name == "wsl":
        return ["wsl", "bash", "-lc", command]
    return [shell_name, command]


def discover_available_shells() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for name, label in SHELL_CANDIDATES:
        path = shutil.which(name) or _known_windows_shell_path(name)
        if not path:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append({"value": name, "label": label, "path": path})
    if not items and os.name == "nt":
        comspec = os.environ.get("COMSPEC")
        if comspec:
            items.append({"value": "cmd", "label": "Command Prompt", "path": comspec})
    return items


def _known_windows_shell_path(name: str) -> str | None:
    if os.name != "nt":
        return None
    for candidate in WINDOWS_SHELL_PATHS.get(name.lower(), ()):
        if Path(candidate).exists():
            return candidate
    return None


def decode_output(data: bytes) -> str:
    for encoding in ("utf-8", "gbk", "utf-16"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").strip()


def trim_output(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[输出已截断]"
