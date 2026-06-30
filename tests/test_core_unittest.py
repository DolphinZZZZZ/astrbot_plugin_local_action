import unittest

import plugin_test_bootstrap  # noqa: F401
from astrbot_plugin_local_action.core import (
    EventView,
    LocalActionRouter,
    SleepEntry,
    SleepState,
    get_channel_type,
    parse_duration,
)
from astrbot_plugin_local_action.defaults import DEFAULT_CONFIG


def make_event(message: str, *, admin: bool = True, platform: str = "webchat") -> EventView:
    return EventView(
        message=message,
        sender_id="10001",
        platform_name=platform,
        channel_type=get_channel_type(platform),
        is_admin=admin,
        unified_msg_origin=f"{platform}:FriendMessage:10001",
    )


class LocalActionRouterTests(unittest.TestCase):
    def test_default_quickcommand_has_no_rules_or_commands(self):
        quickcommand = DEFAULT_CONFIG["quickcommand"]

        self.assertEqual(quickcommand["rules"], [])
        self.assertEqual(quickcommand["commands"], {})
        self.assertEqual(
            quickcommand["ssh_mode"],
            {
                "enabled": False,
                "trigger_keywords": ["ssh"],
                "exit_keywords": ["exit", "退出"],
                "match_mode": "exact",
                "shell": "pwsh",
                "timeout": 1000,
            },
        )

        router = LocalActionRouter({"quickcommand": {"enabled": True}})
        decision = router.route(make_event("关闭微信后台"))

        self.assertFalse(decision.handled)

    def test_default_advanced_settings_and_sleep_wake_values(self):
        self.assertFalse(DEFAULT_CONFIG["advanced_settings_enabled"])
        self.assertEqual(DEFAULT_CONFIG["sleep_wake"]["default_sleep_seconds"], 3600)

    def test_quickcommand_legacy_non_command_action_becomes_draft(self):
        router = LocalActionRouter(
            {
                "quickcommand": {
                    "enabled": True,
                    "rules": [
                        {
                            "command_name": "旧动作",
                            "trigger_keywords": ["旧动作"],
                            "match_mode": "exact",
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ],
                },
            }
        )

        rule = router.config["quickcommand"]["rules"][0]
        self.assertEqual(
            rule["action"],
            {"type": "run_command", "shell": "pwsh", "command": "", "timeout": 10},
        )
        self.assertFalse(router.route(make_event("旧动作")).handled)

    def test_ui_only_settings_entry_is_removed_from_runtime_config(self):
        router = LocalActionRouter(
            {
                "__localaction_settings_entry": "打开",
                "__localaction_plugin_ui_notice": {},
            }
        )

        self.assertNotIn("__localaction_settings_entry", router.config)
        self.assertNotIn("__localaction_plugin_ui_notice", router.config)

    def test_default_screenshot_keyword_routes_to_action(self):
        router = LocalActionRouter()

        decision = router.route(make_event("当前屏幕截图发给我"))

        self.assertTrue(decision.handled)
        self.assertTrue(decision.should_stop)
        self.assertEqual(decision.mode, "quickaction")
        self.assertEqual(decision.action, {"type": "screenshot_fullscreen"})
        self.assertEqual(decision.rule["name"], "屏幕截图")
        self.assertEqual(decision.rule["action_name"], "屏幕截图")

    def test_quickaction_rule_routes_to_action(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickaction_rule_channel_scope_enabled": True,
                },
                "quickaction": {
                    "rules": [
                        {
                            "action_name": "当前窗口截图",
                            "trigger_keywords": ["当前窗口截图"],
                            "match_mode": "exact",
                            "action": {
                                "type": "screenshot_window",
                                "selector": {"foreground": True},
                            },
                        }
                    ]
                },
            }
        )

        decision = router.route(make_event("当前窗口截图"))

        self.assertTrue(decision.handled)
        self.assertEqual(decision.mode, "quickaction")
        self.assertEqual(decision.rule["action_name"], "当前窗口截图")
        self.assertEqual(decision.rule["name"], "当前窗口截图")
        self.assertEqual(decision.action["type"], "screenshot_window")
        self.assertEqual(decision.action["selector"], {"foreground": True})

    def test_disabled_rule_is_skipped(self):
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "quickaction": {
                    "rules": [
                        {
                            "enabled": False,
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ]
                },
            }
        )

        decision = router.route(make_event("屏幕截图"))

        self.assertFalse(decision.handled)

    def test_rule_enabled_defaults_true_for_legacy_config(self):
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "quickaction": {
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ]
                },
            }
        )

        self.assertTrue(router.config["quickaction"]["rules"][0]["enabled"])
        self.assertTrue(router.route(make_event("屏幕截图")).handled)

    def test_non_admin_is_stopped_with_permission_message(self):
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "quickaction": {
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ]
                },
            }
        )

        decision = router.route(make_event("屏幕截图", admin=False))

        self.assertTrue(decision.handled)
        self.assertTrue(decision.should_stop)
        self.assertIn("仅管理员", decision.response_text)

    def test_sleep_command_without_target_suppresses_all_until_wake(self):
        now = 1000.0
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "sleep_wake": {"sleep_match_mode": "prefix"},
                "quickaction": {
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ]
                },
            },
            now_func=lambda: now,
        )

        sleep_decision = router.route(make_event("休眠 30秒"))
        blocked_decision = router.route(make_event("屏幕截图"))
        wake_decision = router.route(make_event("唤醒"))
        action_decision = router.route(make_event("屏幕截图"))

        self.assertTrue(sleep_decision.handled)
        self.assertFalse(blocked_decision.handled)
        self.assertIn("已唤醒", wake_decision.response_text)
        self.assertTrue(action_decision.handled)
        self.assertEqual(action_decision.action["type"], "screenshot_fullscreen")

    def test_sleep_command_with_legacy_target_suppresses_all_until_wake(self):
        now = 1000.0
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "sleep_wake": {"sleep_match_mode": "prefix"},
                "quickaction": {
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ]
                },
            },
            now_func=lambda: now,
        )

        sleep_decision = router.route(make_event("休眠 QuickAction 30秒"))
        blocked_decision = router.route(make_event("屏幕截图"))
        wake_decision = router.route(make_event("唤醒 QuickAction"))
        action_decision = router.route(make_event("屏幕截图"))

        self.assertTrue(sleep_decision.handled)
        self.assertIn("已休眠全部", sleep_decision.response_text)
        self.assertFalse(blocked_decision.handled)
        self.assertIn("已唤醒全部", wake_decision.response_text)
        self.assertTrue(action_decision.handled)
        self.assertEqual(action_decision.action["type"], "screenshot_fullscreen")

    def test_sleep_match_mode_defaults_to_exact(self):
        router = LocalActionRouter({"advanced_settings_enabled": True})

        exact_decision = router.route(make_event("休眠"))
        prefix_decision = router.route(make_event("休眠 30秒"))
        contains_decision = router.route(make_event("请休眠"))

        self.assertEqual(router.config["sleep_wake"]["sleep_match_mode"], "exact")
        self.assertTrue(exact_decision.handled)
        self.assertFalse(prefix_decision.handled)
        self.assertFalse(contains_decision.handled)

    def test_sleep_match_mode_prefix_accepts_duration_argument(self):
        now = 1000.0
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "sleep_wake": {"sleep_match_mode": "prefix"},
            },
            now_func=lambda: now,
        )

        decision = router.route(make_event("休眠 30秒"))

        self.assertTrue(decision.handled)
        self.assertIn("30 秒", decision.response_text)

    def test_sleep_match_mode_contains_can_match_inside_message(self):
        now = 1000.0
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "sleep_wake": {
                    "sleep_match_mode": "contains",
                    "sleep_keywords": ["休眠"],
                },
            },
            now_func=lambda: now,
        )

        decision = router.route(make_event("请休眠 30秒"))

        self.assertTrue(decision.handled)
        self.assertIn("30 秒", decision.response_text)

    def test_sleep_match_mode_regex_uses_text_after_match(self):
        now = 1000.0
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "sleep_wake": {
                    "sleep_match_mode": "regex",
                    "sleep_keywords": [r"^请休眠\s*"],
                },
            },
            now_func=lambda: now,
        )

        decision = router.route(make_event("请休眠 2秒"))

        self.assertTrue(decision.handled)
        self.assertIn("2 秒", decision.response_text)

    def test_sleep_keyword_takes_precedence_over_quickaction_keyword(self):
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "sleep_wake": {
                    "sleep_match_mode": "exact",
                    "sleep_keywords": ["屏幕截图"],
                },
                "quickaction": {
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ]
                },
            }
        )

        decision = router.route(make_event("屏幕截图"))

        self.assertTrue(decision.handled)
        self.assertTrue(decision.should_stop)
        self.assertIsNone(decision.action)
        self.assertIn("已休眠", decision.response_text)

    def test_sleep_status_reports_global_without_independent_sleep(self):
        now = 1000.0
        router = LocalActionRouter(
            {"advanced_settings_enabled": True},
            now_func=lambda: now,
        )

        router.route(make_event("永久休眠"))
        decision = router.route(make_event("休眠状态"))

        self.assertIn("全局：永久休眠", decision.response_text)
        self.assertNotIn("QuickCommand Mode", decision.response_text)
        self.assertNotIn("QuickAction Mode", decision.response_text)
        self.assertNotIn("规则：", decision.response_text)

    def test_default_status_keyword_only_uses_sleep_status(self):
        router = LocalActionRouter({"advanced_settings_enabled": True})

        self.assertEqual(router.config["sleep_wake"]["status_keywords"], ["休眠状态"])
        self.assertTrue(router.route(make_event("休眠状态")).handled)
        self.assertFalse(router.route(make_event("LocalAction状态")).handled)

    def test_legacy_default_status_keyword_migrates_to_sleep_status_only(self):
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "sleep_wake": {
                    "sleep_match_mode": "prefix",
                    "status_keywords": ["休眠状态", "LocalAction状态"],
                    "persist_sleep_state": False,
                    "allow_global_sleep": False,
                },
            }
        )

        self.assertEqual(router.config["sleep_wake"]["status_keywords"], ["休眠状态"])
        self.assertTrue(router.config["sleep_wake"]["persist_sleep_state"])
        self.assertTrue(router.config["sleep_wake"]["allow_global_sleep"])
        self.assertTrue(router.route(make_event("休眠 30秒")).handled)

    def test_sleep_wake_is_ignored_when_advanced_settings_disabled(self):
        router = LocalActionRouter({"advanced_settings_enabled": False})

        sleep_decision = router.route(make_event("休眠 不存在目标 30秒"))
        action_decision = router.route(make_event("屏幕截图"))

        self.assertFalse(sleep_decision.handled)
        self.assertTrue(action_decision.handled)
        self.assertEqual(action_decision.action["type"], "screenshot_fullscreen")

    def test_existing_sleep_state_is_ignored_when_advanced_settings_disabled(self):
        now = 1000.0
        router = LocalActionRouter(
            {"advanced_settings_enabled": False},
            now_func=lambda: now,
            sleep_state=SleepState(global_state=SleepEntry(forever=True)),
        )

        decision = router.route(make_event("屏幕截图"))

        self.assertTrue(router.sleep_state.is_global_sleeping(now))
        self.assertTrue(decision.handled)
        self.assertEqual(decision.action["type"], "screenshot_fullscreen")

    def test_legacy_independent_sleep_state_is_discarded(self):
        state = SleepState.from_json(
            {
                "global": {},
                "modes": {"quickaction": {"forever": True}},
                "rules": {"屏幕截图": {"forever": True}},
            }
        )
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "quickaction": {
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ]
                },
            },
            sleep_state=state,
        )

        decision = router.route(make_event("屏幕截图"))

        self.assertTrue(decision.handled)
        self.assertFalse(router.sleep_state.is_mode_sleeping("quickaction"))
        self.assertFalse(router.sleep_state.is_rule_sleeping("屏幕截图"))
        self.assertEqual(router.sleep_state.to_json()["modes"], {})
        self.assertEqual(router.sleep_state.to_json()["rules"], {})

    def test_quickcommand_requires_confirmation_then_routes_action(self):
        now = 1000.0
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "quickcommand": {
                    "enabled": True,
                    "channel_scope": {"mode": "global"},
                    "rules": [
                        {
                            "command_name": "关闭微信后台",
                            "trigger_keywords": ["关闭微信后台"],
                            "match_mode": "exact",
                            "action": {
                                "type": "run_command",
                                "shell": "pwsh",
                                "command": "Write-Output ok",
                                "timeout": 5,
                            },
                        }
                    ],
                },
            },
            now_func=lambda: now,
        )

        ask = router.route(make_event("关闭微信后台"))
        confirmed = router.route(make_event("确认"))

        self.assertIn("请求确认", ask.response_text)
        self.assertTrue(confirmed.handled)
        self.assertEqual(confirmed.action["type"], "run_command")
        self.assertEqual(confirmed.action["command"], "Write-Output ok")

    def test_notice_template_is_configured_per_mode(self):
        router = LocalActionRouter(
            {
                "quickaction": {
                    "notice_template": "QA:{action_name}",
                },
                "quickcommand": {
                    "enabled": True,
                    "notice_template": "QC:{action_name}",
                    "channel_scope": {"mode": "global"},
                    "confirm": {"enabled": False},
                    "rules": [
                        {
                            "command_name": "关闭微信后台",
                            "trigger_keywords": ["关闭微信后台"],
                            "match_mode": "exact",
                            "action": {
                                "type": "run_command",
                                "shell": "pwsh",
                                "command": "Write-Output ok",
                            },
                        }
                    ],
                },
            }
        )

        quickaction = router.route(make_event("屏幕截图"))
        quickcommand = router.route(make_event("关闭微信后台"))

        self.assertEqual(quickaction.notice_text, "QA:屏幕截图")
        self.assertEqual(quickcommand.notice_text, "QC:关闭微信后台")
        self.assertEqual(
            router.action_finished_text(
                quickcommand.rule,
                "done",
                mode=quickcommand.mode,
            ),
            "QC:关闭微信后台\ndone",
        )

    def test_quickcommand_default_notice_uses_command_name(self):
        router = LocalActionRouter(
            {
                "quickcommand": {
                    "enabled": True,
                    "channel_scope": {"mode": "global"},
                    "confirm": {"enabled": False},
                    "rules": [
                        {
                            "command_name": "关闭微信后台",
                            "trigger_keywords": ["关闭微信后台"],
                            "match_mode": "exact",
                            "action": {
                                "type": "run_command",
                                "shell": "pwsh",
                                "command": "Write-Output ok",
                            },
                        }
                    ],
                },
            }
        )

        decision = router.route(make_event("关闭微信后台"))

        self.assertIn("执行命令：关闭微信后台", decision.notice_text)
        self.assertEqual(decision.rule["command_name"], "关闭微信后台")
        self.assertEqual(
            router.config["quickcommand"]["notice_template"],
            "已由本地插件 LocalAction 执行命令：{command_name}，未调用大模型。",
        )

    def test_quickcommand_rule_uses_command_name_field(self):
        router = LocalActionRouter(
            {
                "quickcommand": {
                    "enabled": True,
                    "channel_scope": {"mode": "global"},
                    "confirm": {"enabled": False},
                    "rules": [
                        {
                            "command_name": "关微信",
                            "trigger_keywords": ["关微信"],
                            "match_mode": "exact",
                            "action": {
                                "type": "run_command",
                                "shell": "pwsh",
                                "command": "Write-Output ok",
                                "timeout": 5,
                            },
                        }
                    ],
                },
            }
        )

        decision = router.route(make_event("关微信"))

        self.assertTrue(decision.handled)
        self.assertEqual(decision.rule["command_name"], "关微信")
        self.assertEqual(decision.rule["name"], "关微信")
        self.assertIn("执行命令：关微信", decision.notice_text)

    def test_quickcommand_confirmation_rejects_wrong_text(self):
        now = 1000.0
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "quickcommand": {
                    "enabled": True,
                    "channel_scope": {"mode": "global"},
                    "rules": [
                        {
                            "command_name": "关闭微信后台",
                            "trigger_keywords": ["关闭微信后台"],
                            "match_mode": "exact",
                            "action": {
                                "type": "run_command",
                                "shell": "pwsh",
                                "command": "Write-Output ok",
                            },
                        }
                    ],
                },
            },
            now_func=lambda: now,
        )

        router.route(make_event("关闭微信后台"))
        decision = router.route(make_event("好"))

        self.assertTrue(decision.handled)
        self.assertIn("确认语不匹配", decision.response_text)

    def test_quickcommand_ssh_mode_enters_executes_and_exits(self):
        now = 1000.0

        def current_time():
            return now

        router = LocalActionRouter(
            {
                "quickcommand": {
                    "enabled": True,
                    "admin_only": True,
                    "channel_scope": {"mode": "global"},
                    "ssh_mode": {
                        "enabled": True,
                        "trigger_keywords": ["shell"],
                        "exit_keywords": ["exit"],
                        "match_mode": "exact",
                        "shell": "cmd",
                        "timeout": 9,
                    },
                    "rules": [],
                },
            },
            now_func=current_time,
        )

        enter = router.route(make_event("shell"))
        command = router.route(make_event("echo ok"))
        exit_decision = router.route(make_event("exit"))

        self.assertTrue(enter.handled)
        self.assertIn("Shell 会话模式已进入", enter.response_text)
        self.assertTrue(command.handled)
        self.assertEqual(command.action["type"], "run_shell_input")
        self.assertEqual(command.action["shell"], "cmd")
        self.assertEqual(command.action["command"], "echo ok")
        self.assertEqual(command.action["timeout"], 9)
        self.assertEqual(command.rule["action"], command.action)
        self.assertIn("Shell 会话模式执行命令", command.notice_text)
        self.assertTrue(exit_decision.handled)
        self.assertIn("Shell 会话模式已退出", exit_decision.response_text)

    def test_quickcommand_ssh_mode_defaults_to_1000_seconds(self):
        router = LocalActionRouter(
            {
                "quickcommand": {
                    "enabled": True,
                    "admin_only": False,
                    "channel_scope": {"mode": "global"},
                    "ssh_mode": {"enabled": True},
                    "rules": [],
                },
            }
        )

        enter = router.route(make_event("ssh", admin=False))
        command = router.route(make_event("echo ok", admin=False))

        self.assertTrue(enter.handled)
        self.assertIn("1000 秒内无消息", enter.response_text)
        self.assertEqual(command.action["timeout"], 1000)

    def test_quickcommand_ssh_mode_timeout_exits_without_execution(self):
        now = 1000.0

        def current_time():
            return now

        router = LocalActionRouter(
            {
                "quickcommand": {
                    "enabled": True,
                    "channel_scope": {"mode": "global"},
                    "ssh_mode": {
                        "enabled": True,
                        "trigger_keywords": ["shell"],
                        "exit_keywords": ["exit"],
                        "match_mode": "exact",
                        "timeout": 5,
                    },
                    "rules": [],
                },
            },
            now_func=current_time,
        )

        router.route(make_event("shell"))
        now = 1006.0
        decision = router.route(make_event("echo late"))

        self.assertTrue(decision.handled)
        self.assertIsNone(decision.action)
        self.assertIn("Shell 会话模式已超时退出", decision.response_text)

    def test_quickcommand_ssh_mode_respects_admin_and_channel_scope(self):
        router = LocalActionRouter(
            {
                "quickcommand": {
                    "enabled": True,
                    "admin_only": True,
                    "sync_with_quickaction_channel_scope": False,
                    "channel_scope": {"mode": "include", "include_channels": ["qq"]},
                    "ssh_mode": {
                        "enabled": True,
                        "trigger_keywords": ["shell"],
                    },
                    "rules": [],
                },
            }
        )

        web_decision = router.route(make_event("shell", platform="webchat"))
        non_admin = router.route(make_event("shell", platform="qq", admin=False))

        self.assertFalse(web_decision.handled)
        self.assertTrue(non_admin.handled)
        self.assertIn("仅管理员可用", non_admin.response_text)

    def test_channel_scope_blocks_unmatched_channel(self):
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "quickaction": {
                    "channel_scope": {
                        "mode": "include",
                        "include_channels": ["qq"],
                    }
                },
            }
        )

        decision = router.route(make_event("屏幕截图", platform="webchat"))

        self.assertFalse(decision.handled)

    def test_rule_channel_scope_is_ignored_until_enabled(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickaction_rule_channel_scope_enabled": True,
                },
                "quickaction": {
                    "channel_scope": {"mode": "global"},
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "use_channel_scope": False,
                            "channel_scope": {
                                "mode": "include",
                                "include_channels": ["qq"],
                            },
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ],
                },
            }
        )

        decision = router.route(make_event("屏幕截图", platform="webchat"))

        self.assertTrue(decision.handled)

    def test_rule_channel_scope_is_ignored_even_when_legacy_switch_enabled(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickaction_rule_channel_scope_enabled": True,
                },
                "quickaction": {
                    "channel_scope": {"mode": "global"},
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "use_channel_scope": True,
                            "channel_scope": {
                                "mode": "include",
                                "include_channels": ["qq"],
                            },
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ],
                },
            }
        )

        decision = router.route(make_event("屏幕截图", platform="webchat"))

        self.assertTrue(decision.handled)

    def test_rule_channel_scope_cannot_override_parent_scope_in_this_version(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickaction_rule_channel_scope_enabled": True,
                },
                "quickaction": {
                    "channel_scope": {
                        "mode": "include",
                        "include_channels": ["qq"],
                    },
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "use_channel_scope": True,
                            "channel_scope": {"mode": "global"},
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ],
                },
            }
        )

        decision = router.route(make_event("屏幕截图", platform="webchat"))

        self.assertFalse(decision.handled)

    def test_legacy_rule_channel_scope_does_not_enable_rule_override(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickaction_rule_channel_scope_enabled": True,
                },
                "quickaction": {
                    "channel_scope": {"mode": "global"},
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "channel_scope": {
                                "mode": "include",
                                "include_channels": ["qq"],
                            },
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ],
                },
            }
        )

        decision = router.route(make_event("屏幕截图", platform="webchat"))

        self.assertTrue(router.config["quickaction"]["rules"][0]["use_channel_scope"])
        self.assertTrue(decision.handled)

    def test_nested_advanced_settings_enable_runtime_advanced_config(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickaction": {
                        "channel_scope": {
                            "mode": "include",
                            "include_channels": ["qq"],
                        }
                    },
                }
            }
        )

        decision = router.route(make_event("屏幕截图", platform="webchat"))

        self.assertTrue(router.config["advanced_settings_enabled"])
        self.assertFalse(decision.handled)

    def test_nested_advanced_settings_file_size_limit_is_global(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "max_file_size_mb": 12,
                }
            }
        )

        self.assertEqual(router.config["max_file_size_mb"], 12)
        self.assertNotIn("max_file_size_mb", router.config["quickaction"])

    def test_legacy_quickaction_file_size_limit_migrates_to_global(self):
        router = LocalActionRouter(
            {
                "quickaction": {
                    "max_file_size_mb": 8,
                }
            }
        )

        self.assertEqual(router.config["max_file_size_mb"], 8)
        self.assertNotIn("max_file_size_mb", router.config["quickaction"])

    def test_legacy_plugin_channel_scope_is_ignored(self):
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "channel_scope": {
                    "mode": "include",
                    "include_channels": ["qq"],
                    "exclude_channels": [],
                    "platform_names": [],
                },
                "quickaction": {
                    "channel_scope": {
                        "mode": "global",
                        "include_channels": ["qq", "web", "client", "other"],
                        "exclude_channels": [],
                        "platform_names": [],
                    }
                },
            }
        )

        decision = router.route(make_event("屏幕截图", platform="webchat"))

        self.assertNotIn("channel_scope", router.config)
        self.assertTrue(decision.handled)
        self.assertEqual(decision.mode, "quickaction")

    def test_legacy_quickshot_config_migrates_to_quickaction(self):
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "quickshot": {
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ]
                },
            }
        )

        decision = router.route(make_event("屏幕截图"))

        self.assertNotIn("quickshot", router.config)
        self.assertTrue(decision.handled)
        self.assertEqual(decision.mode, "quickaction")

    def test_duration_parser(self):
        self.assertEqual(parse_duration("30秒"), 30)
        self.assertEqual(parse_duration("60s"), 60)
        self.assertEqual(parse_duration("5分钟"), 300)
        self.assertEqual(parse_duration("2h"), 7200)

    def test_legacy_quickcommand_basic_enabled_still_enables_quickcommand(self):
        router = LocalActionRouter(
            {
                "advanced_settings_enabled": True,
                "quickcommand_basic_enabled": True,
            }
        )

        self.assertTrue(router.config["quickcommand"]["enabled"])

    def test_legacy_basic_settings_migrate_without_top_level_config(self):
        router = LocalActionRouter(
            {
                "notice_template": "旧模板:{action_name}",
                "basic_trigger_keywords": ["旧截图"],
                "basic_admin_only": False,
                "basic_confirm_text": "同意",
                "quickcommand": {
                    "enabled": True,
                    "channel_scope": {"mode": "global"},
                },
            }
        )

        self.assertNotIn("notice_template", router.config)
        self.assertNotIn("basic_trigger_keywords", router.config)
        self.assertNotIn("basic_admin_only", router.config)
        self.assertNotIn("basic_confirm_text", router.config)
        self.assertFalse(router.config["quickaction"]["admin_only"])
        self.assertEqual(
            router.config["quickaction"]["rules"][0]["trigger_keywords"],
            ["旧截图"],
        )
        self.assertEqual(router.config["quickaction"]["confirm"]["confirm_text"], "同意")
        self.assertEqual(router.config["quickcommand"]["confirm"]["confirm_text"], "同意")
        self.assertEqual(
            router.config["quickaction"]["notice_template"],
            "旧模板:{action_name}",
        )
        self.assertEqual(
            router.config["quickcommand"]["notice_template"],
            "旧模板:{action_name}",
        )
        self.assertTrue(router.route(make_event("旧截图", admin=False)).handled)

    def test_include_channel_scope_defaults_to_empty_selection(self):
        router = LocalActionRouter(
            {
                "quickaction": {
                    "channel_scope": {"mode": "include"},
                },
            }
        )

        self.assertEqual(
            router.config["quickaction"]["channel_scope"]["include_channels"],
            [],
        )
        self.assertFalse(router.route(make_event("屏幕截图", platform="webchat")).handled)

    def test_qq_official_platform_maps_to_qq_channel(self):
        self.assertEqual(get_channel_type("qq_official"), "qq")
        router = LocalActionRouter(
            {
                "quickaction": {
                    "channel_scope": {
                        "mode": "include",
                        "include_channels": ["qq"],
                    }
                }
            }
        )

        self.assertTrue(router.route(make_event("屏幕截图", platform="qq_official")).handled)

    def test_platform_type_channel_scope_matches_exact_platform(self):
        router = LocalActionRouter(
            {
                "quickaction": {
                    "channel_scope": {
                        "mode": "include",
                        "include_channels": ["qq_official"],
                    }
                }
            }
        )

        self.assertTrue(router.route(make_event("屏幕截图", platform="qq_official")).handled)
        self.assertFalse(router.route(make_event("屏幕截图", platform="webchat")).handled)

    def test_exclude_channel_scope_defaults_to_empty_and_blocks_selected_channels(self):
        allow_router = LocalActionRouter(
            {
                "quickaction": {
                    "channel_scope": {"mode": "exclude"},
                },
            }
        )
        block_router = LocalActionRouter(
            {
                "quickaction": {
                    "channel_scope": {
                        "mode": "exclude",
                        "exclude_channels": ["web"],
                    },
                },
            }
        )

        self.assertEqual(
            allow_router.config["quickaction"]["channel_scope"]["exclude_channels"],
            [],
        )
        self.assertTrue(allow_router.route(make_event("屏幕截图", platform="webchat")).handled)
        self.assertFalse(block_router.route(make_event("屏幕截图", platform="webchat")).handled)

    def test_custom_channel_scope_only_matches_platform_names(self):
        router = LocalActionRouter(
            {
                "quickaction": {
                    "channel_scope": {
                        "mode": "custom",
                        "include_channels": ["web"],
                        "platform_names": ["webchat"],
                    },
                },
            }
        )
        missed = LocalActionRouter(
            {
                "quickaction": {
                    "channel_scope": {
                        "mode": "custom",
                        "include_channels": ["web"],
                        "platform_names": ["desktop"],
                    },
                },
            }
        )

        self.assertTrue(router.route(make_event("屏幕截图", platform="webchat")).handled)
        self.assertFalse(missed.route(make_event("屏幕截图", platform="webchat")).handled)

    def test_legacy_channels_field_migrates_by_mode(self):
        include_router = LocalActionRouter(
            {
                "quickaction": {
                    "channel_scope": {"mode": "include", "channels": ["qq"]},
                },
            }
        )
        exclude_router = LocalActionRouter(
            {
                "quickaction": {
                    "channel_scope": {"mode": "exclude", "channels": ["web"]},
                },
            }
        )

        self.assertNotIn("channels", include_router.config["quickaction"]["channel_scope"])
        self.assertEqual(
            include_router.config["quickaction"]["channel_scope"]["include_channels"],
            ["qq"],
        )
        self.assertEqual(
            exclude_router.config["quickaction"]["channel_scope"]["exclude_channels"],
            ["web"],
        )

    def test_quickcommand_channel_scope_syncs_from_quickaction_when_enabled(self):
        router = LocalActionRouter(
            {
                "quickaction": {
                    "channel_scope": {
                        "mode": "custom",
                        "platform_names": ["webchat"],
                    },
                },
                "quickcommand": {
                    "sync_with_quickaction_channel_scope": True,
                    "channel_scope": {
                        "mode": "include",
                        "include_channels": ["qq"],
                    },
                },
            }
        )

        self.assertTrue(
            router.config["quickcommand"]["sync_with_quickaction_channel_scope"]
        )
        self.assertEqual(
            router.config["quickcommand"]["channel_scope"],
            router.config["quickaction"]["channel_scope"],
        )
        self.assertEqual(
            router.config["quickcommand"]["channel_scope"]["platform_names"],
            ["webchat"],
        )

    def test_quickcommand_channel_scope_sync_is_enabled_by_default(self):
        router = LocalActionRouter(
            {
                "quickaction": {
                    "channel_scope": {
                        "mode": "custom",
                        "platform_names": ["webchat"],
                    },
                },
                "quickcommand": {
                    "channel_scope": {
                        "mode": "include",
                        "include_channels": ["qq"],
                    },
                },
            }
        )

        self.assertTrue(
            router.config["quickcommand"]["sync_with_quickaction_channel_scope"]
        )
        self.assertEqual(
            router.config["quickcommand"]["channel_scope"],
            router.config["quickaction"]["channel_scope"],
        )

    def test_quickcommand_channel_scope_keeps_own_value_when_sync_disabled(self):
        router = LocalActionRouter(
            {
                "quickaction": {
                    "channel_scope": {
                        "mode": "custom",
                        "platform_names": ["webchat"],
                    },
                },
                "quickcommand": {
                    "sync_with_quickaction_channel_scope": False,
                    "channel_scope": {
                        "mode": "include",
                        "include_channels": ["qq"],
                    },
                },
            }
        )

        self.assertFalse(
            router.config["quickcommand"]["sync_with_quickaction_channel_scope"]
        )
        self.assertNotEqual(
            router.config["quickcommand"]["channel_scope"],
            router.config["quickaction"]["channel_scope"],
        )
        self.assertEqual(
            router.config["quickcommand"]["channel_scope"]["include_channels"],
            ["qq"],
        )

    def test_quickaction_rule_confirm_is_ignored_until_advanced_switch_enabled(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickaction_rule_confirm_enabled": False,
                },
                "quickaction": {
                    "channel_scope": {"mode": "global"},
                    "confirm": {"enabled": False},
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "confirm": {
                                "enabled": True,
                                "confirm_text": "确认截图",
                            },
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ],
                },
            }
        )

        decision = router.route(make_event("屏幕截图"))

        self.assertFalse(router.config["quickaction"]["rules"][0]["__allow_rule_confirm"])
        self.assertTrue(decision.handled)
        self.assertEqual(decision.action["type"], "screenshot_fullscreen")

    def test_quickaction_rule_confirm_is_ignored_even_when_legacy_switch_enabled(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickaction_rule_confirm_enabled": True,
                },
                "quickaction": {
                    "channel_scope": {"mode": "global"},
                    "confirm": {"enabled": False},
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "confirm": {
                                "enabled": True,
                                "confirm_text": "确认截图",
                            },
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ],
                },
            }
        )

        decision = router.route(make_event("屏幕截图"))

        self.assertFalse(router.config["quickaction"]["rules"][0]["__allow_rule_confirm"])
        self.assertTrue(decision.handled)
        self.assertEqual(decision.action["type"], "screenshot_fullscreen")

    def test_quickaction_rule_channel_scope_is_ignored_until_advanced_switch_enabled(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickaction_rule_channel_scope_enabled": False,
                },
                "quickaction": {
                    "channel_scope": {"mode": "global"},
                    "confirm": {"enabled": False},
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "use_channel_scope": True,
                            "channel_scope": {
                                "mode": "include",
                                "include_channels": ["qq"],
                            },
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ],
                },
            }
        )

        decision = router.route(make_event("屏幕截图", platform="webchat"))

        self.assertFalse(
            router.config["quickaction"]["rules"][0]["__allow_rule_channel_scope"]
        )
        self.assertTrue(decision.handled)
        self.assertEqual(decision.action["type"], "screenshot_fullscreen")

    def test_quickaction_rule_channel_scope_is_ignored_even_when_legacy_switch_enabled(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickaction_rule_channel_scope_enabled": True,
                },
                "quickaction": {
                    "channel_scope": {"mode": "global"},
                    "confirm": {"enabled": False},
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "use_channel_scope": True,
                            "channel_scope": {
                                "mode": "include",
                                "include_channels": ["qq"],
                            },
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ],
                },
            }
        )

        decision = router.route(make_event("屏幕截图", platform="webchat"))

        self.assertFalse(
            router.config["quickaction"]["rules"][0]["__allow_rule_channel_scope"]
        )
        self.assertTrue(decision.handled)

    def test_quickcommand_rule_confirm_is_ignored_until_advanced_switch_enabled(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickcommand_rule_confirm_enabled": False,
                },
                "quickcommand": {
                    "enabled": True,
                    "channel_scope": {"mode": "global"},
                    "confirm": {"enabled": False},
                    "rules": [
                        {
                            "name": "关闭微信后台",
                            "trigger_keywords": ["关闭微信后台"],
                            "match_mode": "exact",
                            "confirm": {
                                "enabled": True,
                                "confirm_text": "确认执行",
                            },
                            "action": {
                                "type": "run_command",
                                "shell": "pwsh",
                                "command": "Write-Output ok",
                            },
                        }
                    ],
                },
            }
        )

        decision = router.route(make_event("关闭微信后台"))

        self.assertEqual(
            router.config["quickcommand"]["rules"][0]["__allow_rule_confirm"],
            False,
        )
        self.assertTrue(decision.handled)
        self.assertEqual(decision.action["type"], "run_command")

    def test_quickcommand_rule_confirm_is_ignored_even_when_legacy_switch_enabled(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickcommand_rule_confirm_enabled": True,
                },
                "quickcommand": {
                    "enabled": True,
                    "channel_scope": {"mode": "global"},
                    "confirm": {"enabled": False},
                    "rules": [
                        {
                            "name": "关闭微信后台",
                            "trigger_keywords": ["关闭微信后台"],
                            "match_mode": "exact",
                            "confirm": {
                                "enabled": True,
                                "confirm_text": "确认执行",
                            },
                            "action": {
                                "type": "run_command",
                                "shell": "pwsh",
                                "command": "Write-Output ok",
                            },
                        }
                    ],
                },
            }
        )

        decision = router.route(make_event("关闭微信后台"))

        self.assertFalse(router.config["quickcommand"]["rules"][0]["__allow_rule_confirm"])
        self.assertTrue(decision.handled)
        self.assertEqual(decision.action["type"], "run_command")

    def test_quickcommand_rule_channel_scope_is_ignored_until_advanced_switch_enabled(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickcommand_rule_channel_scope_enabled": False,
                },
                "quickcommand": {
                    "enabled": True,
                    "channel_scope": {"mode": "global"},
                    "confirm": {"enabled": False},
                    "rules": [
                        {
                            "name": "关闭微信后台",
                            "trigger_keywords": ["关闭微信后台"],
                            "match_mode": "exact",
                            "use_channel_scope": True,
                            "channel_scope": {
                                "mode": "include",
                                "include_channels": ["qq"],
                            },
                            "action": {
                                "type": "run_command",
                                "shell": "pwsh",
                                "command": "Write-Output ok",
                            },
                        }
                    ],
                },
            }
        )

        decision = router.route(make_event("关闭微信后台", platform="webchat"))

        self.assertEqual(
            router.config["quickcommand"]["rules"][0]["__allow_rule_channel_scope"],
            False,
        )
        self.assertTrue(decision.handled)
        self.assertEqual(decision.action["type"], "run_command")

    def test_quickcommand_rule_channel_scope_is_ignored_even_when_legacy_switch_enabled(self):
        router = LocalActionRouter(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickcommand_rule_channel_scope_enabled": True,
                },
                "quickcommand": {
                    "enabled": True,
                    "channel_scope": {"mode": "global"},
                    "confirm": {"enabled": False},
                    "rules": [
                        {
                            "name": "关闭微信后台",
                            "trigger_keywords": ["关闭微信后台"],
                            "match_mode": "exact",
                            "use_channel_scope": True,
                            "channel_scope": {
                                "mode": "include",
                                "include_channels": ["qq"],
                            },
                            "action": {
                                "type": "run_command",
                                "shell": "pwsh",
                                "command": "Write-Output ok",
                            },
                        }
                    ],
                },
            }
        )

        decision = router.route(make_event("关闭微信后台", platform="webchat"))

        self.assertFalse(
            router.config["quickcommand"]["rules"][0]["__allow_rule_channel_scope"]
        )
        self.assertTrue(decision.handled)

    def test_disabled_quickcommand_parent_switch_ignores_children(self):
        router = LocalActionRouter(
            {
                "quickcommand": {"enabled": False},
            }
        )

        decision = router.route(make_event("关闭微信后台"))

        self.assertFalse(router.config["quickcommand"]["enabled"])
        self.assertFalse(decision.handled)

    def test_legacy_plugin_enabled_flag_no_longer_disables_router(self):
        router = LocalActionRouter({"enabled": False})

        decision = router.route(make_event("屏幕截图"))

        self.assertTrue(decision.handled)
        self.assertEqual(decision.mode, "quickaction")


if __name__ == "__main__":
    unittest.main()
