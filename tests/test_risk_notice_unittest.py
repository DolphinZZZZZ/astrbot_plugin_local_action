import importlib
import asyncio
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


def install_astrbot_stubs():
    astrbot_mod = types.ModuleType("astrbot")
    api_mod = types.ModuleType("astrbot.api")
    event_mod = types.ModuleType("astrbot.api.event")
    message_components_mod = types.ModuleType("astrbot.api.message_components")
    star_mod = types.ModuleType("astrbot.api.star")

    class Logger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def exception(self, *args, **kwargs):
            pass

    class AstrMessageEvent:
        pass

    class MessageChain:
        def __init__(self):
            self.chain = []

        def message(self, text):
            self.chain.append(text)
            return self

        def file_image(self, path):
            self.chain.append(path)
            return self

    class Filter:
        class EventMessageType:
            ALL = "all"

        @staticmethod
        def event_message_type(*args, **kwargs):
            def decorator(func):
                return func

            return decorator

    class File:
        def __init__(self, name, file):
            self.name = name
            self.file = file

    class Context:
        pass

    class Star:
        def __init__(self, context):
            self.context = context

    class StarTools:
        @staticmethod
        def get_data_dir(name):
            return Path(tempfile.gettempdir()) / name

    def register(*args, **kwargs):
        def decorator(cls):
            return cls

        return decorator

    api_mod.AstrBotConfig = dict
    api_mod.logger = Logger()
    event_mod.AstrMessageEvent = AstrMessageEvent
    event_mod.MessageChain = MessageChain
    event_mod.filter = Filter
    message_components_mod.File = File
    star_mod.Context = Context
    star_mod.Star = Star
    star_mod.StarTools = StarTools
    star_mod.register = register

    sys.modules.setdefault("astrbot", astrbot_mod)
    sys.modules.setdefault("astrbot.api", api_mod)
    sys.modules.setdefault("astrbot.api.event", event_mod)
    sys.modules.setdefault("astrbot.api.message_components", message_components_mod)
    sys.modules.setdefault("astrbot.api.star", star_mod)


try:
    main = importlib.import_module("astrbot_plugin_local_action.main")
except ModuleNotFoundError as exc:
    if not str(exc).startswith("No module named 'astrbot"):
        raise
    install_astrbot_stubs()
    main = importlib.import_module("astrbot_plugin_local_action.main")


class FakeEvent:
    def __init__(
        self,
        message="hello",
        sender_id="10001",
        *,
        platform_name="webchat",
        unified_msg_origin="webchat:FriendMessage:10001",
        admin=True,
    ):
        self.message = message
        self.sender_id = sender_id
        self.platform_name = platform_name
        self.unified_msg_origin = unified_msg_origin
        self.admin = admin
        self.should_call_llm_values = []
        self.stopped = False

    def get_message_str(self):
        return self.message

    def get_sender_id(self):
        return self.sender_id

    def get_platform_name(self):
        return self.platform_name

    def is_admin(self):
        return self.admin

    def plain_result(self, text):
        return {"type": "plain", "text": text}

    def chain_result(self, chain):
        return {"type": "chain", "chain": chain}

    def should_call_llm(self, value):
        self.should_call_llm_values.append(value)

    def stop_event(self):
        self.stopped = True

    def track_temporary_local_file(self, path):
        pass


class AdvancedSettingsRiskNoticeTests(unittest.TestCase):
    def make_plugin(self, *, config=None, risk_ack=None, admin=True):
        plugin = main.LocalActionPlugin.__new__(main.LocalActionPlugin)
        plugin.router = types.SimpleNamespace(
            config=config or {"advanced_settings_enabled": True}
        )
        plugin.risk_ack = risk_ack or {}
        plugin.saved = False
        plugin._is_admin = lambda event: admin

        def save_risk_ack():
            plugin.saved = True

        plugin._save_risk_ack = save_risk_ack
        return plugin

    def test_old_chat_risk_notice_is_not_forced_for_first_admin_message(self):
        plugin = self.make_plugin()

        decision = plugin.router.config

        self.assertEqual(decision, {"advanced_settings_enabled": True})
        self.assertFalse(hasattr(plugin, "_handle_advanced_settings_risk"))

    def test_settings_risk_ack_persists_and_returns_api_payload(self):
        plugin = self.make_plugin(
            config={
                "advanced_settings_enabled": True,
                "advanced_settings_risk_notice": {
                    "enabled": False,
                    "require_acknowledgement": False,
                    "notice_text": "custom notice",
                },
            }
        )

        response = asyncio.run(plugin.api_settings_risk_ack())

        self.assertEqual(response["status"], "ok")
        self.assertTrue(response["data"]["settings_risk_notice_acknowledged"])
        self.assertTrue(plugin.risk_ack["settings_risk_notice_acknowledged"])
        self.assertTrue(plugin.saved)

    def test_user_risk_notice_is_sent_once_per_user(self):
        plugin = self.make_plugin()

        first = plugin._consume_user_risk_notice(
            FakeEvent(sender_id="10001", unified_msg_origin="web:session-a"), "quickaction"
        )
        same_user_other_session = plugin._consume_user_risk_notice(
            FakeEvent(sender_id="10001", unified_msg_origin="web:session-b"), "quickcommand"
        )
        other_user = plugin._consume_user_risk_notice(
            FakeEvent(sender_id="10002", unified_msg_origin="web:session-c"), "quickcommand"
        )

        self.assertEqual(first, main.SESSION_RISK_NOTICE)
        self.assertIsNone(same_user_other_session)
        self.assertEqual(other_user, main.SESSION_RISK_NOTICE)
        self.assertTrue(plugin.saved)

    def test_user_risk_notice_ignores_non_action_decisions(self):
        plugin = self.make_plugin()

        self.assertIsNone(plugin._consume_user_risk_notice(FakeEvent(), None))
        self.assertEqual(plugin.risk_ack, {})

    def test_handler_sends_user_risk_notice_then_executes_action(self):
        plugin = self.make_plugin(config={})
        plugin.config = {
            "quickaction": {
                "enabled": True,
                "confirm": {"enabled": False},
                "rules": [
                    {
                        "action_name": "屏幕截图",
                        "trigger_keywords": ["屏幕截图"],
                        "match_mode": "exact",
                        "action": {"type": "screenshot_fullscreen"},
                    }
                ],
            }
        }
        plugin.router = main.LocalActionRouter(dict(plugin.config))
        plugin.context = types.SimpleNamespace(get_config=lambda _: {"admins_id": []})
        plugin._save_sleep_state_if_needed = lambda: None

        async def execute(mode, rule):
            return types.SimpleNamespace(ok=True, text="done", images=[], files=[])

        plugin.executor = types.SimpleNamespace(
            config=plugin.router.config,
            execute=execute,
        )
        event = FakeEvent("屏幕截图")

        async def collect():
            return [item async for item in plugin.localaction_handler(event)]

        results = asyncio.run(collect())

        self.assertEqual(results[0], {"type": "plain", "text": main.SESSION_RISK_NOTICE})
        self.assertEqual(results[1]["type"], "chain")
        self.assertIn("done", results[1]["chain"][0])
        self.assertTrue(event.stopped)


class RulesApiTests(unittest.TestCase):
    def make_plugin(self, config):
        plugin = main.LocalActionPlugin.__new__(main.LocalActionPlugin)
        plugin.config = dict(config)
        plugin.router = main.LocalActionRouter(dict(config))
        plugin.executor = types.SimpleNamespace(config=plugin.router.config)
        return plugin

    def command_action(self, command="Write-Output ok"):
        return {
            "type": "run_command",
            "shell": "pwsh",
            "command": command,
            "timeout": 5,
        }

    def test_save_rules_updates_table_columns_and_preserves_rule_details(self):
        plugin = self.make_plugin(
            {
                "advanced_settings_enabled": True,
                "quickaction": {
                    "rules": [
                        {
                            "enabled": True,
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "contains",
                            "channel_scope": {"mode": "custom", "platform_names": ["webchat"]},
                            "confirm": {"enabled": True, "confirm_text": "确认"},
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ]
                },
            }
        )

        response = plugin._save_rules(
            {
                "mode": "quickaction",
                "rules": [
                    {
                        "index": 0,
                        "enabled": False,
                        "action_name": "截图",
                        "trigger_keywords": "截图\n截屏",
                        "match_mode": "exact",
                    }
                ],
            }
        )

        self.assertEqual(response["status"], "ok")
        rule = plugin.config["quickaction"]["rules"][0]
        self.assertFalse(rule["enabled"])
        self.assertEqual(rule["name"], "截图")
        self.assertEqual(rule["action_name"], "截图")
        self.assertEqual(rule["trigger_keywords"], ["截图", "截屏"])
        self.assertEqual(rule["match_mode"], "exact")
        self.assertEqual(rule["action"], {"type": "screenshot_fullscreen"})
        self.assertEqual(rule["confirm"], {"enabled": True, "confirm_text": "确认"})
        self.assertEqual(rule["channel_scope"]["platform_names"], ["webchat"])

    def test_save_rules_removes_ui_only_settings_entry(self):
        plugin = self.make_plugin(
            {
                "__localaction_settings_entry": "打开",
                "__localaction_plugin_ui_notice": {},
                "quickaction": {
                    "rules": [
                        {
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "contains",
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ]
                },
            }
        )

        response = plugin._save_rules(
            {
                "mode": "quickaction",
                "rules": [
                    {
                        "index": 0,
                        "enabled": True,
                        "action_name": "屏幕截图",
                        "trigger_keywords": ["屏幕截图"],
                        "match_mode": "contains",
                    }
                ],
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertNotIn("__localaction_settings_entry", plugin.config)
        self.assertNotIn("__localaction_plugin_ui_notice", plugin.config)

    def test_save_quickcommand_rules_accepts_command_name(self):
        plugin = self.make_plugin(
            {
                "quickcommand": {
                    "enabled": True,
                    "rules": [
                        {
                            "command_name": "关闭微信后台",
                            "trigger_keywords": ["关闭微信后台"],
                            "match_mode": "exact",
                            "action": self.command_action(),
                        }
                    ],
                },
            }
        )

        response = plugin._save_rules(
            {
                "mode": "quickcommand",
                "rules": [
                    {
                        "index": 0,
                        "enabled": True,
                        "command_name": "关微信",
                        "trigger_keywords": ["关微信"],
                        "match_mode": "exact",
                    }
                ],
            }
        )

        self.assertEqual(response["status"], "ok")
        rule = plugin.config["quickcommand"]["rules"][0]
        self.assertEqual(rule["command_name"], "关微信")
        self.assertEqual(rule["name"], "关微信")

    def test_save_rules_full_replaces_order_and_action_parameters(self):
        plugin = self.make_plugin(
            {
                "quickaction": {
                    "enabled": True,
                    "rules": [
                        {
                            "action_name": "旧规则",
                            "trigger_keywords": ["旧规则"],
                            "match_mode": "contains",
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ],
                },
            }
        )

        response = plugin._save_rules_full(
            {
                "mode": "quickaction",
                "enabled": False,
                "rules": [
                    {
                        "enabled": True,
                        "action_name": "新窗口截图",
                        "trigger_keywords": "截图窗口\n窗口截图",
                        "match_mode": "prefix",
                        "action": {
                            "type": "screenshot_window",
                            "selector": {
                                "process": "Code.exe",
                                "title_contains": "main.py",
                            },
                        },
                    },
                    {
                        "enabled": False,
                        "action_name": "日志尾部",
                        "trigger_keywords": ["日志尾部"],
                        "match_mode": "exact",
                        "action": {
                            "type": "tail_file",
                            "path": "C:/logs/app.log",
                            "lines": "50",
                        },
                    },
                ],
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertFalse(plugin.config["quickaction"]["enabled"])
        rules = plugin.config["quickaction"]["rules"]
        self.assertEqual([rule["action_name"] for rule in rules], ["新窗口截图", "日志尾部"])
        self.assertEqual(rules[0]["trigger_keywords"], ["截图窗口", "窗口截图"])
        self.assertEqual(rules[0]["match_mode"], "prefix")
        self.assertEqual(
            rules[0]["action"],
            {
                "type": "screenshot_window",
                "selector": {
                    "process": "Code.exe",
                    "title_contains": "main.py",
                },
            },
        )
        self.assertFalse(rules[1]["enabled"])
        self.assertEqual(
            rules[1]["action"],
            {"type": "tail_file", "path": "C:/logs/app.log", "lines": 50},
        )

    def test_save_rules_full_persists_notice_template(self):
        plugin = self.make_plugin(
            {
                "quickcommand": {
                    "enabled": True,
                    "notice_template": "旧提示：{command_name}",
                    "channel_scope": {"mode": "global"},
                    "confirm": {"enabled": False},
                    "rules": [],
                },
            }
        )

        response = plugin._save_rules_full(
            {
                "mode": "quickcommand",
                "enabled": True,
                "notice_template": "新提示：{command_name}",
                "rules": [
                    {
                        "enabled": True,
                        "command_name": "关微信",
                        "trigger_keywords": ["关微信"],
                        "match_mode": "exact",
                        "action": self.command_action(),
                    }
                ],
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(
            plugin.config["quickcommand"]["notice_template"],
            "新提示：{command_name}",
        )
        decision = plugin.router.route(
            main.EventView(
                message="关微信",
                sender_id="10001",
                platform_name="web",
                channel_type="web",
                is_admin=True,
                unified_msg_origin="web:10001",
            )
        )
        self.assertEqual(decision.notice_text, "新提示：关微信")

    def test_save_rules_full_persists_mode_confirm(self):
        plugin = self.make_plugin(
            {
                "quickaction": {
                    "enabled": True,
                    "notice_template": "已执行：{action_name}",
                    "confirm": {"enabled": False, "confirm_text": "确认", "timeout_seconds": 30},
                    "rules": [],
                },
            }
        )

        response = plugin._save_rules_full(
            {
                "mode": "quickaction",
                "enabled": True,
                "notice_template": "已执行：{action_name}",
                "confirm": {
                    "enabled": True,
                    "confirm_text": "确认截图",
                    "timeout_seconds": 45,
                },
                "rules": [
                    {
                        "enabled": True,
                        "action_name": "截图",
                        "trigger_keywords": ["截图"],
                        "match_mode": "contains",
                        "action": {"type": "screenshot_fullscreen"},
                    }
                ],
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(
            plugin.config["quickaction"]["confirm"],
            {"enabled": True, "confirm_text": "确认截图", "timeout_seconds": 45},
        )

    def test_save_rules_full_persists_mode_admin_and_channel_scope(self):
        plugin = self.make_plugin(
            {
                "quickaction": {
                    "enabled": True,
                    "admin_only": True,
                    "channel_scope": {"mode": "global"},
                    "rules": [],
                },
            }
        )

        response = plugin._save_rules_full(
            {
                "mode": "quickaction",
                "enabled": True,
                "admin_only": False,
                "channel_scope": {
                    "mode": "include",
                    "include_channels": "qq\nweb",
                    "exclude_channels": ["client"],
                    "platform_names": ["ignored"],
                },
                "rules": [
                    {
                        "enabled": True,
                        "action_name": "截图",
                        "trigger_keywords": ["截图"],
                        "match_mode": "contains",
                        "action": {"type": "screenshot_fullscreen"},
                    }
                ],
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertFalse(plugin.config["quickaction"]["admin_only"])
        self.assertEqual(
            plugin.config["quickaction"]["channel_scope"],
            {
                "mode": "include",
                "include_channels": ["qq", "web"],
                "exclude_channels": ["client"],
                "platform_names": ["ignored"],
            },
        )

    def test_initial_channel_scope_defaults_only_apply_to_unmodified_scopes(self):
        defaults = main._initial_channel_scope_defaults(
            {},
            main.LocalActionRouter({}).config,
            {"active_channels": ["qq_official", "webchat"]},
        )

        self.assertEqual(defaults["mode"], "include")
        self.assertEqual(defaults["active_channels"], ["qq_official", "webchat"])
        self.assertTrue(defaults["apply_modes"]["quickaction"])
        self.assertTrue(defaults["apply_modes"]["quickcommand"])

        modified = main._initial_channel_scope_defaults(
            {
                "quickaction": {
                    "channel_scope": {
                        "mode": "include",
                        "include_channels": ["qq"],
                    }
                }
            },
            main.LocalActionRouter({}).config,
            {"active_channels": ["qq_official"]},
        )

        self.assertFalse(modified["apply_modes"]["quickaction"])
        self.assertTrue(modified["apply_modes"]["quickcommand"])

    def test_save_rules_full_normalizes_unknown_channel_scope_mode(self):
        plugin = self.make_plugin(
            {
                "quickaction": {
                    "enabled": True,
                    "channel_scope": {"mode": "global"},
                    "rules": [],
                },
            }
        )

        response = plugin._save_rules_full(
            {
                "mode": "quickaction",
                "channel_scope": {
                    "mode": "invalid",
                    "include_channels": ["qq"],
                },
                "rules": [],
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(
            plugin.config["quickaction"]["channel_scope"],
            {
                "mode": "global",
                "include_channels": ["qq"],
                "exclude_channels": [],
                "platform_names": [],
            },
        )

    def test_save_rules_full_syncs_quickcommand_channel_scope(self):
        plugin = self.make_plugin(
            {
                "quickaction": {
                    "enabled": True,
                    "channel_scope": {
                        "mode": "custom",
                        "include_channels": [],
                        "exclude_channels": [],
                        "platform_names": ["webchat"],
                    },
                    "rules": [],
                },
                "quickcommand": {
                    "enabled": True,
                    "sync_with_quickaction_channel_scope": False,
                    "channel_scope": {"mode": "include", "include_channels": ["qq"]},
                    "rules": [],
                },
            }
        )

        response = plugin._save_rules_full(
            {
                "mode": "quickcommand",
                "enabled": True,
                "sync_with_quickaction_channel_scope": True,
                "channel_scope": {"mode": "exclude", "exclude_channels": ["web"]},
                "rules": [
                    {
                        "enabled": True,
                        "command_name": "关微信",
                        "trigger_keywords": ["关微信"],
                        "match_mode": "exact",
                        "action": self.command_action(),
                    }
                ],
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertTrue(
            plugin.config["quickcommand"]["sync_with_quickaction_channel_scope"]
        )
        self.assertEqual(
            plugin.config["quickcommand"]["channel_scope"],
            plugin.config["quickaction"]["channel_scope"],
        )

    def test_save_rules_full_persists_quickcommand_ssh_mode(self):
        plugin = self.make_plugin({"quickcommand": {"enabled": True, "rules": []}})

        response = plugin._save_rules_full(
            {
                "mode": "quickcommand",
                "enabled": True,
                "ssh_mode": {
                    "enabled": True,
                    "trigger_keywords": "shell\nssh",
                    "exit_keywords": ["exit", "quit"],
                    "match_mode": "prefix",
                    "shell": "cmd",
                    "timeout": "12",
                },
                "rules": [],
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(
            plugin.config["quickcommand"]["ssh_mode"],
            {
                "enabled": True,
                "trigger_keywords": ["shell", "ssh"],
                "exit_keywords": ["exit", "quit"],
                "match_mode": "prefix",
                "shell": "cmd",
                "timeout": 12,
            },
        )

    def test_save_rules_full_defaults_quickcommand_ssh_mode_timeout_to_1000(self):
        plugin = self.make_plugin({"quickcommand": {"enabled": True, "rules": []}})

        response = plugin._save_rules_full(
            {
                "mode": "quickcommand",
                "enabled": True,
                "ssh_mode": {
                    "enabled": True,
                    "timeout": "",
                },
                "rules": [],
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(plugin.config["quickcommand"]["ssh_mode"]["timeout"], 1000)

    def test_migrate_quickcommand_ssh_mode_old_default_timeout_to_1000(self):
        config = {"quickcommand": {"ssh_mode": {"timeout": 10}}}

        changed = main._migrate_quickcommand_shell_session_timeout(config)

        self.assertTrue(changed)
        self.assertEqual(config["quickcommand"]["ssh_mode"]["timeout"], 1000)

    def test_migrate_quickcommand_ssh_mode_keeps_custom_timeout(self):
        config = {"quickcommand": {"ssh_mode": {"timeout": 12}}}

        changed = main._migrate_quickcommand_shell_session_timeout(config)

        self.assertFalse(changed)
        self.assertEqual(config["quickcommand"]["ssh_mode"]["timeout"], 12)

    def test_save_rules_full_rejects_unknown_action_type(self):
        plugin = self.make_plugin({"quickaction": {"rules": []}})

        response = plugin._save_rules_full(
            {
                "mode": "quickaction",
                "rules": [
                    {
                        "action_name": "坏规则",
                        "trigger_keywords": ["坏规则"],
                        "action": {"type": "not_supported"},
                    }
                ],
            }
        )

        self.assertEqual(response["status"], "error")
        self.assertIn("不支持的动作类型", response["message"])

    def test_save_rules_full_rejects_quickcommand_non_command_action(self):
        plugin = self.make_plugin({"quickcommand": {"rules": []}})

        response = plugin._save_rules_full(
            {
                "mode": "quickcommand",
                "rules": [
                    {
                        "command_name": "截图",
                        "trigger_keywords": ["截图"],
                        "action": {"type": "screenshot_fullscreen"},
                    }
                ],
            }
        )

        self.assertEqual(response["status"], "error")
        self.assertIn("QuickCommand 只支持执行命令", response["message"])

    def test_save_rules_full_persists_incomplete_draft_rule(self):
        plugin = self.make_plugin({"quickcommand": {"enabled": True, "rules": []}})

        response = plugin._save_rules_full(
            {
                "mode": "quickcommand",
                "rules": [
                    {
                        "enabled": True,
                        "command_name": "New QuickCommand",
                        "trigger_keywords": [],
                        "match_mode": "contains",
                        "action": {"type": ""},
                    }
                ],
            }
        )

        self.assertEqual(response["status"], "ok")
        rule = plugin.config["quickcommand"]["rules"][0]
        self.assertTrue(rule["enabled"])
        self.assertEqual(rule["command_name"], "New QuickCommand")
        self.assertEqual(rule["trigger_keywords"], [])
        self.assertEqual(rule["action"], {"type": ""})

        decision = plugin.router.route(
            main.EventView(
                message="New QuickCommand",
                sender_id="10001",
                platform_name="web",
                channel_type="web",
                is_admin=True,
                unified_msg_origin="web:10001",
            )
        )
        self.assertFalse(decision.handled)

    def test_save_rules_full_persists_missing_command_as_draft(self):
        plugin = self.make_plugin({"quickcommand": {"enabled": True, "rules": []}})

        response = plugin._save_rules_full(
            {
                "mode": "quickcommand",
                "rules": [
                    {
                        "enabled": True,
                        "command_name": "待选命令",
                        "trigger_keywords": ["待选命令"],
                        "match_mode": "exact",
                        "action": {"type": "run_command", "shell": "pwsh", "command": "", "timeout": 5},
                    }
                ],
            }
        )

        self.assertEqual(response["status"], "ok")
        rule = plugin.config["quickcommand"]["rules"][0]
        self.assertEqual(
            rule["action"], {"type": "run_command", "shell": "pwsh", "command": "", "timeout": 5}
        )

        decision = plugin.router.route(
            main.EventView(
                message="待选命令",
                sender_id="10001",
                platform_name="web",
                channel_type="web",
                is_admin=True,
                unified_msg_origin="web:10001",
            )
        )
        self.assertFalse(decision.handled)

    def test_save_advanced_settings_updates_flat_runtime_fields(self):
        plugin = self.make_plugin(
            {
                "advanced_settings_enabled": False,
                "max_file_size_mb": 50,
                "quickaction": {
                    "enabled": True,
                    "rules": [
                        {
                            "action_name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ],
                },
                "quickcommand": {
                    "enabled": True,
                    "rules": [
                        {
                            "command_name": "关闭微信后台",
                            "trigger_keywords": ["关闭微信后台"],
                            "action": self.command_action(),
                        }
                    ],
                },
            }
        )

        response = plugin._save_advanced_settings(
            {
                "advanced_settings_enabled": True,
                "max_file_size_mb": "25",
                "quickaction_rule_confirm_enabled": True,
                "quickaction_rule_channel_scope_enabled": True,
                "quickcommand_rule_confirm_enabled": True,
                "quickcommand_rule_channel_scope_enabled": True,
                "sleep_wake": {
                    "enabled": False,
                    "sleep_keywords": "休眠\n暂停",
                    "permanent_sleep_keywords": ["永久休眠"],
                    "wake_keywords": "唤醒",
                    "wake_all_keywords": "全部唤醒\n唤醒全部",
                    "status_keywords": "休眠状态",
                    "default_sleep_seconds": "90",
                    "persist_sleep_state": False,
                    "allow_global_sleep": False,
                    "allow_mode_sleep": True,
                    "allow_rule_sleep": False,
                    "admin_only": False,
                },
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertIn("advanced_settings", plugin.config)
        self.assertTrue(plugin.config["advanced_settings"]["enabled"])
        self.assertEqual(plugin.config["advanced_settings"]["max_file_size_mb"], "25")
        self.assertFalse(
            plugin.config["advanced_settings"]["quickaction_rule_confirm_enabled"]
        )
        self.assertTrue(plugin.config["advanced_settings_enabled"])
        self.assertEqual(plugin.config["max_file_size_mb"], 25)
        self.assertFalse(plugin.config["quickaction_rule_confirm_enabled"])
        self.assertFalse(plugin.config["quickaction_rule_channel_scope_enabled"])
        self.assertFalse(plugin.config["quickcommand_rule_confirm_enabled"])
        self.assertFalse(plugin.config["quickcommand_rule_channel_scope_enabled"])
        self.assertFalse(plugin.config["quickaction"]["rules"][0]["__allow_rule_confirm"])
        self.assertFalse(plugin.config["quickcommand"]["rules"][0]["__allow_rule_channel_scope"])
        self.assertFalse(plugin.config["sleep_wake"]["enabled"])
        self.assertEqual(plugin.config["sleep_wake"]["sleep_keywords"], ["休眠", "暂停"])
        self.assertEqual(
            plugin.config["advanced_settings"]["sleep_wake"]["sleep_keywords"],
            ["休眠", "暂停"],
        )
        self.assertEqual(plugin.config["sleep_wake"]["status_keywords"], ["休眠状态"])
        self.assertEqual(plugin.config["sleep_wake"]["default_sleep_seconds"], 90)
        self.assertTrue(plugin.config["sleep_wake"]["persist_sleep_state"])
        self.assertTrue(plugin.config["sleep_wake"]["allow_global_sleep"])
        self.assertFalse(plugin.config["sleep_wake"]["allow_mode_sleep"])
        self.assertFalse(plugin.config["sleep_wake"]["allow_rule_sleep"])

    def test_save_advanced_settings_updates_quickaction_allowed_paths(self):
        plugin = self.make_plugin(
            {
                "advanced_settings_enabled": True,
                "quickaction": {"allowed_paths": ["C:/old"]},
            }
        )

        response = plugin._save_advanced_settings(
            {
                "advanced_settings_enabled": True,
                "quickaction_allowed_paths": "C:/allowed\n\nD:/logs/app.log",
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(
            plugin.config["quickaction"]["allowed_paths"],
            ["C:/allowed", "D:/logs/app.log"],
        )

    def test_save_advanced_settings_blank_allowed_paths_disables_whitelist(self):
        plugin = self.make_plugin(
            {
                "advanced_settings_enabled": True,
                "quickaction": {"allowed_paths": ["C:/old"]},
            }
        )

        response = plugin._save_advanced_settings(
            {
                "advanced_settings_enabled": True,
                "quickaction_allowed_paths": "",
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(plugin.config["quickaction"]["allowed_paths"], [])

    @unittest.skipUnless(os.name == "nt", "Windows-only file picker behavior")
    def test_local_path_picker_supports_directory_selection(self):
        fake_tk = types.ModuleType("tkinter")
        fake_filedialog = types.ModuleType("tkinter.filedialog")

        class FakeRoot:
            def withdraw(self):
                pass

            def attributes(self, *args):
                pass

            def destroy(self):
                pass

        fake_tk.Tk = FakeRoot
        fake_filedialog.askopenfilename = mock.Mock(return_value="C:/file.txt")
        fake_filedialog.askdirectory = mock.Mock(return_value="C:/allowed")

        with mock.patch.dict(
            sys.modules,
            {"tkinter": fake_tk, "tkinter.filedialog": fake_filedialog},
        ):
            self.assertEqual(main._pick_local_path("directory"), "C:/allowed")

        fake_filedialog.askdirectory.assert_called_once()
        fake_filedialog.askopenfilename.assert_not_called()

    def test_save_advanced_settings_preserves_zero_file_size_limit(self):
        plugin = self.make_plugin({})

        response = plugin._save_advanced_settings(
            {
                "advanced_settings_enabled": True,
                "max_file_size_mb": 0,
                "sleep_wake": {"default_sleep_seconds": 0},
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(plugin.config["max_file_size_mb"], 0)
        self.assertEqual(plugin.config["sleep_wake"]["default_sleep_seconds"], 1)

    def test_save_advanced_settings_accepts_kb_size_limit(self):
        plugin = self.make_plugin({})

        response = plugin._save_advanced_settings(
            {
                "advanced_settings_enabled": True,
                "max_file_size_mb": 0.5,
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(plugin.config["max_file_size_mb"], 0.5)
        self.assertEqual(plugin.config["advanced_settings"]["max_file_size_mb"], "0.5")

    def test_save_advanced_settings_treats_negative_size_limit_as_unlimited(self):
        plugin = self.make_plugin({})

        response = plugin._save_advanced_settings(
            {
                "advanced_settings_enabled": True,
                "max_file_size_mb": -1,
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertIsNone(plugin.config["max_file_size_mb"])
        self.assertEqual(plugin.config["advanced_settings"]["max_file_size_mb"], "")

    def test_save_advanced_settings_treats_blank_size_limit_as_unlimited(self):
        plugin = self.make_plugin({})

        response = plugin._save_advanced_settings(
            {
                "advanced_settings_enabled": True,
                "max_file_size_mb": "",
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertIsNone(plugin.config["max_file_size_mb"])
        self.assertEqual(plugin.config["advanced_settings"]["max_file_size_mb"], "")

    def test_advanced_settings_schema_value_keeps_blank_file_size_limit_blank(self):
        value = main._advanced_settings_schema_value(
            {"advanced_settings_enabled": True, "max_file_size_mb": None}
        )

        self.assertEqual(value["max_file_size_mb"], "")

    def test_save_rule_enabled_states_updates_only_enabled_values(self):
        plugin = self.make_plugin(
            {
                "quickaction": {
                    "enabled": True,
                    "rules": [
                        {
                            "enabled": True,
                            "action_name": "原规则",
                            "trigger_keywords": ["原关键词"],
                            "match_mode": "contains",
                            "action": {"type": "screenshot_fullscreen"},
                        },
                        {
                            "enabled": False,
                            "action_name": "第二条",
                            "trigger_keywords": ["第二条"],
                            "match_mode": "exact",
                            "action": {"type": "tail_file", "path": "C:/logs/app.log"},
                        },
                    ],
                },
            }
        )

        response = plugin._save_rule_enabled_states(
            {
                "mode": "quickaction",
                "enabled": False,
                "rules": [
                    {"index": 0, "enabled": False},
                    {"index": 1, "enabled": True},
                ],
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertFalse(plugin.config["quickaction"]["enabled"])
        rules = plugin.config["quickaction"]["rules"]
        self.assertEqual([rule["enabled"] for rule in rules], [False, True])
        self.assertEqual(rules[0]["action_name"], "原规则")
        self.assertEqual(rules[0]["trigger_keywords"], ["原关键词"])
        self.assertEqual(rules[0]["match_mode"], "contains")
        self.assertEqual(rules[0]["action"], {"type": "screenshot_fullscreen"})
        self.assertEqual(rules[1]["action"], {"type": "tail_file", "path": "C:/logs/app.log"})


class ConfigMigrationTests(unittest.TestCase):
    class SaveableConfig(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.saved = None

        def save_config(self, replace_config=None):
            self.saved = dict(replace_config or self)
            if replace_config:
                self.clear()
                self.update(replace_config)

    class Context:
        pass

    def test_plugin_init_adds_template_key_for_existing_rules(self):
        config = self.SaveableConfig(
            {
                "quickaction": {
                    "channel_scope": {"mode": "global"},
                    "rules": [
                        {
                            "enabled": True,
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "channel_scope": {
                                "mode": "include",
                                "include_channels": ["qq"],
                            },
                        }
                    ]
                }
            }
        )

        main.LocalActionPlugin(self.Context(), config=config)

        self.assertEqual(
            config["quickaction"]["rules"][0]["__template_key"],
            "rule",
        )
        self.assertEqual(config["quickaction"]["rules"][0]["action_name"], "屏幕截图")
        self.assertTrue(config["quickaction"]["rules"][0]["use_channel_scope"])
        self.assertIsNotNone(config.saved)

    def test_plugin_init_removes_ui_only_settings_entry(self):
        config = self.SaveableConfig(
            {
                "__localaction_settings_entry": {},
                "__localaction_plugin_ui_notice": {},
                "quickaction": {
                    "rules": [
                        {
                            "enabled": True,
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ],
                },
            }
        )

        main.LocalActionPlugin(self.Context(), config=config)

        self.assertNotIn("__localaction_settings_entry", config)
        self.assertNotIn("__localaction_plugin_ui_notice", config)
        self.assertIsNotNone(config.saved)

    def test_plugin_init_persists_normalized_sleep_controls(self):
        config = self.SaveableConfig(
            {
                "advanced_settings_enabled": True,
                "sleep_wake": {
                    "enabled": True,
                    "status_keywords": ["休眠状态", "LocalAction状态"],
                    "persist_sleep_state": False,
                    "allow_global_sleep": False,
                    "allow_mode_sleep": True,
                    "allow_rule_sleep": True,
                },
                "advanced_settings": {
                    "enabled": True,
                    "sleep_wake": {
                        "enabled": True,
                        "status_keywords": ["休眠状态", "LocalAction状态"],
                        "persist_sleep_state": False,
                        "allow_global_sleep": False,
                        "allow_mode_sleep": True,
                        "allow_rule_sleep": True,
                    },
                },
            }
        )

        main.LocalActionPlugin(self.Context(), config=config)

        self.assertEqual(config["sleep_wake"]["status_keywords"], ["休眠状态"])
        self.assertEqual(
            config["advanced_settings"]["sleep_wake"]["status_keywords"], ["休眠状态"]
        )
        self.assertTrue(config["sleep_wake"]["persist_sleep_state"])
        self.assertTrue(config["advanced_settings"]["sleep_wake"]["persist_sleep_state"])
        self.assertTrue(config["sleep_wake"]["allow_global_sleep"])
        self.assertTrue(config["advanced_settings"]["sleep_wake"]["allow_global_sleep"])
        self.assertFalse(config["sleep_wake"]["allow_mode_sleep"])
        self.assertFalse(config["sleep_wake"]["allow_rule_sleep"])
        self.assertFalse(config["advanced_settings"]["sleep_wake"]["allow_mode_sleep"])
        self.assertFalse(config["advanced_settings"]["sleep_wake"]["allow_rule_sleep"])
        self.assertIsNotNone(config.saved)

    def test_sleep_state_is_always_persisted_with_temporary_timer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            config = self.SaveableConfig(
                {
                    "advanced_settings_enabled": True,
                    "sleep_wake": {
                        "enabled": True,
                        "sleep_match_mode": "prefix",
                        "persist_sleep_state": False,
                        "default_sleep_seconds": 90,
                    },
                }
            )
            with mock.patch.object(main.StarTools, "get_data_dir", return_value=data_dir):
                plugin = main.LocalActionPlugin(self.Context(), config=config)
            plugin.router.now_func = lambda: 1000.0

            sleep_decision = plugin.router.route(main.EventView(message="休眠 90秒", is_admin=True))
            plugin._save_sleep_state_if_needed()

            self.assertTrue(sleep_decision.handled)
            saved = json.loads((data_dir / "sleep_state.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["global"]["until"], 1090.0)
            self.assertFalse(saved["global"]["forever"])

            restored = main.SleepState.from_json(saved)
            self.assertTrue(restored.is_global_sleeping(1089.0))
            self.assertFalse(restored.is_global_sleeping(1091.0))
            self.assertTrue(config["sleep_wake"]["persist_sleep_state"])

            plugin.router.route(main.EventView(message="唤醒", is_admin=True))
            plugin._save_sleep_state_if_needed()

            cleared = json.loads((data_dir / "sleep_state.json").read_text(encoding="utf-8"))
            self.assertFalse(cleared["global"]["forever"])
            self.assertIsNone(cleared["global"]["until"])

    def test_plugin_init_disables_rule_advanced_visibility_flags(self):
        config = self.SaveableConfig(
            {
                "advanced_settings": {
                    "enabled": True,
                    "quickaction_rule_confirm_enabled": True,
                    "quickaction_rule_channel_scope_enabled": True,
                    "quickcommand_rule_confirm_enabled": True,
                    "quickcommand_rule_channel_scope_enabled": True,
                },
                "quickaction": {
                    "enabled": True,
                    "rules": [
                        {
                            "enabled": True,
                            "name": "屏幕截图",
                            "trigger_keywords": ["屏幕截图"],
                            "match_mode": "exact",
                            "action": {"type": "screenshot_fullscreen"},
                        }
                    ],
                },
                "quickcommand": {
                    "enabled": True,
                    "commands": {
                        "close_weixin": {
                            "name": "关闭微信后台",
                            "shell": "pwsh",
                            "command": "Write-Output ok",
                            "timeout": 5,
                        },
                    },
                    "rules": [
                        {
                            "enabled": True,
                            "name": "关闭微信后台",
                            "trigger_keywords": ["关闭微信后台"],
                            "match_mode": "exact",
                            "action": {
                                "type": "run_predefined_command",
                                "command_id": "close_weixin",
                            },
                        }
                    ],
                },
            }
        )

        main.LocalActionPlugin(self.Context(), config=config)

        for mode in ("quickaction", "quickcommand"):
            rule = config[mode]["rules"][0]
            self.assertFalse(rule["__allow_rule_confirm"])
            self.assertFalse(rule["__allow_rule_channel_scope"])
        self.assertEqual(config["quickaction"]["rules"][0]["action_name"], "屏幕截图")
        self.assertEqual(config["quickcommand"]["rules"][0]["command_name"], "关闭微信后台")
        self.assertEqual(
            config["quickcommand"]["rules"][0]["action"],
            {
                "type": "run_command",
                "shell": "pwsh",
                "command": "Write-Output ok",
                "timeout": 5,
            },
        )
        self.assertIsNotNone(config.saved)


if __name__ == "__main__":
    unittest.main()
