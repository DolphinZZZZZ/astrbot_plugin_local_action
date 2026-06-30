import tempfile
import unittest
from pathlib import Path

import plugin_test_bootstrap  # noqa: F401
from astrbot_plugin_local_action.platform_logs import (
    extract_active_platforms,
    get_platform_scope_info,
)


class PlatformLogDiscoveryTests(unittest.TestCase):
    def test_extracts_active_platforms_from_event_and_session_logs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "backend.log"
            log_path.write_text(
                "\n".join(
                    [
                        "[11:01:51.676] [Core] [INFO] [core.event_bus:79]: "
                        "[default] [AstrBot (qq_official)] user: hi",
                        "[22:55:05.225] [Core] [DBUG] [core.plugin_lifecycle:76]: "
                        "[主动消息] 忽略插件启动前的历史消息时间用于自动主动消息任务喵: "
                        "私聊 webchat!astrbot!263d041f -> 1776930147.2364614",
                        "[01:34:51.676] [Core] [INFO] "
                        "[qqofficial.qqofficial_platform_adapter:131]: "
                        "[QQOfficial] Websocket session starting.",
                    ]
                ),
                encoding="utf-8",
            )

            active = extract_active_platforms([log_path])

        self.assertEqual(active, {"qq_official", "webchat"})

    def test_platform_scope_info_marks_log_matched_options_active(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "backend.log"
            log_path.write_text(
                "[Core] [INFO] [core.event_bus:79]: "
                "[default] [AstrBot (qq_official)] user: hi\n",
                encoding="utf-8",
            )

            info = get_platform_scope_info(
                log_paths=[log_path],
                platform_options=[
                    ("qq_official", "QQ 官方机器人(WebSocket)"),
                    ("webchat", "WebChat"),
                ],
            )

        self.assertEqual(info["active_channels"], ["qq_official"])
        active_by_value = {item["value"]: item["active"] for item in info["options"]}
        self.assertTrue(active_by_value["qq_official"])
        self.assertFalse(active_by_value["webchat"])


if __name__ == "__main__":
    unittest.main()
